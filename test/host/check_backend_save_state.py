"""Exercise actual backend NVS snapshot writes with simulated NVS errors."""
from pathlib import Path
import subprocess
import tempfile
from host_coverage import compile_cpp, mapped, run_cpp

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Storage.cpp').read_text()
method = source[source.index('bool BackendAgent::saveStatePreferences()'):]
harness = r'''
#include <Arduino.h>
#include <cassert>
#include <map>
#include <string>
using esp_err_t = int; using nvs_handle_t = int;
constexpr int ESP_OK = 0, NVS_READWRITE = 1;
constexpr const char *BACKEND_PREFS_PARTITION = "agent_state", *BACKEND_PREFS_NAMESPACE = "backend";
bool useDedicatedBackendPrefs = false, openOk = true, commitOk = true;
int opened = 0, closed = 0, commits = 0; String failedKey, partition;
std::map<String, String> saved;
const char *esp_err_to_name(int) { return "simulated"; }
int nvs_open(const char *, int, nvs_handle_t *handle) { ++opened; *handle = 1; return openOk ? ESP_OK : 1; }
int nvs_open_from_partition(const char *name, const char *space, int mode, nvs_handle_t *handle) {
    partition = name; return nvs_open(space, mode, handle);
}
int nvs_set_str(nvs_handle_t, const char *key, const char *value) {
    if (failedKey == key) return 1;
    saved[key] = value; return ESP_OK;
}
int nvs_set_u8(nvs_handle_t, const char *key, uint8_t value) {
    if (failedKey == key) return 1;
    saved[key] = String(value); return ESP_OK;
}
int nvs_commit(nvs_handle_t) { ++commits; return commitOk ? ESP_OK : 1; }
void nvs_close(nvs_handle_t) { ++closed; }
struct BackendAgent {
    String serialNumber_, deviceName_ = "station", sensorType_ = "Ublox";
    String baseConfig_ = "base", serviceConfig_ = "service", licenseToken_ = "token";
    String lastCommandResult_ = "command", autoBaseProgress_ = "progress", surveyInResult_ = "survey";
    bool provisioned_ = true; struct { bool all = true; uint8_t servers = 2; } stationLock_;
    bool saveStatePreferences();
};
'''
checks = r'''
int main() {
    BackendAgent agent;
    assert(!agent.saveStatePreferences() && opened == 0 && commits == 0);
    agent.serialNumber_ = "esp-test"; openOk = false;
    assert(!agent.saveStatePreferences() && opened == 1 && commits == 0 && closed == 0);
    openOk = true; assert(agent.saveStatePreferences());
    assert(opened == 2 && closed == 1 && commits == 1);
    assert(saved["DEVICE_SERIAL"] == "esp-test" && saved["DEVICE_NAME"] == "station");
    assert(saved["PROVISIONED"] == "1" && saved["REMOTE_LOCK"] == "1" && saved["LOCK_SERVERS"] == "2");
    assert(saved["BASE_JSON"] == "base" && saved["SERVICE_JSON"] == "service" && saved["SURVEY_RESULT"] == "survey");
    failedKey = "SERVICE_JSON"; assert(!agent.saveStatePreferences());
    assert(opened == 3 && closed == 2 && commits == 2);
    failedKey.clear(); commitOk = false; assert(!agent.saveStatePreferences());
    assert(opened == 4 && closed == 3 && commits == 3);
    commitOk = true; useDedicatedBackendPrefs = true;
    assert(agent.saveStatePreferences() && partition == BACKEND_PREFS_PARTITION);
    assert(opened == 5 && closed == 4 && commits == 4);
}
'''
with tempfile.TemporaryDirectory(prefix='backend-save-state-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + mapped(root / 'src/functions/backend/Backend_Agent_Storage.cpp', method) + checks)
    compile_cpp(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'), str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    run_cpp([str(path / 'check')], check=True)
print('PASS: NVS state snapshot, partition choice, write and commit failures')
