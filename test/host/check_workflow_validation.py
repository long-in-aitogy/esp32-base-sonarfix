"""Invalid workflow requests must not stop transport or write the receiver."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Workflows.cpp').read_text()
methods = []
for name, next_state in [('runAutoBaseWorkflow', 'auto_setup_rover'), ('runReferenceCheckWorkflow', 'reference_check_rover')]:
    start = source.index('bool BackendAgent::' + name + '(')
    end = source.index('    setAgentState("' + next_state + '");', start)
    methods.append(source[start:end] + '    finish(false, false, "simulated failure");\n    return false;\n}\n')
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cmath>
#include <cassert>
constexpr size_t CONFIG_DOCUMENT_SIZE = 4096;
double coordinateNumber(JsonVariantConst value) { return value.isNull() ? NAN : value.as<double>(); }
struct BackendAgent {
    String baseStartupState_;
    void markStatusDirty() {}
    String baseConfig_ = R"({"base_setup_method":"SURVEY_IN","survey_in_duration":1800})";
    uint32_t surveyInTargetSeconds_ = 120;
    bool valid = false, stopOk = true, restoreOk = true;
    int writes = 0, stops = 0, restarts = 0, saved = 0;
    String stage;
    template<class... T> bool prepareAutoBaseConfig(T&&...) { return valid; }
    template<class... T> bool prepareReferenceCheckConfig(T&&...) { return valid; }
    bool stopNtripRoverLocked() { ++stops; return stopOk; }
    bool restoreWorkflowBase(JsonObjectConst) { ++writes; return restoreOk; }
    bool restartConfiguredNtrip() { ++restarts; return true; }
    String normalAgentState() { return "ready"; }
    void setAgentState(const String &) {}
    void setWorkflowProgress(const String &s, int, int, const String &) { stage = s; }
    void saveStatePreferences() { ++saved; }
    bool runAutoBaseWorkflow(JsonObject);
    bool runReferenceCheckWorkflow(JsonObject);
};
'''
checks = r'''
int main() {
    DynamicJsonDocument request(256);
    BackendAgent agent;
    assert(!agent.runAutoBaseWorkflow(request.to<JsonObject>()));
    assert(agent.stage == "failed" && agent.saved == 1);
    assert(!agent.runReferenceCheckWorkflow(request.as<JsonObject>()));
    assert(agent.stage == "reference_check_failed" && agent.saved == 2);
    assert(agent.stops == 0 && agent.writes == 0 && agent.restarts == 0);
    for (auto workflow : {&BackendAgent::runAutoBaseWorkflow, &BackendAgent::runReferenceCheckWorkflow}) {
        BackendAgent blocked; blocked.valid = true; blocked.stopOk = false;
        assert(!(blocked.*workflow)(request.as<JsonObject>()));
        assert(blocked.stops == 1 && blocked.writes == 0 && blocked.restarts == 0);
        BackendAgent rejected; rejected.valid = true; rejected.restoreOk = false;
        assert(!(rejected.*workflow)(request.as<JsonObject>()));
        assert(rejected.stops == 1 && rejected.writes == 1 && rejected.restarts == 0);
        BackendAgent restored; restored.valid = true;
        assert(!(restored.*workflow)(request.as<JsonObject>()));
        assert(restored.stops == 1 && restored.writes == 1 && restored.restarts == 1);
    }
}
'''
with tempfile.TemporaryDirectory(prefix='workflow-validation-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + '\n'.join(methods) + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'),
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: invalid requests leave receiver untouched; failed cleanup never restarts transport')
