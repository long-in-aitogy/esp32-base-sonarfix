"""Exercise the complete backend state migration/save code with in-memory NVS."""
from pathlib import Path
import re
import tempfile
from host_coverage import compile_cpp, run_cpp, mapped

root = Path(__file__).resolve().parents[2]
source_path = root / 'src/functions/backend/Backend_Agent_Storage.cpp'
source = re.sub(r'^#include.*$', '', source_path.read_text(), flags=re.M)
shim = (root / 'test/host/Arduino.h').read_text().replace('#pragma once', '')
shim = shim.replace('    bool isEmpty()', '''    bool startsWith(const char *text) const { return find(text) == 0; }
    void remove(size_t start, size_t count) { erase(start, count); }
    bool isEmpty()''')
harness = r'''
#include <ArduinoJson.h>
#include "functions/backend/Station_Lock.h"
#include <cassert>
#include <map>
#include <string>
using Store = std::map<std::string, String>;
std::map<std::string, Store> stores;
std::string failOpen, failWrite;
bool failCommit = false;
unsigned commits = 0, nativeOpens = 0, nativeCloses = 0;
struct Preferences {
    std::string space;
    bool begin(const char *name, bool, const char *partition = "nvs") {
        space = std::string(partition) + "/" + name;
        return space != failOpen;
    }
    void end() {}
    bool isKey(const char *key) { return stores[space].count(key); }
    String getString(const char *key, const String &fallback = String()) {
        return isKey(key) ? stores[space][key] : fallback;
    }
    size_t putString(const char *key, const String &value) {
        if (key == failWrite) return 0;
        stores[space][key] = value; return value.size();
    }
    bool getBool(const char *key, bool fallback = false) { return isKey(key) ? stores[space][key] == "1" : fallback; }
    size_t putBool(const char *key, bool value) { return putString(key, value ? "1" : "0"); }
    uint8_t getUChar(const char *key, uint8_t fallback = 0) { return isKey(key) ? std::stoi(stores[space][key]) : fallback; }
    size_t putUChar(const char *key, uint8_t value) { return putString(key, String(unsigned(value))) ? 1 : 0; }
    int getInt(const char *key, int fallback = 0) { return isKey(key) ? std::stoi(stores[space][key]) : fallback; }
    uint16_t getUShort(const char *key, uint16_t fallback) { return isKey(key) ? std::stoi(stores[space][key]) : fallback; }
} prefs;
using esp_err_t = int;
using nvs_handle_t = unsigned;
constexpr int ESP_OK = 0, NVS_READWRITE = 1, CONFIG_DOCUMENT_SIZE = 4096;
constexpr const char *NTRIP_CASTER_ADDRESS = "caster.example", *NTRIP_MOUNTPOINT = "/BASE", *NTRIP_AUTH_BASE_STATION = "test";
constexpr unsigned NTRIP_CASTER_PORT = 2101;
std::map<nvs_handle_t, std::pair<std::string, Store>> handles;
esp_err_t nvs_open_from_partition(const char *partition, const char *name, int, nvs_handle_t *handle) {
    std::string space = std::string(partition) + "/" + name;
    if (space == failOpen) return -1;
    *handle = ++nativeOpens; handles[*handle] = {space, stores[space]}; return ESP_OK;
}
esp_err_t nvs_open(const char *name, int mode, nvs_handle_t *handle) { return nvs_open_from_partition("nvs", name, mode, handle); }
const char *esp_err_to_name(esp_err_t) { return "injected failure"; }
esp_err_t nvs_set_str(nvs_handle_t handle, const char *key, const char *value) {
    if (key == failWrite) return -1;
    handles[handle].second[key] = value; return ESP_OK;
}
esp_err_t nvs_set_u8(nvs_handle_t handle, const char *key, uint8_t value) {
    return nvs_set_str(handle, key, String(unsigned(value)).c_str());
}
esp_err_t nvs_commit(nvs_handle_t handle) {
    if (failCommit) return -1;
    ++commits; stores[handles[handle].first] = handles[handle].second; return ESP_OK;
}
void nvs_close(nvs_handle_t handle) { ++nativeCloses; handles.erase(handle); }
namespace BackendAgentInternal {
bool licenseMatchesSerial(const String &, const String &token) { return token == "test-license"; }
}
struct BackendAgent {
    String serialNumber_, deviceName_, sensorType_, baseConfig_, serviceConfig_, licenseToken_, lastCommandResult_,
           autoBaseProgress_, surveyInResult_, statusBootId_, agentState_;
    bool provisioned_ = false, licenseValid_ = false;
    StationLock stationLock_;
    void loadPreferences(); void ensureDefaultServiceConfig(); bool saveStatePreferences();
    String normalAgentState() const { return stationLock_.all ? "locked" : licenseValid_ ? "online" : "awaiting_license"; }
};
'''
checks = r'''
int main() {
    using namespace BackendAgentInternal;
    stores["nvs/myPrefs"] = {{"DEVICE_SERIAL","LP_123"},{"DEVICE_NAME","station"},{"SENSOR_TYPE","Ublox"},
        {"PROVISIONED","1"},{"REMOTE_LOCK","1"},{"LOCK_SERVERS","2"},{"BASE_JSON","{\"coords\":{}}"},
        {"SERVICE_JSON","{}"},{"LICENSE_KEY","test-license"},{"CMD_RESULT","{}"},{"PROGRESS_JSON","{}"},{"RSTRT_COUNT","7"}};
    BackendAgent agent; agent.loadPreferences();
    assert(agent.serialNumber_ == "esp_123" && agent.deviceName_ == "station");
    assert(agent.provisioned_ && agent.licenseValid_ && agent.stationLock_.all && agent.stationLock_.servers == 2);
    assert(agent.statusBootId_ == "esp_123-00000007" && agent.agentState_ == "locked");
    assert(std::string(backendPreferencesPartition()) == "agent_state");
    assert(stores["agent_state/backend"]["MIGRATED"] == "1");
    stores["nvs/myPrefs"]["DEVICE_NAME"] = "must-not-overwrite";
    BackendAgent reloaded; reloaded.loadPreferences(); assert(reloaded.deviceName_ == "station");
    reloaded.surveyInResult_ = "{\"duration\":120}";
    assert(reloaded.saveStatePreferences() && commits == 1 && nativeOpens == nativeCloses);
    assert(stores["agent_state/backend"]["SURVEY_RESULT"] == reloaded.surveyInResult_);
    for (const auto *key : {"DEVICE_SERIAL", "SERVICE_JSON", "PROVISIONED"}) {
        failWrite = key; assert(!reloaded.saveStatePreferences()); assert(nativeOpens == nativeCloses);
    }
    failWrite.clear(); failCommit = true; assert(!reloaded.saveStatePreferences());
    assert(nativeOpens == nativeCloses); failCommit = false;
    failOpen = "agent_state/backend"; assert(!reloaded.saveStatePreferences());
    assert(nativeOpens == nativeCloses);
    BackendAgent fallback; fallback.loadPreferences();
    assert(std::string(backendPreferencesPartition()) == "nvs" && fallback.serialNumber_ == "esp_123");
    assert(fallback.saveStatePreferences());
    assert(readPreference("DEVICE_NAME", "fallback") == "must-not-overwrite");
    assert(readPreference("missing", "fallback") == "fallback");
    failOpen.clear(); stores.clear();
    BackendAgent generated; generated.loadPreferences();
    assert(generated.serialNumber_ == "esp_000000000000" && !generated.licenseValid_);
    assert(generated.surveyInResult_ == "{}");
    BackendAgent empty; assert(!empty.saveStatePreferences());
    generated.serviceConfig_ = "bad json";
    stores["nvs/myPrefs"]["NTRIP_MPT"] = "///MOUNT";
    generated.ensureDefaultServiceConfig();
    DynamicJsonDocument config(4096); assert(deserializeJson(config, generated.serviceConfig_) == DeserializationError::Ok);
    assert(config["mountpoint1"] == "MOUNT" && config["server1_enabled"] == true && config["server2_enabled"] == false);
    generated.serviceConfig_ = "{\"custom\":true}"; generated.ensureDefaultServiceConfig();
    assert(generated.serviceConfig_ == "{\"custom\":true}");
    assert(nativeOpens == nativeCloses);
}
'''
with tempfile.TemporaryDirectory(prefix='backend-storage-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(shim + harness + mapped(source_path, source, stripped_includes=True) + checks)
    compile_cpp(['c++', '-std=c++17', '-DNATIVE_BUILD', '-fsanitize=address,undefined',
                 '-I' + str(root / 'include'), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                 str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    run_cpp([str(path / 'check')], check=True)
print('PASS: complete backend NVS migration, identity, lock/license restoration, defaults, write/commit/open failures')
