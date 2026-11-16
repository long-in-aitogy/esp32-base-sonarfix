"""Exercise AutoNearest selection, waiting, and Survey-In fallback."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Workflows.cpp').read_text()
start = source.index('bool BackendAgent::runAutoBaseWorkflow(')
end = source.index('\nbool BackendAgent::', start + 5)
method = source[source.index('namespace\n{\n    bool missingAutoNearestPosition('):start] + source[start:end]
sampling = source[source.index('bool BackendAgent::waitForAutoBaseFix('):source.index('String BackendAgent::buildAutoBaseResult(')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include "functions/backend/Base_Sample.h"
#include <array>
#include <cassert>
#include <cmath>
#include <vector>
constexpr size_t CONFIG_DOCUMENT_SIZE = 6144, AUTO_BASE_RESULT_SIZE = 6144;
namespace GnssCmdBuilder { constexpr double BASE_ACCURACY_METERS = 5.0; }
uint32_t now = 10000;
uint32_t millis() { return now; }
int pdMS_TO_TICKS(int ms) { return ms; }
void vTaskDelay(int ms) { now += ms; }
struct GnssTelemetrySnapshot { uint32_t lastGgaMs = 9999; double latitude = 21, longitude = 105, altitude = 12; std::array<char, 16> fixStatus = {"RTK_FIXED"}; } position;
GnssTelemetrySnapshot getGnssTelemetrySnapshot() { position.lastGgaMs = now; return position; }
uint32_t roverDisconnectAt = 0;
const char *ntripRoverLastError() { return "caster disconnected"; }
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
    void setWorkflowProgress(const String &s, int, int, const String &d = String()) {
        stage=s; details=d;
        if (s == "wait_fix" || s == "averaging") {
            DynamicJsonDocument progress(1200); deserializeJson(progress, d);
            if (s == "wait_fix") fixSource = progress["source_mountpoint"] | String();
            else sampleSource = progress["source_mountpoint"] | String();
        }
    }
    void publishConfigState(const char *) {}
    bool applyRoverMode() { return true; }
    bool startAutoBaseRover(const String &, uint16_t, const String &, const String &, const String &, uint8_t, String &failure, String *selected) {
        assert(stage == "connect_caster");
        ++connections; selectedRequested = selected != nullptr;
        if (!connectOk) { failure = error; return false; }
        if (selected) *selected = "selected-station";
        return true;
    }
    int loopNtripRoverLocked() { return roverDisconnectAt && now >= roverDisconnectAt ? 504 : 200; }
    bool waitForAutoBaseFix(uint32_t, uint8_t, bool &, String &, const String &);
    bool collectAutoBaseSamples(int, std::vector<double> &, std::vector<double> &, std::vector<double> &, bool &, String &, const String &);
    bool completeAutoBaseSetup(JsonObject, const std::vector<double> &lat, const std::vector<double> &lon, const std::vector<double> &alt, String &result, String &, const String &) { assert(lat.size() == 60 && lon.size() == 60 && alt.size() == 60); result="{}"; return true; }
    bool restoreAutoBaseAfterReview(JsonDocument &);
    bool prepareAutoBaseSnapshot(JsonDocument &);
    bool waitForAutoNearestPosition(uint32_t);
    bool startSurveyInFallback(JsonObject, JsonDocument &, const String &, const String &, String &);
    void finishAutoBaseWorkflow(JsonDocument &, bool, const String &, bool, bool, const String &);
    bool runAutoBaseWorkflow(JsonObject);
};
'''
checks = r'''
int main() {
    DynamicJsonDocument doc(256); JsonObject payload = doc.to<JsonObject>(); payload["source_mode"] = "nearest";
    BackendAgent selected; assert(selected.runAutoBaseWorkflow(payload));
    assert(selected.selectedRequested && selected.fixSource == "selected-station" && selected.sampleSource == "selected-station");
    assert(selected.details.find("selected-station") != String::npos);
    assert(selected.stage == "ready_for_review" && selected.restores == 1 && selected.restarts == 1);
    roverDisconnectAt = now + 6000;
    BackendAgent disconnected; assert(!disconnected.runAutoBaseWorkflow(payload));
    assert(disconnected.stage == "failed" && disconnected.restores == 1 && disconnected.restarts == 1);
    roverDisconnectAt = 0;
    payload["auto_apply"] = true;
    BackendAgent automatic; assert(automatic.runAutoBaseWorkflow(payload));
    assert(automatic.stage == "completed" && automatic.restores == 0);
    payload["auto_apply"] = false;
    BackendAgent fallback; fallback.connectOk = false; assert(fallback.runAutoBaseWorkflow(payload));
    DynamicJsonDocument saved(1024); assert(!deserializeJson(saved, fallback.baseConfig_));
    assert(saved["base_setup_method"] == "SURVEY_IN" && saved["accuracy"] == 5 && saved["survey_in_accuracy"] == 5);
    assert(saved["survey_in_duration"] == 120);
    assert(saved["coords"].isNull() && fallback.restores == 1 && fallback.restarts == 1);
    BackendAgent duration; duration.connectOk = false;
    duration.baseConfig_ = R"({"base_setup_method":"FIXED_LLA","survey_in_duration":300,"coords":{"lat":21,"lon":105,"alt":4}})";
    assert(duration.runAutoBaseWorkflow(payload));
    saved.clear(); assert(!deserializeJson(saved, duration.baseConfig_));
    assert(saved["survey_in_duration"] == 300);
    payload["startup_auto"] = true;
    BackendAgent bootFallback; bootFallback.connectOk = false;
    bootFallback.baseConfig_ = R"({"base_setup_method":"AUTO_CORS","auto_base_started_boot_id":"boot-1","auto_base_started_request_id":"request-1","auto_base_previous_config":{"base_setup_method":"FIXED_LLA","coords":{"lat":21,"lon":105,"alt":4}}})";
    assert(bootFallback.runAutoBaseWorkflow(payload));
    saved.clear(); assert(!deserializeJson(saved, bootFallback.baseConfig_));
    assert(saved["auto_base_started_boot_id"] == "boot-1" && saved["auto_base_started_request_id"] == "request-1");
    payload["startup_auto"] = false;
    BackendAgent manualFallback; manualFallback.connectOk = false;
    manualFallback.baseConfig_ = R"({"base_setup_method":"FIXED_LLA","auto_base_started_boot_id":"boot-1","coords":{"lat":21,"lon":105,"alt":4}})";
    assert(manualFallback.runAutoBaseWorkflow(payload));
    saved.clear(); assert(!deserializeJson(saved, manualFallback.baseConfig_));
    assert(saved["auto_base_started_boot_id"].isNull());
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
    BackendAgent previousSurvey; previousSurvey.connectOk = false; previousSurvey.error = "network error";
    previousSurvey.baseConfig_ = R"({"base_setup_method":"AUTO_CORS","auto_cors_source_mode":"nearest","auto_base_previous_config":{"base_setup_method":"SURVEY_IN","survey_in_duration":300}})";
    assert(!previousSurvey.runAutoBaseWorkflow(payload));
    saved.clear(); assert(!deserializeJson(saved, previousSurvey.baseConfig_));
    assert(saved["base_setup_method"] == "SURVEY_IN" && saved["survey_in_duration"] == 300);
    BackendAgent snapshotSaveFailure; snapshotSaveFailure.connectOk = false; snapshotSaveFailure.saveOk = false;
    snapshotSaveFailure.error = "network error";
    snapshotSaveFailure.baseConfig_ = R"({"base_setup_method":"AUTO_CORS","auto_base_previous_config":{"base_setup_method":"SURVEY_IN"}})";
    const String pendingConfig = snapshotSaveFailure.baseConfig_;
    assert(!snapshotSaveFailure.runAutoBaseWorkflow(payload));
    assert(snapshotSaveFailure.baseConfig_ == pendingConfig && snapshotSaveFailure.stage == "failed");
    BackendAgent restoreFailure; restoreFailure.restoreOk = false;
    assert(!restoreFailure.runAutoBaseWorkflow(payload) && restoreFailure.stage == "failed");
    payload["source_mode"] = "manual";
    BackendAgent manual; assert(manual.runAutoBaseWorkflow(payload) && !manual.selectedRequested && manual.fixSource == "nearest");
}
'''
with tempfile.TemporaryDirectory(prefix='auto-nearest-workflow-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + sampling + method + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'), '-I' + str(root / 'include'), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: AutoNearest selection, RTK sampling, disconnect, fallback and restoration')
