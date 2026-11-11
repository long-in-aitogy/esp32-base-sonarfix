"""Exercise AutoNearest selection, waiting, and Survey-In fallback."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Workflows.cpp').read_text()
start = source.index('bool BackendAgent::runAutoBaseWorkflow(')
end = source.index('\nbool BackendAgent::', start + 5)
method = source[start:end]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
#include <cmath>
#include <vector>
constexpr size_t CONFIG_DOCUMENT_SIZE = 4096;
namespace GnssCmdBuilder { constexpr double BASE_ACCURACY_METERS = 5.0; }
uint32_t now = 10000;
uint32_t millis() { return now; }
int pdMS_TO_TICKS(int ms) { return ms; }
void vTaskDelay(int ms) { now += ms; }
struct Position { uint32_t lastGgaMs = 9999; double latitude = 21, longitude = 105; } position;
Position getGnssTelemetrySnapshot() { return position; }
double coordinateNumber(JsonVariantConst value) { return value.isNull() ? NAN : value.as<double>(); }
struct BackendAgent {
    String baseStartupState_;
    void markStatusDirty() {}
    String baseConfig_ = R"({"base_setup_method":"FIXED_LLA","coords":{"lat":21,"lon":105,"alt":4}})";
    uint32_t surveyInTargetSeconds_ = 0;
    bool workflowCancelRequested_ = false, connectOk = true, saveOk = true, restoreOk = true;
    bool selectedRequested = false; int connections = 0, restores = 0, restarts = 0;
    String error = "ERROR - NO STATION WITHIN 20 KM", stage, details, fixSource, sampleSource;
    bool prepareAutoBaseConfig(JsonObject, String &host, uint16_t &port, String &user, String &password, String &mount, uint8_t &version, uint32_t &timeout, uint8_t &streak) {
        host="host"; port=2101; user="user"; password="secret"; mount="nearest"; version=1; timeout=30; streak=5; return true;
    }
    bool stopNtripRoverLocked() { return true; }
    bool restoreWorkflowBase(JsonObjectConst config) { ++restores; return restoreOk && !config.isNull(); }
    bool restartConfiguredNtrip() { ++restarts; return true; }
    bool saveStatePreferences() { return saveOk; }
    String normalAgentState() { return "ready"; }
    void setAgentState(const String &) {}
    void setWorkflowProgress(const String &s, int, int, const String &d = String()) { stage=s; details=d; }
    void publishConfigState(const char *) {}
    bool applyRoverMode() { return true; }
    bool startAutoBaseRover(const String &, uint16_t, const String &, const String &, const String &, uint8_t, String &failure, String *selected) {
        ++connections; selectedRequested = selected != nullptr;
        if (!connectOk) { failure = error; return false; }
        if (selected) *selected = "selected-station";
        return true;
    }
    bool waitForAutoBaseFix(uint32_t, uint8_t, bool &, String &, const String &source) { fixSource=source; return true; }
    bool collectAutoBaseSamples(int, std::vector<double> &, std::vector<double> &, std::vector<double> &, bool &, String &, const String &source) { sampleSource=source; return true; }
    bool completeAutoBaseSetup(JsonObject, const std::vector<double> &, const std::vector<double> &, const std::vector<double> &, String &result, String &) { result="{}"; return true; }
    bool runAutoBaseWorkflow(JsonObject);
};
'''
checks = r'''
int main() {
    DynamicJsonDocument doc(256); JsonObject payload = doc.to<JsonObject>(); payload["source_mode"] = "nearest";
    BackendAgent selected; assert(selected.runAutoBaseWorkflow(payload));
    assert(selected.selectedRequested && selected.fixSource == "selected-station" && selected.sampleSource == "selected-station");
    assert(selected.details.find("selected-station") != String::npos);
    BackendAgent fallback; fallback.connectOk = false; assert(fallback.runAutoBaseWorkflow(payload));
    DynamicJsonDocument saved(1024); assert(!deserializeJson(saved, fallback.baseConfig_));
    assert(saved["base_setup_method"] == "SURVEY_IN" && saved["accuracy"] == 5 && saved["survey_in_accuracy"] == 5);
    assert(saved["coords"].isNull() && fallback.restores == 1 && fallback.restarts == 1);
    BackendAgent failed; failed.connectOk = false; failed.error = "ERROR - FIXED STATION CATALOG UNAVAILABLE";
    assert(!failed.runAutoBaseWorkflow(payload) && failed.restores == 1 && failed.stage == "failed");
    BackendAgent saveFailed; saveFailed.connectOk = false; saveFailed.saveOk = false;
    assert(!saveFailed.runAutoBaseWorkflow(payload) && saveFailed.restores == 2 && saveFailed.stage == "failed");
    position.latitude = 0; position.longitude = 0;
    BackendAgent noPosition; assert(!noPosition.runAutoBaseWorkflow(payload) && noPosition.connections == 0 && noPosition.stage == "failed");
    BackendAgent cancelled; cancelled.baseConfig_ = R"({"base_setup_method":"AUTO_CORS","auto_cors_source_mode":"nearest"})";
    cancelled.workflowCancelRequested_ = true;
    assert(!cancelled.runAutoBaseWorkflow(payload) && cancelled.stage == "stopped");
    assert(cancelled.baseStartupState_ == "awaiting_configuration" && cancelled.connections == 0);
    payload["source_mode"] = "manual";
    BackendAgent manual; assert(manual.runAutoBaseWorkflow(payload) && !manual.selectedRequested && manual.fixSource == "nearest");
}
'''
with tempfile.TemporaryDirectory(prefix='auto-nearest-workflow-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + method + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: AutoNearest selection, GGA timeout, fallback and restoration')
