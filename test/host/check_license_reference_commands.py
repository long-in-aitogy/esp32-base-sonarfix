"""Check license persistence and reference workflow command rollback."""
from pathlib import Path
import subprocess
import tempfile
from host_coverage import compile_cpp, mapped, run_cpp

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Commands.cpp').read_text()
license_command = source[source.index('bool BackendAgent::executeLicenseCommand('):
                         source.index('bool BackendAgent::executeServiceConfigCommand(')]
reference_command = source[source.index('bool BackendAgent::executeReferenceCheckCommand('):
                           source.index('bool BackendAgent::executeProvinceCommand(')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
uint32_t millis() { return 0; }
bool licenseMatchesSerial(const String &serial, const String &license) {
    return serial == "station" && license == "valid";
}
struct BackendAgent {
    String serialNumber_ = "station", licenseToken_ = "old", agentState_ = "online", autoBaseProgress_ = "old progress";
    bool licenseValid_ = false, saveOk = true, active = false, startOk = false, dirty = false, refreshed = false;
    bool saveStatePreferences() { return saveOk; }
    void setAgentState(const String &state) { agentState_ = state; }
    void refreshWebsocket() { refreshed = true; }
    bool workflowActive() { return active; }
    void setWorkflowProgress(const char *, int, int) { autoBaseProgress_ = "queued"; }
    bool startWorkflow(const String &kind, const String &payload) {
        assert(kind == "reference_check" && !payload.isEmpty());
        return startOk;
    }
    void markStatusDirty() { dirty = true; }
    bool executeLicenseCommand(JsonObject, String &, String &, bool &);
    bool executeReferenceCheckCommand(JsonObject, String &, String &);
};
'''
checks = r'''
int main() {
    BackendAgent agent;
    DynamicJsonDocument document(1024);
    JsonObject payload = document.to<JsonObject>();
    String error, detail;
    bool restart = false;
    assert(!agent.executeLicenseCommand(payload, error, detail, restart));
    payload["license_key"] = "bad";
    assert(!agent.executeLicenseCommand(payload, error, detail, restart));
    payload["license_key"] = "valid"; agent.saveOk = false;
    assert(!agent.executeLicenseCommand(payload, error, detail, restart));
    assert(agent.licenseToken_ == "old" && !agent.licenseValid_ && !restart && !agent.refreshed);
    agent.saveOk = true;
    assert(agent.executeLicenseCommand(payload, error, detail, restart));
    assert(agent.licenseToken_ == "valid" && agent.licenseValid_ && restart && agent.refreshed);
    assert(agent.agentState_ == "rebooting");

    document.clear(); payload = document.to<JsonObject>();
    agent.agentState_ = "online"; agent.active = true;
    assert(!agent.executeReferenceCheckCommand(payload, error, detail));
    agent.active = false;
    assert(!agent.executeReferenceCheckCommand(payload, error, detail));
    assert(!deserializeJson(document, R"({"reference_coords":{"lat":21,"lon":105,"alt":10},"ip":"caster.example","port":2101,"user":"test","password":"test","mountpoint":"BASE"})"));
    payload = document.as<JsonObject>();
    assert(!agent.executeReferenceCheckCommand(payload, error, detail));
    assert(agent.agentState_ == "online" && agent.autoBaseProgress_ == "old progress" && agent.dirty);
    agent.startOk = true;
    assert(agent.executeReferenceCheckCommand(payload, error, detail));
    assert(agent.agentState_ == "reference_check_queued" && agent.autoBaseProgress_ == "queued");
}
'''
with tempfile.TemporaryDirectory(prefix='license-reference-') as directory:
    path = Path(directory)
    source_path = root / 'src/functions/backend/Backend_Agent_Commands.cpp'
    (path / 'check.cpp').write_text(harness + mapped(source_path, license_command) + mapped(source_path, reference_command) + checks)
    compile_cpp(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'),
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    run_cpp([str(path / 'check')], check=True)
print('PASS: license persistence rollback and reference workflow command')
