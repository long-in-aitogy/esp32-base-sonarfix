"""Retry persistence of confirmed Survey-In results when NVS fails."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Gnss.cpp').read_text()
method = source[source.index('void BackendAgent::saveSurveyResult('):source.index('bool BackendAgent::refreshUbloxReadback(')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
struct Epoch { long toInt() { return 123; } };
Epoch epochString() { return {}; }
struct BackendAgent {
    bool surveyInMonitoring_ = true, surveyInReadbackReady_ = true, surveyInReadbackHasPosition_ = true;
    bool surveyInResultPending_ = true, saveOk = false;
    int attempts = 0;
    String sensorType_ = "Unicorecomm", surveyInResult_ = "{}";
    bool saveStatePreferences() { ++attempts; return saveOk; }
    void saveSurveyResult(JsonObjectConst, const String &);
};
'''
checks = r'''
int main() {
    BackendAgent agent;
    DynamicJsonDocument doc(512);
    deserializeJson(doc, R"({"state":"ok","position_type":"FIXEDPOS","lat":"21"})");
    agent.saveSurveyResult(doc.as<JsonObjectConst>(), "MODE BASE TIME 300");
    assert(agent.attempts == 1 && agent.surveyInResultPending_);
    agent.saveOk = true;
    agent.saveSurveyResult(doc.as<JsonObjectConst>(), "MODE BASE TIME 300");
    assert(agent.attempts == 2 && !agent.surveyInResultPending_);
    agent.saveSurveyResult(doc.as<JsonObjectConst>(), "MODE BASE TIME 300");
    assert(agent.attempts == 2);
    agent.surveyInResult_ = "{}"; agent.saveOk = false;
    agent.saveSurveyResult(doc.as<JsonObjectConst>(), "MODE BASE TIME 300");
    assert(agent.attempts == 3 && agent.surveyInResultPending_);
    agent.surveyInReadbackReady_ = false;
    agent.saveSurveyResult(doc.as<JsonObjectConst>(), "MODE BASE TIME 300");
    assert(agent.attempts == 3);
}
'''
with tempfile.TemporaryDirectory(prefix='esp-survey-retry-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + method + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined', '-I' + str(root / 'test/host'), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'), str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: confirmed Survey-In result retries failed NVS save and stops after success')
