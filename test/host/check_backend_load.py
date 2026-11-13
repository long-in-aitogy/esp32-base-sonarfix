"""Exercise migration and loading the saved Base configuration together."""
from pathlib import Path
import tempfile
from host_coverage import compile_cpp, mapped, run_cpp

root = Path(__file__).resolve().parents[2]
source_path = root / 'src/functions/backend/Backend_Agent_Storage.cpp'
source = source_path.read_text()
internal = source[source.index('namespace BackendAgentInternal\n{'):source.index('} // namespace BackendAgentInternal') + len('} // namespace BackendAgentInternal')]
load = source[source.index('void BackendAgent::loadPreferences()'):source.index('void BackendAgent::ensureDefaultServiceConfig()')]
shim = (root / 'test/host/Arduino.h').read_text().replace('    bool isEmpty()', '    bool startsWith(const char *text) const { return find(text) == 0; }\n    String substring(size_t pos) const { return substr(pos); }\n    bool isEmpty()')
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <array>
#include <cstdio>
#include "functions/backend/Station_Lock.h"
#include <cassert>
#include <map>
#include <string>
using Store = std::map<std::string, String>;
std::map<std::string, Store> stores;
std::string failOpen, failWrite;
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
} prefs;
constexpr int CONFIG_DOCUMENT_SIZE = 4096, PROGRESS_DOCUMENT_SIZE = 8192;
namespace GnssCmdBuilder { constexpr float BASE_ACCURACY_METERS = 5; }
namespace BackendAgentInternal {
bool licenseMatchesSerial(const String &, const String &token) { return token == "test-license"; }
}

struct BackendAgent {
    String serialNumber_, deviceName_, sensorType_, baseConfig_, serviceConfig_, licenseToken_, lastCommandResult_,
           autoBaseProgress_, surveyInResult_, statusBootId_, agentState_;
    bool provisioned_ = false, licenseValid_ = false;
    StationLock stationLock_;
    void loadPreferences();
    String normalAgentState() const { return stationLock_.all ? "locked" : licenseValid_ ? "online" : "awaiting_license"; }
};
'''
checks = r'''
int main() {
    using namespace BackendAgentInternal;
    stores["nvs/myPrefs"] = {{"DEVICE_SERIAL", "LP_123"}, {"DEVICE_NAME", "station"},
        {"PROVISIONED", "1"}, {"REMOTE_LOCK", "1"}, {"LOCK_SERVERS", "2"},
        {"BASE_JSON", R"({"base_setup_method":"SURVEY_IN","survey_in_accuracy":3})"},
        {"SURVEY_RESULT", R"({"duration":120})"}, {"LICENSE_KEY", "test-license"}, {"RSTRT_COUNT", "7"}};
    BackendAgent agent; agent.loadPreferences();
    assert(agent.serialNumber_ == "esp_123" && agent.deviceName_ == "station");
    assert(agent.provisioned_ && agent.licenseValid_ && agent.stationLock_.all && agent.stationLock_.servers == 2);
    assert(agent.statusBootId_ == "esp_123-00000007" && agent.agentState_ == "locked");
    assert(std::string(backendPreferencesPartition()) == "agent_state");
    DynamicJsonDocument base(1024); assert(!deserializeJson(base, agent.baseConfig_));
    assert(base["survey_in_accuracy"] == 5 && agent.surveyInResult_ == R"({"duration":120})");
    assert(stores["agent_state/backend"]["BASE_JSON"] == agent.baseConfig_);
    stores["nvs/myPrefs"]["DEVICE_NAME"] = "legacy";
    BackendAgent reloaded; reloaded.loadPreferences(); assert(reloaded.deviceName_ == "station");
    stores["agent_state/backend"]["BASE_JSON"] = R"({"base_setup_method":"FIXED_LLA","accuracy":0.01,"coords":{"lat":21,"lon":105,"alt":10,"accuracy":3}})";
    BackendAgent fixed; fixed.loadPreferences();
    assert(!deserializeJson(base, fixed.baseConfig_) && base["accuracy"] == 5 && base["coords"]["accuracy"] == 5);
    assert(stores["agent_state/backend"]["BASE_JSON"] == fixed.baseConfig_);
    failOpen = "agent_state/backend"; BackendAgent fallback; fallback.loadPreferences();
    assert(std::string(backendPreferencesPartition()) == "nvs" && fallback.deviceName_ == "legacy");
    assert(!deserializeJson(base, fallback.baseConfig_) && base["survey_in_accuracy"] == 5);
}
'''
with tempfile.TemporaryDirectory(prefix='backend-load-') as directory:
    path = Path(directory)
    (path / 'Arduino.h').write_text(shim)
    (path / 'check.cpp').write_text(harness + mapped(source_path, internal) + '\nusing namespace BackendAgentInternal;\n' + mapped(source_path, load) + checks)
    compile_cpp(['c++', '-std=c++17', '-DNATIVE_BUILD', '-fsanitize=address,undefined',
                 '-I' + str(path), '-I' + str(root / 'include'),
                 '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                 str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    run_cpp([str(path / 'check')], check=True)
print('PASS: startup migration, 5 m accuracy, saved state and legacy NVS fallback')
