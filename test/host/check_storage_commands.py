"""Exercise storage command validation and cleanup guards."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Commands.cpp').read_text()
begin = source.index('    else if (command == "CHECK_STORAGE_STATUS")', source.index('void BackendAgent::executeCommand('))
end = source.index('    else if (command == "REBOOT_DEVICE")', begin)
branch = source[begin:end].replace('    else if (command == "CHECK_STORAGE_STATUS")', '    if (command == "CHECK_STORAGE_STATUS")', 1)
helpers = source[source.index('bool BackendAgent::executeStorageStatus('):source.index('void BackendAgent::finishCommand(')].replace('BackendAgent::', 'Agent::')
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
uint32_t millis() { return 42; }
struct Preferences { bool isKey(const char *) { return true; } bool remove(const char *) { return true; } void end() {} } preferences;
Preferences &backendPreferences() { return preferences; }
bool beginBackendPreferences(bool) { return true; }
int clears=0, reads=0;
bool clearUnusedWifi(String &) { ++clears; return true; }
bool readNvsInventory(uint32_t, const String &, String &output, String &) { ++reads; output="{}"; return true; }
struct Agent {
    String nvsInventory_, gnssVerification_="old", autoBaseProgress_="previous"; uint32_t nvsInventoryMs_=0;
    bool active=false, surveyInMonitoring_=false, surveyInReadbackReady_=false;
    bool workflowActive() { return active; }
    bool executeStorageStatus(JsonObject, const String &, String &);
    bool executeNvsCleanup(JsonObject, String &, String &);
    bool run(String command, JsonObject payload) {
        String error, detail, commandId="test"; bool success=true;
'''
checks = r'''
        return success;
    }
};
''' + helpers + r'''
int main() {
    DynamicJsonDocument request(512); auto payload=request.to<JsonObject>(); Agent agent;
    payload["inspect"]=true; payload["offset"]=8193;
    assert(!agent.run("CHECK_STORAGE_STATUS", payload) && reads==0);
    payload["offset"]=0; assert(agent.run("CHECK_STORAGE_STATUS", payload) && reads==1 && agent.nvsInventoryMs_==42 && agent.gnssVerification_.isEmpty());
    payload.clear(); payload["group"]="unused_wifi"; payload["confirm"]="wrong";
    assert(!agent.run("CLEAR_NVS_DATA", payload) && clears==0);
    payload["confirm"]="unused_wifi"; agent.active=true;
    assert(!agent.run("CLEAR_NVS_DATA", payload) && clears==0);
    agent.active=false; agent.surveyInMonitoring_=true;
    assert(!agent.run("CLEAR_NVS_DATA", payload) && clears==0);
    agent.surveyInReadbackReady_=true; assert(agent.run("CLEAR_NVS_DATA", payload) && clears==1);
    payload["group"]="auto_base_history"; payload["confirm"]="auto_base_history";
    assert(agent.run("CLEAR_NVS_DATA", payload) && agent.autoBaseProgress_=="{}");
}
'''
with tempfile.TemporaryDirectory(prefix='storage-commands-') as directory:
    path=Path(directory); (path/'check.cpp').write_text(harness+branch+checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(root/'test/host'),'-I'+str(root/'.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path/'check.cpp'),'-o',str(path/'check')], check=True)
    subprocess.run([str(path/'check')], check=True)
print('PASS: storage paging validation and cleanup workflow guards')
