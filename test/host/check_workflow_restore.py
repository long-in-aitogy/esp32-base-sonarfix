"""Exercise the actual restore helper with receiver write/readback boundaries stubbed."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Workflows.cpp').read_text()
number = source[source.index('double coordinateNumber('):source.index('} // namespace')]
method = source[source.index('bool BackendAgent::restoreWorkflowBase('):source.index('void BackendAgent::runWorkflow()')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
#include <cmath>
#include <cstdlib>
#include "functions/gnss/gnss_cmd_builder.h"
uint32_t restoredDuration;
float restoredAccuracy;
GnssCmdBuilder::CommandList GnssCmdBuilder::buildBaseSurveyInCommand(uint32_t duration, float accuracy, GnssSensorType, const GnssOptions &) {
    restoredDuration = duration; restoredAccuracy = accuracy; return {};
}
struct BackendAgent {
    String sensorType_ = "Ublox", baseStartupState_, baseStartupError_, receiverBaseReadback_;
    bool surveyInResultPending_ = false, writeOk = true, readOk = true;
    int writes = 0;
    bool writeGnssCommands(const GnssCmdBuilder::CommandList &) { ++writes; return writeOk; }
    bool applyBaseCoordinates(double, double, double) { ++writes; return writeOk; }
    bool refreshReceiverReadback(String &error) { error = "read failed"; return readOk; }
    void markStatusDirty() {}
    bool restoreWorkflowBase(JsonObjectConst);
};
'''
checks = r'''
int main() {
    DynamicJsonDocument base(2048);
    base["base_setup_method"] = "SURVEY_IN";
    base["survey_in_duration"] = 120;
    base["survey_in_accuracy"] = 5;
    BackendAgent agent;
    agent.receiverBaseReadback_ = R"({"mode_kind":"survey_in"})";
    assert(agent.restoreWorkflowBase(base.as<JsonObjectConst>()));
    assert(restoredDuration == 120 && restoredAccuracy == 5 && agent.surveyInResultPending_);
    assert(agent.baseStartupState_ == "configured");
    base["survey_in_duration"] = 300;
    assert(agent.restoreWorkflowBase(base.as<JsonObjectConst>()) && restoredDuration == 300);
    base["survey_in_duration"] = -1;
    int writes = agent.writes;
    assert(!agent.restoreWorkflowBase(base.as<JsonObjectConst>()) && agent.writes == writes);
    base["survey_in_duration"] = 120;
    agent.writeOk = false;
    assert(!agent.restoreWorkflowBase(base.as<JsonObjectConst>()));
    agent.writeOk = true; agent.readOk = false;
    assert(!agent.restoreWorkflowBase(base.as<JsonObjectConst>()));
    agent.readOk = true;
    agent.receiverBaseReadback_ = R"({"mode_kind":"rover"})";
    assert(!agent.restoreWorkflowBase(base.as<JsonObjectConst>()));
    base.clear(); base["base_setup_method"] = "FIXED_LLA";
    base["coords"]["lat"] = 21.0; base["coords"]["lon"] = 105.0; base["coords"]["alt"] = 10.0;
    agent.receiverBaseReadback_ = R"({"mode_kind":"base"})";
    assert(agent.restoreWorkflowBase(base.as<JsonObjectConst>()));
    base.clear(); writes = agent.writes;
    assert(agent.restoreWorkflowBase(base.as<JsonObjectConst>()));
    assert(agent.baseStartupState_ == "awaiting_configuration" && agent.writes == writes);
}
'''
with tempfile.TemporaryDirectory(prefix='workflow-restore-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + number + method + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'), '-I' + str(root / 'include'),
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: Survey-In/Fixed restore, invalid parameters, write/read failures and mode mismatch')
