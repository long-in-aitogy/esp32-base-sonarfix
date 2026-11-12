"""Exercise the actual restore helper with receiver write/readback boundaries stubbed."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Workflows.cpp').read_text()
number = source[source.index('double coordinateNumber('):source.index('    bool acceptAutoBaseLocationReply(')]
startup = (root / 'src/functions/backend/Backend_Agent_Startup.cpp').read_text()
config_number = startup[startup.index('    constexpr uint32_t AUTO_SURVEY_IN_SECONDS'):startup.index('\n}\n\nbool BackendAgent::readStartupReceiverMode')]
build = startup[startup.index('bool BackendAgent::buildStartupCommands('):startup.index('bool BackendAgent::initializeBaseAtBoot(')]
builder = (root / 'src/functions/gnss/gnss_cmd_builder.cpp').read_text()
sensor_type = builder[builder.index('    GnssSensorType sensorTypeFromString('):builder.index('/** @brief Implements commandListToBytes.') ]
method = source[source.index('bool BackendAgent::restoreWorkflowBase('):source.index('void BackendAgent::runWorkflow()')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
#include <array>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include "functions/gnss/gnss_cmd_builder.h"
#include "functions/gnss/Unicore_Config_Verification.h"
constexpr size_t CONFIG_DOCUMENT_SIZE = 4096;
uint32_t restoredDuration;
float restoredAccuracy;
GnssCmdBuilder::GnssOptions restoredOptions;
double restoredLatitude, restoredLongitude, restoredAltitude;
GnssCmdBuilder::CommandList GnssCmdBuilder::buildBaseSurveyInCommand(uint32_t duration, float accuracy, GnssSensorType, const GnssOptions &options) {
    restoredOptions = options; restoredDuration = duration; restoredAccuracy = accuracy; return {};
}
GnssCmdBuilder::CommandList GnssCmdBuilder::buildBaseFixedLlaCommand(double lat, double lon, double alt, float accuracy, GnssSensorType, const GnssOptions &options) {
    restoredLatitude = lat; restoredLongitude = lon; restoredAltitude = alt;
    restoredAccuracy = accuracy; restoredOptions = options; return {};
}
struct BackendAgent {
    struct StartupPosition { double latitude = 0, longitude = 0, altitude = 0; bool ellipsoid = false; };
    uint32_t surveyInTargetSeconds_ = 0;
    bool surveyInMonitoring_ = false;
    bool buildStartupCommands(JsonObjectConst, GnssCmdBuilder::GnssSensorType, bool, GnssCmdBuilder::CommandList &, StartupPosition &, String &);
    bool verifyStartupReadback(GnssCmdBuilder::GnssSensorType, bool, const StartupPosition &, String &);
    String sensorType_ = "Ublox", baseStartupState_, baseStartupError_, receiverBaseReadback_, baseConfig_;
    bool surveyInResultPending_ = false, writeOk = true, readOk = true;
    int writes = 0, roverCalls = 0;
    bool roverOk = true;
    bool applyRoverMode() { ++roverCalls; return roverOk; }
    GnssCmdBuilder::CommandList lastCommands;
    bool writeGnssCommands(const GnssCmdBuilder::CommandList &commands) { ++writes; lastCommands = commands; return writeOk; }
    bool applyBaseCoordinates(double, double, double) { ++writes; return writeOk; }
    bool refreshReceiverReadback(String &error) { error = "read failed"; return readOk; }
    void markStatusDirty() {}
    bool restoreWorkflowBase(JsonObjectConst);
    void reconcileBaseStartupReadback();
};
'''
checks = r'''
int main() {
    DynamicJsonDocument base(2048);
    base["base_setup_method"] = "SURVEY_IN";
    base["survey_in_duration"] = 120;
    base["survey_in_accuracy"] = 3;
    BackendAgent agent;
    agent.receiverBaseReadback_ = R"({"state":"ok","mode_kind":"survey_in"})";
    assert(agent.restoreWorkflowBase(base.as<JsonObjectConst>()));
    assert(restoredDuration == 120 && restoredAccuracy == 5 && agent.surveyInResultPending_);
    assert(agent.baseStartupState_ == "configured");
    GnssCmdBuilder::CommandList startupCommands;
    BackendAgent::StartupPosition startupPosition;
    String startupError;
    base["survey_in_duration"] = 300;
    assert(agent.buildStartupCommands(base.as<JsonObjectConst>(), GnssCmdBuilder::GnssSensorType::Ublox,
                                      false, startupCommands, startupPosition, startupError));
    assert(restoredDuration == 300 && restoredAccuracy == 5 && agent.surveyInTargetSeconds_ == 300);
    base.remove("survey_in_duration");
    assert(agent.buildStartupCommands(base.as<JsonObjectConst>(), GnssCmdBuilder::GnssSensorType::Ublox,
                                      false, startupCommands, startupPosition, startupError));
    assert(restoredDuration == 120);
    base["survey_in_duration"] = 3601;
    assert(!agent.buildStartupCommands(base.as<JsonObjectConst>(), GnssCmdBuilder::GnssSensorType::Unicore,
                                       false, startupCommands, startupPosition, startupError));
    base["survey_in_duration"] = 1.5;
    assert(!agent.buildStartupCommands(base.as<JsonObjectConst>(), GnssCmdBuilder::GnssSensorType::Ublox,
                                       false, startupCommands, startupPosition, startupError));
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
    agent.receiverBaseReadback_ = R"({"state":"ok","mode_kind":"rover"})";
    assert(!agent.restoreWorkflowBase(base.as<JsonObjectConst>()));
    base.clear(); base["base_setup_method"] = "FIXED_LLA";
    base["coords"]["lat"] = 21.25; base["coords"]["lon"] = 105.75; base["coords"]["alt"] = 10.5;
    base["accuracy"] = 0.5;
    base["gnss_options"]["msm_level"] = "7";
    base["gnss_options"]["constellations"]["glo"] = false;
    agent.receiverBaseReadback_ = R"({"state":"ok","mode_kind":"base","bestpos":{"state":"ok","position_type":"FIXEDPOS","lat":21.25,"lon":105.75,"alt":10.5}})";
    assert(agent.restoreWorkflowBase(base.as<JsonObjectConst>()));
    assert(restoredLatitude == 21.25 && restoredLongitude == 105.75 && restoredAltitude == 10.5);
    assert(restoredAccuracy == 5 && !restoredOptions.glo && restoredOptions.msmLevel == GnssCmdBuilder::MsmLevel::Msm7);
    agent.receiverBaseReadback_ = R"({"state":"ok","mode_kind":"base","bestpos":{"state":"ok","position_type":"FIXEDPOS","lat":22.0,"lon":105.75,"alt":10.5}})";
    assert(!agent.restoreWorkflowBase(base.as<JsonObjectConst>()));
    agent.sensorType_ = "Unicorecomm";
    base["altitude_reference"] = "ELLIPSOID";
    agent.receiverBaseReadback_ = R"({"state":"ok","mode_kind":"base","bestpos":{"state":"ok","position_type":"FIXEDPOS","raw":"#BESTPOSA;SOL_COMPUTED,FIXEDPOS,21.25,105.75,9.5,1.0,WGS84,"}})";
    assert(agent.restoreWorkflowBase(base.as<JsonObjectConst>()));
    assert(!agent.lastCommands.empty());
    const auto &undulation = agent.lastCommands.front();
    assert(std::string(undulation.begin(), undulation.end()) == "config undulation 0.0\r\n");
    agent.receiverBaseReadback_ = R"({"state":"ok","mode_kind":"base","mode_raw":"MODE BASE 21.25 105.75 10.5"})";
    assert(!agent.restoreWorkflowBase(base.as<JsonObjectConst>())); // MODE alone cannot confirm actual BESTPOS.
    agent.receiverBaseReadback_ = R"({"state":"ok","mode_kind":"base","mode_raw":"MODE BASE 21.26 105.75 10.5"})";
    assert(!agent.restoreWorkflowBase(base.as<JsonObjectConst>()));
    agent.receiverBaseReadback_ = R"({"state":"ok","mode_kind":"base","mode_raw":"MODE BASE invalid"})";
    assert(!agent.restoreWorkflowBase(base.as<JsonObjectConst>()));
    base["coords"]["lat"] = 100;
    writes = agent.writes;
    assert(!agent.restoreWorkflowBase(base.as<JsonObjectConst>()) && agent.writes == writes);
    base.clear(); writes = agent.writes;
    assert(agent.restoreWorkflowBase(base.as<JsonObjectConst>()));
    assert(agent.baseStartupState_ == "awaiting_configuration" && agent.writes == writes && agent.roverCalls == 1);
    base["base_setup_method"] = "AUTO_CORS"; base["auto_cors_source_mode"] = "nearest";
    assert(agent.restoreWorkflowBase(base.as<JsonObjectConst>()));
    assert(agent.baseStartupState_ == "awaiting_auto_base" && agent.roverCalls == 2);
    agent.roverOk = false;
    assert(!agent.restoreWorkflowBase(base.as<JsonObjectConst>()));
    assert(agent.baseStartupState_ == "error" && agent.baseStartupError_ == "cannot restore unconfigured receiver to Rover mode");
    agent.roverOk = true;
    base["coords"]["lat"] = 21;
    assert(!agent.restoreWorkflowBase(base.as<JsonObjectConst>())); // Partial coordinates are never treated as unconfigured.
    BackendAgent zero;
    DynamicJsonDocument zeroBase(256);
    zeroBase["base_setup_method"]="FIXED_LLA";
    zeroBase["coords"]["lat"]=0; zeroBase["coords"]["lon"]=0; zeroBase["coords"]["alt"]=0;
    zero.receiverBaseReadback_ = R"({"state":"ok","mode_kind":"base","bestpos":{"state":"ok","position_type":"FIXEDPOS"}})";
    assert(!zero.restoreWorkflowBase(zeroBase.as<JsonObjectConst>()));
    zero.receiverBaseReadback_ = R"({"state":"error","mode_kind":"base","bestpos":{"state":"ok","position_type":"FIXEDPOS","lat":0,"lon":0,"alt":0}})";
    assert(!zero.restoreWorkflowBase(zeroBase.as<JsonObjectConst>()));
    zero.receiverBaseReadback_ = R"({"state":"ok","mode_kind":"base","bestpos":{"state":"ok","position_type":"FIXEDPOS","lat":"bad","lon":0,"alt":0}})";
    assert(!zero.restoreWorkflowBase(zeroBase.as<JsonObjectConst>()));
    zero.receiverBaseReadback_ = R"({"state":"ok","mode_kind":"base","bestpos":{"state":"ok","position_type":"FIXEDPOS","lat":"0.0","lon":0,"alt":0}})";
    assert(zero.restoreWorkflowBase(zeroBase.as<JsonObjectConst>()));
    BackendAgent retry;
    retry.baseConfig_ = R"({"base_setup_method":"FIXED_LLA","coords":{"lat":21.25,"lon":105.75,"alt":10.5}})";
    retry.baseStartupState_ = "error";
    retry.baseStartupError_ = "Receiver has not confirmed the saved fixed position";
    retry.receiverBaseReadback_ = R"({"state":"ok","mode_kind":"base","bestpos":{"state":"ok","position_type":"FIXEDPOS","lat":21.26,"lon":105.75,"alt":10.5}})";
    retry.reconcileBaseStartupReadback();
    assert(retry.baseStartupState_ == "error"); // A different fixed position cannot enable output.
    retry.receiverBaseReadback_ = R"({"state":"ok","mode_kind":"base","bestpos":{"state":"ok","position_type":"FIXEDPOS","lat":21.25,"lon":105.75,"alt":10.5}})";
    retry.baseStartupError_ = "Could not save Base configuration";
    retry.reconcileBaseStartupReadback();
    assert(retry.baseStartupState_ == "error"); // Persistence failures never self-clear.
    retry.baseStartupError_ = "Receiver has not confirmed the saved fixed position";
    retry.reconcileBaseStartupReadback();
    assert(retry.baseStartupState_ == "fixed_restored" && retry.baseStartupError_.isEmpty());
    retry.sensorType_ = "Unicorecomm";
    retry.baseConfig_ = R"({"base_setup_method":"FIXED_LLA","altitude_reference":"ELLIPSOID","coords":{"lat":21.25,"lon":105.75,"alt":10.5}})";
    retry.baseStartupState_ = "error";
    retry.baseStartupError_ = "Receiver has not confirmed the saved fixed position";
    retry.receiverBaseReadback_ = R"({"state":"ok","mode_kind":"base","bestpos":{"state":"ok","position_type":"FIXEDPOS","raw":"#BESTPOSA;SOL_COMPUTED,FIXEDPOS,21.25,105.75,9.5,1.0,WGS84,"}})";
    retry.reconcileBaseStartupReadback();
    assert(retry.baseStartupState_ == "fixed_restored" && retry.baseStartupError_.isEmpty());
}
'''
with tempfile.TemporaryDirectory(prefix='workflow-restore-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + number + config_number + "namespace GnssCmdBuilder {\n" + sensor_type + "}\n" + build + method + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'), '-I' + str(root / 'include'),
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: Survey-In/Fixed restore, invalid parameters, write/read failures and mode mismatch')
