#include "functions/backend/Backend_Agent.h"
#include "functions/backend/Backend_Agent_Internal.h"
#include "Prog_Config.h"
#include "functions/ntrip/NTRIP_Handler_IP.h"
#include "functions/ntrip/RTCM_Receiver.h"
#include "functions/backend/Storage_Status.h"
#include <cmath>
#include <cstring>

#include "functions/mqtt/MQTT_Manager.h"
#include "functions/gnss/Unicore_Output.h"
#include "functions/gnss/Unicore_Readback.h"

using namespace BackendAgentInternal;

extern SemaphoreHandle_t rtcmBufferMutex;

namespace {

String normalizedStreamValue(String value, bool stripLeadingSlash) {
    value.trim();
    if (stripLeadingSlash) {
        while (value.startsWith("/")) value.remove(0, 1);
    }
    value.toLowerCase();
    return value;
}

int streamServerId(JsonObjectConst payload) {
    int serverId = payload["server_id"] | 0;
    if (serverId != 1 && serverId != 2) serverId = payload["server_idx"] | 0;
    if (serverId != 1 && serverId != 2) serverId = payload["server"] | 0;
    return serverId;
}

void setStreamServerState(JsonObject service, uint8_t id, bool active,
                          const String &mountpoint) {
    const String prefix = String("server") + String(id);
    const bool onDemand = jsonBool(
        service, prefix + "_stream_on_demand",
        jsonBool(service, "stream_on_demand", false));
    if (!active && !onDemand) return;
    // Dynamic keys must be copied into the JSON pool, not linked to a temporary.
    service[prefix + "_stream_active"] = active;
    if (active && mountpoint.length() > 0) {
        service["active_mountpoint"] = mountpoint;
        return;
    }
    if (!active) {
        const String configured = jsonString(service, String("mountpoint") + String(id));
        const String current = jsonString(service, "active_mountpoint");
        if (mountpoint.isEmpty() || mountpoint.equalsIgnoreCase(configured)
            || current.equalsIgnoreCase(configured)) {
            service.remove("active_mountpoint");
        }
    }
}

bool serverMatchesAddress(JsonObjectConst service, uint8_t id, const String &address) {
    const String prefix = String("server") + String(id);
    String configured = jsonString(service, prefix + "_host",
                                   jsonString(service, String("serverhost") + String(id)));
    configured = normalizedStreamValue(configured, false);
    return !configured.isEmpty()
        && (address.indexOf(configured) >= 0 || configured.indexOf(address) >= 0);
}

bool serverMatchesMountpoint(JsonObjectConst service, uint8_t id,
                             const String &mountpoint) {
    String configured = jsonString(service, String("mountpoint") + String(id));
    while (configured.startsWith("/")) configured.remove(0, 1);
    configured.toLowerCase();
    return !configured.isEmpty() && configured == mountpoint;
}

bool applyTargetedStreamState(JsonObject service, int serverId, bool active,
                              const String &address, const String &mountpoint) {
    if (serverId == 1 || serverId == 2) {
        setStreamServerState(service, static_cast<uint8_t>(serverId), active, mountpoint);
        return true;
    }
    if (address.length() > 0) {
        bool targeted = false;
        for (uint8_t id = 1; id <= 2; ++id) {
            if (!serverMatchesAddress(service, id, address)) continue;
            setStreamServerState(service, id, active, mountpoint);
            targeted = true;
        }
        return targeted;
    }
    if (mountpoint.length() > 0) {
        bool targeted = false;
        for (uint8_t id = 1; id <= 2; ++id) {
            if (!serverMatchesMountpoint(service, id, mountpoint)) continue;
            setStreamServerState(service, id, active, mountpoint);
            targeted = true;
        }
        return targeted;
    }
    if (active) return false;
    for (uint8_t id = 1; id <= 2; ++id)
        setStreamServerState(service, id, active, mountpoint);
    return true;
}

void applyGlobalStreamState(JsonObject service, bool active, const String &mountpoint) {
    service["stream_active"] = active;
    if (mountpoint.length() > 0 && active) service["active_mountpoint"] = mountpoint;
    if (!active) service.remove("active_mountpoint");
}

}

void BackendAgent::recordCommandResult(const String &command, const String &source,
                                       const String &status, const String &detail,
                                       const String &commandId) {
    DynamicJsonDocument doc(1024);
    doc["command"] = command;
    doc["source"] = source;
    doc["status"] = status;
    doc["detail"] = detail.substring(0, 300);
    doc["command_id"] = commandId;
    doc["timestamp"] = epochString().toInt();
    lastCommandResult_.clear();
    serializeJson(doc, lastCommandResult_);
    const bool readOnly = command == "VERIFY_GNSS_CONFIG";
    const bool saved = readOnly || saveStatePreferences();
    Serial.printf("[BACKEND][CMD] %s id=%s source=%s status=%s; NVS=%s\n",
                  command.c_str(), commandId.c_str(), source.c_str(), status.c_str(),
                  readOnly ? "SKIPPED (read-only)" : saved ? "OK" : "LOI");
}

void BackendAgent::publishConfigState(const char *kind) {
    if (!mqttConnected()) return;
    DynamicJsonDocument doc(CONFIG_DOCUMENT_SIZE);
    doc["serial"] = serialNumber_;
    doc["timestamp"] = epochString().toInt();
    doc["type"] = kind;
    if (strcmp(kind, "base_config_state") == 0) {
        copyJsonObject(doc, "config", baseConfig_);
    } else {
        copyJsonObject(doc, "config", serviceConfig_);
    }
    String output;
    serializeJson(doc, output);
    const String topic = String("pi/devices/") + serialNumber_ + "/" + kind;
    mqtt.publish(topic.c_str(), output.c_str(), true);
}

void BackendAgent::applyServiceStreamCommand(JsonObject payload) {
    DynamicJsonDocument serviceDoc(CONFIG_DOCUMENT_SIZE);
    if (deserializeJson(serviceDoc, serviceConfig_) != DeserializationError::Ok
        || !serviceDoc.is<JsonObject>()) {
        serviceDoc.to<JsonObject>();
    }
    JsonObject service = serviceDoc.as<JsonObject>();
    const bool active = payload["active"] | false;
    String mountpoint = normalizedStreamValue(payload["mountpoint"] | String(), true);
    String address = payload["address"] | String();
    if (address.isEmpty()) address = payload["caster_host"] | String();
    if (address.isEmpty()) address = payload["ip"] | String();
    if (address.isEmpty()) address = payload["host"] | String();
    address = normalizedStreamValue(address, false);
    const int serverId = streamServerId(payload);

    if (!applyTargetedStreamState(service, serverId, active, address, mountpoint))
        applyGlobalStreamState(service, active, mountpoint);
    service["stream_active"] = BackendAgent::effectiveStreamActive(service, 1, false)
        || BackendAgent::effectiveStreamActive(service, 2, false);
    serviceConfig_.clear();
    serializeJson(serviceDoc, serviceConfig_);
    saveStatePreferences();
}

bool BackendAgent::executeRawCommands(JsonArray commands, String &error, const String &sensorType) {
    if (commands.isNull() || commands.size() == 0) {
        error = "missing payload.commands_b64";
        return false;
    }
    if (commands.size() > 200) {
        error = "too many raw commands";
        return false;
    }
    uint8_t decoded[3072] = {};
    for (JsonVariant item : commands) {
        const String encoded = item.as<String>();
        if (encoded.isEmpty() || encoded.length() > 4096) {
            error = "invalid raw command item";
            return false;
        }
        size_t length = decodeBase64(encoded, decoded, sizeof(decoded));
        if (length == 0) {
            error = "raw command is not valid base64";
            return false;
        }
        uint32_t delayMs = 0;
        if (delayMarker(decoded, length, delayMs)) {
            delay(delayMs);
            continue;
        }
        if (sensorType == "Unicorecomm") length = routeUnicoreOutput(decoded, length, GNSS_UNICORE_PORT);
        else if (sensorType == "Ublox") GnssCmdBuilder::routeUbloxOutput(decoded, length);
        const bool unicore = sensorType == "Unicorecomm" || (sensorType.isEmpty() && sensorType_ == "Unicorecomm");
        if (unicore) {
            if (!writeUnicoreCommand(decoded, length, error)) return false;
            continue;
        }
        if (rtcmBufferMutex && xSemaphoreTake(rtcmBufferMutex, pdMS_TO_TICKS(MUTEX_TIMEOUT_MS)) == pdTRUE) {
            Serial1.write(decoded, length);
            Serial1.flush();
            xSemaphoreGive(rtcmBufferMutex);
        } else {
            error = "GNSS serial is busy";
            return false;
        }
        delay(50);
    }
    return true;
}

bool BackendAgent::executeLicenseCommand(JsonObject payload, String &error, String &detail, bool &restartAfterCommand) {
    bool success = true;
    const String license = payload["license_key"] | String();
    if (license.isEmpty()) {
        Serial.println("[BACKEND][LICENSE] Lenh DEPLOY_LICENSE khong co license_key.");
        success = false;
        error = "missing payload.license_key";
    } else if (!licenseMatchesSerial(serialNumber_, license)) {
        success = false;
        error = "invalid device token or legacy license";
    } else {
        Serial.println("[BACKEND][LICENSE] Da nhan license_key (khong in noi dung key).");
        const String previousToken = licenseToken_;
        const bool previousValid = licenseValid_;
        licenseToken_ = license;
        licenseValid_ = true;
        const bool saved = saveStatePreferences();
        Serial.printf("[BACKEND][LICENSE] Kiem tra: %s; luu NVS: %s.\n",
                      licenseValid_ ? "HOP LE" : "KHONG HOP LE",
                      saved ? "THANH CONG" : "THAT BAI");
        if (!saved) {
            licenseToken_ = previousToken;
            licenseValid_ = previousValid;
            success = false;
            error = "cannot persist device token";
        } else {
            detail = "license deployed; rebooting";
            restartAfterCommand = true;
            setAgentState("rebooting");
            refreshWebsocket();
        }
    }
    return success;
}

bool BackendAgent::executeServiceConfigCommand(JsonObject payload, String &error, String &detail) {
    bool success = true;
    if (payload.isNull() || payload.size() == 0) {
        success = false;
        error = "missing service config payload";
    } else {
        DynamicJsonDocument serviceDoc(CONFIG_DOCUMENT_SIZE);
        if (deserializeJson(serviceDoc, serviceConfig_) != DeserializationError::Ok
            || !serviceDoc.is<JsonObject>()) {
            serviceDoc.clear();
            serviceDoc.to<JsonObject>();
        }
        JsonObject service = serviceDoc.as<JsonObject>();
        for (JsonPair entry : payload) {
            service[entry.key()] = entry.value();
        }
        const JsonArrayConst removedServers = payload["removed_servers"].as<JsonArrayConst>();
        for (JsonVariantConst removed : removedServers) {
            if (!removed.is<int>()) continue;
            const int serverId = removed.as<int>();
            if (serverId <= 2) continue;
            const String suffix = String(serverId);
            service.remove((String("server") + suffix + "_enabled").c_str());
            service.remove((String("server") + suffix + "_stream_on_demand").c_str());
            service.remove((String("server") + suffix + "_stream_active").c_str());
            service.remove((String("serverhost") + suffix).c_str());
            service.remove((String("port") + suffix).c_str());
            service.remove((String("mountpoint") + suffix).c_str());
            service.remove((String("username") + suffix).c_str());
            service.remove((String("password") + suffix).c_str());
            service.remove((String("ntrip_version") + suffix).c_str());
        }
        service.remove("removed_servers");
        const bool onDemand = jsonBool(service, "stream_on_demand", false);
        if (!onDemand) service["stream_active"] = true;
        else if (service["stream_active"].isNull()) service["stream_active"] = false;
        const bool globalActive = jsonBool(service, "stream_active", false);
        for (uint8_t id = 1; id <= 2; ++id) {
            const String prefix = String("server") + String(id);
            const String onDemandKey = prefix + "_stream_on_demand";
            const String activeKey = prefix + "_stream_active";
            const bool serverOnDemand = jsonBool(service, onDemandKey, onDemand);
            service[onDemandKey] = serverOnDemand;
            if (!serverOnDemand) service[activeKey] = true;
            else if (service[activeKey.c_str()].isNull()) {
                service[activeKey] = globalActive;
            }
        }
        serviceConfig_.clear();
        serializeJson(serviceDoc, serviceConfig_);
        detail = "service config deployed";
        setupNTRIP();
        connectNTRIP();
        publishConfigState("service_config_state");
    }
    return success;
}

bool BackendAgent::executeRawCommand(JsonDocument &doc, JsonObject payload, String &error, String &detail) {
    bool success = true;
    JsonArray commands = payload["commands_b64"].as<JsonArray>();
    const JsonObject originalConfig = doc["original_config"].as<JsonObject>();
    const bool configuringBase = String(originalConfig["mode"] | "") == "BASE";
    const String sensorType = originalConfig["sensor_type"] | sensorType_;
    if (workflowActive()) {
        requestWorkflowStop();
        const uint32_t stopWaitMs = millis();
        while (workflowActive() && static_cast<uint32_t>(millis() - stopWaitMs) < 1500UL) {
            vTaskDelay(pdMS_TO_TICKS(50));
        }
    }
    if (workflowActive()) {
        success = false;
        error = "cannot stop active base workflow";
    } else if (configuringBase && sensorType != "Ublox" && sensorType != "Unicorecomm") {
        success = false;
        error = "unsupported GNSS sensor_type";
    } else {
        success = executeRawCommands(commands, error, configuringBase ? sensorType : String());
    }
    detail = success ? "raw commands executed" : error;
    if (success) {
        if (configuringBase) {
            sensorType_ = sensorType;
            baseStartupState_ = "configured";
            baseStartupError_ = "";
            baseStartupAttempted_ = true;
            autoBaseProgress_.clear();
            lastReceiverPollMs_ = 0;
            setAgentState(normalAgentState());
        }
        if (!originalConfig.isNull() && originalConfig.containsKey("params")) {
            DynamicJsonDocument baseDoc(CONFIG_DOCUMENT_SIZE);
            baseDoc.set(originalConfig["params"]);
            JsonObject base = baseDoc.as<JsonObject>();
            if (originalConfig.containsKey("mode")) base["mode"] = originalConfig["mode"];
            baseConfig_.clear();
            serializeJson(baseDoc, baseConfig_);
            publishConfigState("base_config_state");
        }
    }
    return success;
}

bool BackendAgent::executeAutoBaseCommand(JsonObject payload, String &error, String &detail) {
    bool success = true;
    const String sensorType = payload["sensor_type"] | sensorType_;
    const int requestedPort = payload["port"] | 0;
    const bool hasConnection = !String(payload["ip"] | String()).isEmpty()
        && !String(payload["user"] | String()).isEmpty()
        && !String(payload["password"] | String()).isEmpty()
        && !String(payload["mountpoint"] | String()).isEmpty()
        && requestedPort >= 1 && requestedPort <= 65535;
    if (workflowActive()) {
        success = false;
        error = "another base workflow is already running";
    } else if (sensorType != "Ublox" && sensorType != "Unicorecomm") {
        success = false;
        error = "select Ublox or Unicorecomm in CORS before starting auto base";
    } else if (!hasConnection) {
        success = false;
        error = "missing or invalid CORS connection fields";
    } else {
        sensorType_ = sensorType;
        String workflowPayload;
        serializeJson(payload, workflowPayload);
        if (!startWorkflow("auto_base", workflowPayload)) {
            success = false;
            error = "cannot start auto base workflow";
        } else {
            DynamicJsonDocument progress(CONFIG_DOCUMENT_SIZE);
            progress["ntrip_host"] = payload["ip"];
            progress["ntrip_port"] = payload["port"];
            progress["mountpoint"] = payload["mountpoint"];
            progress["note"] = "Collect RTK Fixed LLH; VNGEONET datum parameters are decoded per session and results wait for review.";
            String progressJson;
            serializeJson(progress, progressJson);
            setAgentState("auto_setup_queued");
            setWorkflowProgress("queued", 0, 4, progressJson);
            detail = "auto base workflow queued";
        }
    }
    return success;
}

bool BackendAgent::executeReferenceCheckCommand(JsonObject payload, String &error, String &detail) {
    bool success = true;
    const JsonObject reference = payload["reference_coords"].as<JsonObject>();
    const int requestedPort = payload["port"] | 0;
    const bool validReference = !reference.isNull()
        && !reference["lat"].isNull() && !reference["lon"].isNull()
        && !reference["alt"].isNull();
    const bool hasConnection = !String(payload["ip"] | String()).isEmpty()
        && !String(payload["user"] | String()).isEmpty()
        && !String(payload["password"] | String()).isEmpty()
        && !String(payload["mountpoint"] | String()).isEmpty()
        && requestedPort >= 1 && requestedPort <= 65535;
    if (workflowActive()) {
        success = false;
        error = "another base workflow is already running";
    } else if (!validReference || !hasConnection) {
        success = false;
        error = "missing or invalid reference/CORS configuration";
    } else {
        String workflowPayload;
        serializeJson(payload, workflowPayload);
        if (!startWorkflow("reference_check", workflowPayload)) {
            success = false;
            error = "cannot start reference check workflow";
        } else {
            setAgentState("reference_check_queued");
            setWorkflowProgress("reference_check_queued", 0, 4);
            detail = "base reference check queued";
        }
    }
    return success;
}

void BackendAgent::handleCommand(const String &source, const String &message) {
    Serial.printf("[BACKEND][RX] Nhan goi lenh qua %s (%u bytes).\n",
                  source.c_str(), static_cast<unsigned>(message.length()));
    DynamicJsonDocument doc(COMMAND_DOCUMENT_SIZE);
    if (deserializeJson(doc, message) != DeserializationError::Ok || !doc.is<JsonObject>()) {
        recordCommandResult("UNKNOWN", source, "rejected", "command envelope must be an object", "");
        publishStatus(true);
        return;
    }

    const String command = doc["command"] | String();
    const JsonObject payload = doc["payload"].as<JsonObject>();
    String commandId = doc["command_id"] | String();
    if (commandId.isEmpty() && !payload.isNull()) commandId = payload["command_id"] | String();
    if (commandId.isEmpty()) commandId = String("esp32-") + String(millis());
    Serial.printf("[BACKEND][CMD] Nhan command=%s id=%s qua %s.\n",
                  command.c_str(), commandId.c_str(), source.c_str());
    if (command.isEmpty()) {
        recordCommandResult("UNKNOWN", source, "rejected", "missing command", commandId);
        publishStatus(true);
        return;
    }

    const bool allowed = command == "LOCK_DEVICE" || command == "UNLOCK_DEVICE"
        || command == "PROVISION_DEVICE" || command == "DEPLOY_LICENSE"
        || command == "TRIGGER_AUTO_BASE" || command == "TRIGGER_BASE_REFERENCE_CHECK"
        || command == "STOP_AUTO_BASE" || command == "APPLY_VN2000_PROVINCE"
        || command == "EXECUTE_RAW_COMMANDS" || command == "DEPLOY_SERVICE_CONFIG"
        || command == "SET_RTCM_STREAM_ACTIVE" || command == "DELETE_DEVICE"
        || command == "CHECK_BASE_STATUS" || command == "REBOOT_DEVICE"
        || command == "CHECK_STORAGE_STATUS" || command == "CLEAR_NVS_DATA"
        || command == "VERIFY_GNSS_CONFIG";
    if (!allowed) {
        recordCommandResult(command, source, "rejected", "unsupported command", commandId);
        publishStatus(true);
        return;
    }
    if (stationLock_.all && command != "LOCK_DEVICE" && command != "UNLOCK_DEVICE") {
        recordCommandResult(command, source, "rejected", "device is locked", commandId);
        publishStatus(true);
        return;
    }
    if (!licenseValid_ && command != "LOCK_DEVICE" && command != "UNLOCK_DEVICE"
        && command != "PROVISION_DEVICE" && command != "DEPLOY_LICENSE") {
        recordCommandResult(command, source, "rejected", "license is missing or invalid", commandId);
        publishStatus(true);
        return;
    }

    recordCommandResult(command, source, "running", "", commandId);
    setAgentState("configuring");
    String error;
    bool success = true;
    String detail;
    bool restartAfterCommand = false;

    if (command == "LOCK_DEVICE") {
        if (payload.containsKey("locked_servers")) {
            JsonArrayConst ids = payload["locked_servers"].as<JsonArrayConst>();
            int serverIds[2] = {};
            size_t count = 0;
            if (ids.isNull()) {
                success = false;
            } else {
                for (JsonVariantConst id : ids) {
                    if (!id.is<int>() || id.as<int>() < 1 || id.as<int>() > 2) {
                        success = false;
                        break;
                    }
                    const int serverId = id.as<int>();
                    if (count == 0 || serverIds[0] != serverId) {
                        if (count < 2) serverIds[count++] = serverId;
                    }
                }
            }
            if (success) success = stationLock_.setScoped(serverIds, count);
            if (!success) error = "payload.locked_servers must contain only server IDs 1 or 2";
        } else {
            requestWorkflowStop();
            stationLock_.all = true;
            stationLock_.servers = 0;
        }
        if (success) {
            setAgentState(normalAgentState());
            // loopNTRIP applies the policy per endpoint. Rebuilding all sockets
            // here would interrupt the other host during a scoped lock.
            detail = "device lock updated";
        }
    } else if (command == "UNLOCK_DEVICE") {
        stationLock_.restore(false, 0);
        if (baseStartupState_ == "locked") baseStartupAttempted_ = false;
        setAgentState(normalAgentState());
        detail = "device unlocked";
    } else if (command == "PROVISION_DEVICE") {
        const String name = payload["name"] | String();
        if (name.isEmpty()) {
            success = false;
            error = "missing payload.name";
        } else {
            deviceName_ = name;
            provisioned_ = true;
            setupNTRIP();
            connectNTRIP();
            detail = "device provisioned";
        }
    } else if (command == "DEPLOY_LICENSE") {
        success = executeLicenseCommand(payload, error, detail, restartAfterCommand);
    } else if (command == "DEPLOY_SERVICE_CONFIG") {
        success = executeServiceConfigCommand(payload, error, detail);
    } else if (command == "SET_RTCM_STREAM_ACTIVE") {
        if (!payload.containsKey("active")) {
            success = false;
            error = "missing payload.active";
        } else {
            applyServiceStreamCommand(payload);
            setupNTRIP();
            connectNTRIP();
            detail = (payload["active"] | false) ? "stream activated" : "stream set to standby";
        }
    } else if (command == "EXECUTE_RAW_COMMANDS") {
        success = executeRawCommand(doc, payload, error, detail);
    } else if (command == "VERIFY_GNSS_CONFIG") {
        if (workflowActive() || (sensorType_ != "Ublox" && sensorType_ != "Unicorecomm")) {
            success = false;
            error = "Verification requires an idle supported GNSS receiver";
        } else {
            success = sensorType_ == "Ublox" ? verifyGnssConfig(payload, commandId, error)
                                             : verifyUnicoreConfig(payload, commandId, error);
            if (success) detail = "GNSS readback completed; inspect verification result";
        }
    } else if (command == "CHECK_BASE_STATUS") {
        if (sensorType_ == "Unicorecomm" || sensorType_ == "Ublox") {
            success = refreshReceiverReadback(error);
            if (success) detail = "receiver mode and position read back";
        } else {
            success = false;
            error = "GNSS serial is busy";
        }
    } else if (command == "TRIGGER_AUTO_BASE") {
        success = executeAutoBaseCommand(payload, error, detail);
    } else if (command == "TRIGGER_BASE_REFERENCE_CHECK") {
        success = executeReferenceCheckCommand(payload, error, detail);
    } else if (command == "STOP_AUTO_BASE") {
        if (workflowActive()) {
            requestWorkflowStop();
            setWorkflowProgress("stopping", 0, 4);
            detail = "base workflow stop requested";
        } else {
            setWorkflowProgress("stopped", 0, 4);
                setAgentState(normalAgentState());
            detail = "auto base stopped";
        }
    } else if (command == "APPLY_VN2000_PROVINCE") {
        success = false;
        error = "Review Auto Base results and apply Fixed LLA; province overrides no longer write the receiver";
    } else if (command == "CHECK_STORAGE_STATUS") {
        if (payload["inspect"] == true) {
            if (!payload["offset"].is<uint32_t>() || payload["offset"].as<uint32_t>() > 8192) {
                success = false;
                error = "NVS offset must be an integer from 0 to 8192";
            } else {
                nvsInventory_ = static_cast<const char *>(nullptr);
                success = readNvsInventory(payload["offset"].as<uint32_t>(), commandId, nvsInventory_, error);
                nvsInventoryMs_ = millis();
            }
        }
        detail = "storage status refreshed";
    } else if (command == "CLEAR_NVS_DATA") {
        nvsInventory_ = static_cast<const char *>(nullptr);
        const String group = payload["group"] | "";
        const String confirmation = payload["confirm"] | "";
        if (workflowActive() || (surveyInMonitoring_ && !surveyInReadbackReady_)) {
            success = false;
            error = "Cannot clean storage during an active GNSS workflow or survey";
        } else if (confirmation != group || (group != "unused_wifi" && group != "auto_base_history")) {
            success = false;
            error = "Select and confirm a supported cleanup group";
        } else if (group == "unused_wifi") {
            success = clearUnusedWifi(error);
            detail = "obsolete Wi-Fi portal data cleared; active network preserved";
        } else {
            success = beginBackendPreferences(false);
            if (success) {
                Preferences &store = backendPreferences();
                success = !store.isKey("PROGRESS_JSON") || store.remove("PROGRESS_JSON");
                store.end();
            }
            if (success) {
                // Null assignment releases the old JSON buffer in Arduino String.
                autoBaseProgress_ = static_cast<const char *>(nullptr);
                autoBaseProgress_ = "{}";
            }
            else error = "Cannot clear Auto Base history";
            detail = "saved Auto Base history cleared; base configuration and Survey-In result preserved";
        }
    } else if (command == "REBOOT_DEVICE") {
        requestWorkflowStop();
        setAgentState("rebooting");
        recordCommandResult(command, source, "success", "device reboot requested", commandId);
        saveStatePreferences();
        publishStatus(true);
        delay(500);
        mqtt.disconnect();
        ESP.restart();
    } else if (command == "DELETE_DEVICE") {
        requestWorkflowStop();
        setAgentState("rebooting_for_reset");
        recordCommandResult(command, source, "success", "device reset requested", commandId);
        saveStatePreferences();
        publishStatus(true);
        delay(500);
        prefs.begin("myPrefs", false);
        prefs.clear();
        prefs.end();
        if (beginBackendPreferences(false)) {
            backendPreferences().clear();
            backendPreferences().end();
        }
        mqtt.disconnect();
        ESP.restart();
    }

    finishCommand(source, command, commandId, success, error, detail, restartAfterCommand);
}

void BackendAgent::finishCommand(const String &source, const String &command, const String &commandId, bool success, const String &error, const String &detail, bool restartAfterCommand) {
    if (success) {
        const bool workflowState = command == "TRIGGER_AUTO_BASE"
            || command == "TRIGGER_BASE_REFERENCE_CHECK"
            || command == "STOP_AUTO_BASE" && workflowActive();
        if (command != "REBOOT_DEVICE" && command != "DELETE_DEVICE"
            && command != "DEPLOY_LICENSE" && !workflowState) {
            setAgentState(normalAgentState());
        }
        recordCommandResult(command, source, "success", detail, commandId);
    } else {
        setAgentState(normalAgentState());
        recordCommandResult(command, source, "error", error, commandId);
    }
    if (command != "VERIFY_GNSS_CONFIG") saveStatePreferences();
    publishStatus(true);
    if (success && restartAfterCommand) {
        delay(500);
        mqtt.disconnect();
        ESP.restart();
    }
}
