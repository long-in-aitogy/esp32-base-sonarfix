#include "functions/backend/Storage_Status.h"
#include "functions/backend/Backend_Agent_Internal.h"
#include "hardware/Wifi_Credentials.h"
#include <Preferences.h>
#include <nvs.h>
#include <esp_partition.h>
#include <esp_ota_ops.h>
#include <type_traits>
#include <memory>

namespace {
size_t obsoleteWifiKeys() {
    nvs_handle_t handle;
    if (nvs_open("wifi_config", NVS_READONLY, &handle) != ESP_OK) return 0;
    size_t count = 0;
    for (const char *key : {"profiles", "ap_pass"}) {
        size_t length = 0;
        if (nvs_get_str(handle, key, nullptr, &length) == ESP_OK) ++count;
    }
    nvs_close(handle);
    return count;
}
void partitionStatus(JsonArray partitions, const char *label) {
    JsonObject item = partitions.createNestedObject();
    item["id"] = label;
    nvs_stats_t stats{};
    const esp_err_t result = nvs_get_stats(label, &stats);
    item["available"] = result == ESP_OK;
    if (result != ESP_OK) return;
    item["used_entries"] = stats.used_entries;
    item["free_entries"] = stats.free_entries;
    item["total_entries"] = stats.total_entries;
    item["namespaces"] = stats.namespace_count;
    const esp_partition_t *partition = esp_partition_find_first(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_NVS, label);
    if (partition) item["size_bytes"] = partition->size;
}
}

void appendStorageStatus(JsonObject system) {
    JsonObject memory = system["memory"];
    memory["minimum_free_heap_bytes"] = ESP.getMinFreeHeap();
    memory["largest_free_block_bytes"] = ESP.getMaxAllocHeap();
    JsonObject disk = system["disk"];
    const esp_partition_t *app = esp_ota_get_running_partition();
    if (app) disk["app_capacity_bytes"] = app->size;
    // Physical flash also holds OTA/NVS/data partitions; it is not one free pool.
    disk["firmware_bytes"] = disk["used_bytes"];
    JsonObject nvs = system.createNestedObject("nvs");
    nvs["cleanup_supported"] = true;
    nvs["inventory_supported"] = true;
    nvs["sampled_at_ms"] = millis();
    partitionStatus(nvs.createNestedArray("partitions"), "nvs");
    partitionStatus(nvs["partitions"].as<JsonArray>(), "agent_state");
    JsonArray groups = nvs.createNestedArray("cleanup_groups");
    JsonObject wifi = groups.createNestedObject();
    wifi["id"] = "unused_wifi";
    wifi["keys"] = obsoleteWifiKeys();
    JsonObject history = groups.createNestedObject();
    history["id"] = "auto_base_history";
    history["keys"] = 0;
    nvs_handle_t handle;
    const char *partition = BackendAgentInternal::backendPreferencesPartition();
    const char *space = strcmp(partition, "nvs") == 0 ? "myPrefs" : "backend";
    if (nvs_open_from_partition(partition, space, NVS_READONLY, &handle) == ESP_OK) {
        size_t count = 0, length = 0;
        for (const char *key : {"PROGRESS_JSON"}) {
            if (nvs_get_str(handle, key, nullptr, &length) == ESP_OK && length > 3) ++count;
        }
        history["keys"] = count;
        nvs_close(handle);
    }
}

bool clearUnusedWifi(String &error) {
    nvs_handle_t handle;
    esp_err_t opened = nvs_open("wifi_config", NVS_READONLY, &handle);
    if (opened == ESP_ERR_NVS_NOT_FOUND) return true;
    if (opened != ESP_OK) { error = "Cannot open obsolete Wi-Fi storage"; return false; }
    nvs_close(handle);
    opened = nvs_open("wifi_config", NVS_READWRITE, &handle);
    if (opened != ESP_OK) { error = "Cannot update obsolete Wi-Fi storage"; return false; }
    esp_err_t erased = ESP_OK;
    for (const char *key : {"profiles", "ap_pass"}) {
        const esp_err_t result = nvs_erase_key(handle, key);
        if (result != ESP_OK && result != ESP_ERR_NVS_NOT_FOUND) erased = result;
    }
    const esp_err_t committed = erased == ESP_OK ? nvs_commit(handle) : erased;
    nvs_close(handle);
    if (committed != ESP_OK) error = "Cannot clear obsolete Wi-Fi storage";
    return committed == ESP_OK;
}


bool saveMigratedWifi(const String &ssid, const String &password) {
    if (!validWifiSsid(ssid) || !validWifiPassword(password)) return false;
    Preferences active;
    if (!active.begin("myPrefs", false)) return false;
    const bool hadSsid = active.isKey("WIFI_SSID"), hadPassword = active.isKey("WIFI_PASS");
    const String oldSsid = active.getString("WIFI_SSID", ""), oldPassword = active.getString("WIFI_PASS", "");
    active.putString("WIFI_SSID", ssid);
    active.putString("WIFI_PASS", password);
    const bool saved = active.isKey("WIFI_SSID") && active.isKey("WIFI_PASS")
        && active.getString("WIFI_SSID", "") == ssid && active.getString("WIFI_PASS", "") == password;
    if (!saved) {
        if (hadSsid) active.putString("WIFI_SSID", oldSsid); else active.remove("WIFI_SSID");
        if (hadPassword) active.putString("WIFI_PASS", oldPassword); else active.remove("WIFI_PASS");
    }
    active.end();
    if (!saved) return false;
    String error;
    return clearUnusedWifi(error);
}

namespace {
bool readableNvsValue(const nvs_entry_info_t &entry) {
    if (strcmp(entry.namespace_name, "myPrefs") && strcmp(entry.namespace_name, "backend")) return false;
    // Raw values use an allowlist. Known configuration JSON is expanded below.
    for (const char *key : {"DEVICE_SERIAL", "DEVICE_NAME", "SENSOR_TYPE", "CONNECTION_TYPE",
                           "GNSS_MDL_TYPE", "WIFI_SSID", "APN", "MQTT_SERVER", "MQTT_PORT",
                           "BACKEND_HOST", "BACKEND_PORT", "NTRIP_SERVER", "NTRIP_PORT",
                           "NTRIP_MPT", "TPC_SUB_CMD", "TPC_HEALTH", "RSTRT_COUNT",
                           "PROVISIONED", "REMOTE_LOCK", "LOCK_SERVERS", "NEED_RESET"}) {
        if (!strcmp(entry.key, key)) return true;
    }
    return false;
}

bool configurationNamespace(const nvs_entry_info_t &entry) {
    return !strcmp(entry.namespace_name, "myPrefs") || !strcmp(entry.namespace_name, "backend");
}

bool configurationJson(const nvs_entry_info_t &entry) {
    if (!configurationNamespace(entry) || entry.type != NVS_TYPE_STR) return false;
    for (const char *key : {"BASE_JSON", "SERVICE_JSON", "PROGRESS_JSON", "CMD_RESULT", "SURVEY_RESULT"})
        if (!strcmp(entry.key, key)) return true;
    return false;
}

bool secretField(String path) {
    path.toLowerCase();
    return path.indexOf("pass") >= 0 || path.indexOf("token") >= 0
        || path.indexOf("secret") >= 0 || path.indexOf("license") >= 0
        || path.indexOf("auth") >= 0 || path.indexOf("api_key") >= 0
        || path.indexOf("apikey") >= 0 || path.indexOf("private_key") >= 0
        || path.indexOf("credential") >= 0;
}

void appendConfigurationFields(JsonArray entries, uint32_t offset, uint32_t &total,
                               const char *partition, const nvs_entry_info_t &entry,
                               JsonVariantConst value, const String &path, bool secret = false) {
    secret = secret || secretField(path);
    if (value.is<JsonObjectConst>() && value.size()) {
        for (JsonPairConst field : value.as<JsonObjectConst>())
            appendConfigurationFields(entries, offset, total, partition, entry, field.value(),
                                      path.isEmpty() ? String(field.key().c_str()) : path + "." + field.key().c_str(), secret);
        return;
    }
    if (value.is<JsonArrayConst>() && value.size()) {
        size_t index = 0;
        for (JsonVariantConst item : value.as<JsonArrayConst>())
            appendConfigurationFields(entries, offset, total, partition, entry, item,
                                      path + "[" + String(index++) + "]", secret);
        return;
    }
    if (total++ < offset || entries.size() >= 6) return;
    JsonObject row = entries.createNestedObject();
    row["partition"] = String(partition);
    row["namespace"] = String(entry.namespace_name);
    row["key"] = String(entry.key);
    row["field"] = path;
    row["type"] = "JSON";
    row["bytes"] = measureJson(value);
    row["redacted"] = secret;
    if (!secret) {
        String text;
        if (value.is<const char *>()) text = value.as<String>();
        else serializeJson(value, text);
        row["value"] = text.substring(0, 96);
        row["truncated"] = text.length() > 96;
    }
}

void describeNvsEntry(JsonObject row, const char *partition, const nvs_entry_info_t &entry) {
    row["partition"] = String(partition);
    row["namespace"] = String(entry.namespace_name);
    row["key"] = String(entry.key);
    row["redacted"] = !readableNvsValue(entry);
    nvs_handle_t handle;
    if (nvs_open_from_partition(partition, entry.namespace_name, NVS_READONLY, &handle) != ESP_OK) {
        row["error"] = "Không đọc được";
        return;
    }
    const bool readable = readableNvsValue(entry);
    esp_err_t result = ESP_OK;
    switch (entry.type) {
#define NVS_NUMBER(kind, type, getter) case kind: { \
        type value{}; result = getter(handle, entry.key, &value); \
        row["type"] = #type; row["bytes"] = sizeof(type); \
        if (readable && result == ESP_OK) { \
            char text[24]; \
            if constexpr (std::is_signed<type>::value) snprintf(text, sizeof(text), "%lld", static_cast<long long>(value)); \
            else snprintf(text, sizeof(text), "%llu", static_cast<unsigned long long>(value)); \
            row["value"] = String(text); \
        } break; }
        NVS_NUMBER(NVS_TYPE_U8, uint8_t, nvs_get_u8)
        NVS_NUMBER(NVS_TYPE_I8, int8_t, nvs_get_i8)
        NVS_NUMBER(NVS_TYPE_U16, uint16_t, nvs_get_u16)
        NVS_NUMBER(NVS_TYPE_I16, int16_t, nvs_get_i16)
        NVS_NUMBER(NVS_TYPE_U32, uint32_t, nvs_get_u32)
        NVS_NUMBER(NVS_TYPE_I32, int32_t, nvs_get_i32)
        NVS_NUMBER(NVS_TYPE_U64, uint64_t, nvs_get_u64)
        NVS_NUMBER(NVS_TYPE_I64, int64_t, nvs_get_i64)
#undef NVS_NUMBER
        case NVS_TYPE_STR:
        case NVS_TYPE_BLOB: {
            size_t length = 0;
            const bool text = entry.type == NVS_TYPE_STR;
            result = text ? nvs_get_str(handle, entry.key, nullptr, &length)
                          : nvs_get_blob(handle, entry.key, nullptr, &length);
            row["type"] = text ? "string" : "blob";
            if (result == ESP_OK) row["bytes"] = text && length ? length - 1 : length;
            if (text && readable && result == ESP_OK) {
                if (length <= 97) {
                    char value[97] = {};
                    result = nvs_get_str(handle, entry.key, value, &length);
                    if (result == ESP_OK) row["value"] = String(value);
                } else row["value"] = "Giá trị dài hơn 96 byte";
            }
            break;
        }
        default: row["type"] = "unknown"; break;
    }
    if (result != ESP_OK) row["error"] = "Dữ liệu đã thay đổi hoặc không đọc được";
    nvs_close(handle);
}
} // namespace

bool readNvsInventory(uint32_t offset, const String &commandId, String &output, String &error) {
    DynamicJsonDocument doc(3072);
    doc["command_id"] = commandId;
    doc["offset"] = offset;
    doc["page_size"] = 6;
    doc["sampled_at_ms"] = millis();
    JsonArray entries = doc.createNestedArray("entries");
    uint32_t total = 0;
    // Show saved Wi-Fi first, then application configuration, then SDK internals.
    for (int priority = 0; priority < 3; ++priority) {
        for (const char *partition : {"nvs", "agent_state"}) {
            nvs_stats_t stats{};
            const esp_err_t status = nvs_get_stats(partition, &stats);
            if (status != ESP_OK) {
                if (!strcmp(partition, "nvs")) { error = "Cannot inspect NVS"; return false; }
                JsonArray unavailable = doc["unavailable_partitions"].isNull()
                    ? doc.createNestedArray("unavailable_partitions") : doc["unavailable_partitions"].as<JsonArray>();
                if (priority == 0) unavailable.add(partition);
                continue;
            }
            for (auto iterator = nvs_entry_find(partition, nullptr, NVS_TYPE_ANY); iterator;
                 iterator = nvs_entry_next(iterator)) {
                nvs_entry_info_t entry;
                nvs_entry_info(iterator, &entry);
                const bool wifi = configurationNamespace(entry) && !strncmp(entry.key, "WIFI_", 5);
                const int entryPriority = wifi ? 0 : configurationNamespace(entry) ? 1 : 2;
                if (entryPriority != priority) continue;
                if (configurationJson(entry)) {
                    nvs_handle_t handle;
                    if (nvs_open_from_partition(partition, entry.namespace_name, NVS_READONLY, &handle) == ESP_OK) {
                        size_t length = 0;
                        if (nvs_get_str(handle, entry.key, nullptr, &length) == ESP_OK && length <= 8192) {
                            std::unique_ptr<char[]> text(new char[length]);
                            DynamicJsonDocument config(12288);
                            if (nvs_get_str(handle, entry.key, text.get(), &length) == ESP_OK
                                && deserializeJson(config, text.get()) == DeserializationError::Ok) {
                                appendConfigurationFields(entries, offset, total, partition, entry,
                                                          config.as<JsonVariantConst>(), String());
                                nvs_close(handle);
                                continue;
                            }
                        }
                        nvs_close(handle);
                    }
                }
                if (total >= offset && entries.size() < 6)
                    describeNvsEntry(entries.createNestedObject(), partition, entry);
                ++total;
            }
        }
    }
    doc["fields_expanded"] = true;
    doc["total"] = total;
    doc["has_more"] = offset + entries.size() < total;
    if (doc.overflowed()) { error = "NVS inventory page exceeds memory limit"; return false; }
    output.clear();
    serializeJson(doc, output);
    return true;
}
