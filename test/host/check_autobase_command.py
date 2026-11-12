"""Verify Auto Base source and automatic-apply request validation."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Commands.cpp').read_text()
begin = source.index('bool BackendAgent::executeAutoBaseCommand(')
end = source.index('\nbool BackendAgent::', begin + 5)
method = source[begin:end]
reference_begin = source.index('bool BackendAgent::executeReferenceCheckCommand(')
reference_end = source.index('\nbool BackendAgent::', reference_begin + 5)
method += source[reference_begin:reference_end]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
constexpr size_t CONFIG_DOCUMENT_SIZE = 6144;
const char *AUTO_BASE_CASTER_HOST="caster", *AUTO_BASE_CASTER_USER="user", *AUTO_BASE_CASTER_PASSWORD="pass", *AUTO_BASE_CASTER_MOUNTPOINT="nearest";
constexpr int AUTO_BASE_CASTER_PORT=2101;
bool transportHeld=true;
void stopNtrip() { assert(transportHeld); }
void stopNtripRover() { assert(transportHeld); }
struct BackendAgent {
    String statusBootId_="boot", sensorType_ = "Ublox", baseConfig_ = R"({"base_setup_method":"SURVEY_IN"})", baseStartupState_, baseStartupError_;
    String agentState_ = "ready", autoBaseProgress_ = "old-progress";
    bool roverOk=true, saveOk=true, startOk=true, restoreOk=true, restartOk=true;
    int published=0, saves=0, failOnSave=0, restarts=0;
    bool applyRoverMode() { return roverOk; }
    bool saveStatePreferences() { ++saves; return saveOk && saves != failOnSave; }
    bool restoreWorkflowBase(JsonObjectConst) { if (restoreOk) baseStartupState_="configured"; return restoreOk; }
    bool restartConfiguredNtrip(bool locked) { assert(locked && transportHeld); ++restarts; return restartOk; }
    void publishConfigState(const char *) { ++published; }
    void markStatusDirty() {}
    void setWorkflowProgress(const char *phase, int, int) { autoBaseProgress_ = phase; }
    bool running = false, startImmediately = false; int started = 0; String progress;
    bool workflowActive() { return running; }
    bool startWorkflow(const char *, const String &) { ++started; if (startImmediately) { agentState_="running"; autoBaseProgress_="running"; baseStartupState_="running"; } return startOk; }
    void setAgentState(const String &state) { agentState_ = state; }
    void setWorkflowProgress(const char *, int, int, const String &value) { progress = value; autoBaseProgress_ = value; }
    bool executeAutoBaseCommand(JsonObject, String &, String &);
    bool executeReferenceCheckCommand(JsonObject, String &, String &);
};
'''
checks = r'''
int main() {
    DynamicJsonDocument doc(1024); JsonObject request = doc.to<JsonObject>();
    request["ip"]="host"; request["port"]=2101; request["user"]="user";
    request["password"]="secret"; request["mountpoint"]="station";
    request["source_name"]="Station A"; request["source_serial"]="serial-a"; request["source_distance_m"]=12.5;
    BackendAgent agent; agent.baseStartupState_="configured"; String error, detail;
    assert(agent.executeAutoBaseCommand(request, error, detail) && agent.started == 1);
    assert(agent.baseStartupState_=="configured");
    DynamicJsonDocument progress(4096); assert(!deserializeJson(progress, agent.progress));
    assert(progress["source_name"] == "Station A" && progress["source_serial"] == "serial-a");
    assert(progress["source_distance_m"] == 12.5 && progress["note"] == "Collect RTK Fixed LLH; results wait for review.");
    request["auto_apply"] = true;
    assert(!agent.executeAutoBaseCommand(request, error, detail) && agent.started == 1);
    assert(error == "automatic apply is only supported for nearest CORS mode");
    request["source_mode"] = "nearest";
    assert(agent.executeAutoBaseCommand(request, error, detail) && agent.started == 2);
    assert(agent.baseStartupState_=="auto_base_running");
    assert(agent.baseConfig_ == R"({"base_setup_method":"SURVEY_IN"})" && agent.published == 0);
    BackendAgent immediate; immediate.startImmediately = true;
    assert(immediate.executeAutoBaseCommand(request, error, detail));
    assert(immediate.agentState_ == "running" && immediate.autoBaseProgress_ == "running" && immediate.baseStartupState_ == "running");
    progress.clear(); assert(!deserializeJson(progress, agent.progress));
    assert(progress["note"] == "Collect RTK Fixed LLH and apply Base coordinates after quality checks.");
    DynamicJsonDocument pending(1024); pending["source_mode"]="nearest"; pending["auto_apply"]=true;
    BackendAgent local;
    assert(local.executeAutoBaseCommand(pending.as<JsonObject>(), error, detail));
    assert(local.baseStartupState_=="awaiting_auto_base" && local.started==0);
    DynamicJsonDocument saved(1024); assert(!deserializeJson(saved,local.baseConfig_));
    assert(saved["base_setup_method"]=="AUTO_CORS" && saved["auto_cors_source_mode"]=="nearest");
    assert(saved["auto_base_previous_config"]["base_setup_method"]=="SURVEY_IN");
    assert(local.executeAutoBaseCommand(pending.as<JsonObject>(), error, detail));
    saved.clear(); assert(!deserializeJson(saved,local.baseConfig_));
    assert(saved["auto_base_previous_config"]["base_setup_method"]=="SURVEY_IN");
    assert(saved["auto_base_previous_config"]["auto_base_previous_config"].isNull());
    BackendAgent failed; failed.roverOk=false;
    assert(!failed.executeAutoBaseCommand(pending.as<JsonObject>(), error, detail));
    assert(failed.baseConfig_==R"({"base_setup_method":"SURVEY_IN"})" && failed.baseStartupState_=="configured");
    BackendAgent restoreFailed; restoreFailed.roverOk=false; restoreFailed.restoreOk=false;
    assert(!restoreFailed.executeAutoBaseCommand(pending.as<JsonObject>(), error, detail));
    assert(error == "cannot restore previous Base/NTRIP after AutoNearest failure" && restoreFailed.baseStartupState_ == "error" && restoreFailed.restarts == 0);
    BackendAgent restartFailed; restartFailed.roverOk=false; restartFailed.restartOk=false;
    assert(!restartFailed.executeAutoBaseCommand(pending.as<JsonObject>(), error, detail));
    assert(error == "cannot restore previous Base/NTRIP after AutoNearest failure" && restartFailed.baseStartupState_ == "error" && restartFailed.restarts == 1);
    BackendAgent nvsFailed; nvsFailed.saveOk=false;
    assert(!nvsFailed.executeAutoBaseCommand(pending.as<JsonObject>(), error, detail));
    assert(error == "cannot restore previous Base configuration after AutoNearest save failed" && nvsFailed.baseStartupState_ == "error");
    DynamicJsonDocument startup(1024); startup["source_mode"]="nearest"; startup["auto_apply"]=true; startup["startup_auto"]=true;
    BackendAgent boot;
    boot.baseConfig_=R"({"base_setup_method":"AUTO_CORS","auto_base_request_id":"request"})";
    assert(boot.executeAutoBaseCommand(startup.as<JsonObject>(), error, detail));
    saved.clear(); assert(!deserializeJson(saved,boot.baseConfig_));
    assert(saved["auto_base_started_boot_id"]=="boot" && saved["auto_base_started_request_id"]=="request");
    BackendAgent startFailed; startFailed.startOk=false; startFailed.baseStartupState_="configured";
    startup["sensor_type"] = "Unicorecomm";
    assert(!startFailed.executeAutoBaseCommand(startup.as<JsonObject>(), error, detail));
    assert(startFailed.baseConfig_==R"({"base_setup_method":"SURVEY_IN"})" && startFailed.baseStartupState_=="configured");
    assert(startFailed.agentState_ == "ready" && startFailed.autoBaseProgress_ == "old-progress");
    assert(startFailed.sensorType_ == "Ublox" && startFailed.published == 0);
    BackendAgent rollbackFailed; rollbackFailed.startOk=false; rollbackFailed.failOnSave=2;
    assert(!rollbackFailed.executeAutoBaseCommand(startup.as<JsonObject>(), error, detail));
    assert(error == "cannot restore previous Base configuration after workflow start failed");
    assert(rollbackFailed.sensorType_ == "Ublox" && rollbackFailed.published == 0);
    BackendAgent saveFailed; saveFailed.saveOk=false;
    assert(!saveFailed.executeAutoBaseCommand(startup.as<JsonObject>(), error, detail));
    assert(saveFailed.sensorType_ == "Ublox" && saveFailed.published == 0);
    startup.remove("sensor_type");
    request["source_mode"] = "manual"; request["auto_apply"] = false; request["sensor_type"] = "Unicorecomm";
    BackendAgent manualFailed; manualFailed.startOk = false;
    assert(!manualFailed.executeAutoBaseCommand(request, error, detail));
    assert(manualFailed.sensorType_ == "Ublox" && manualFailed.published == 0);
    request.remove("sensor_type");
    pending["ip"]="partial";
    BackendAgent partial;
    assert(!partial.executeAutoBaseCommand(pending.as<JsonObject>(), error, detail));
    request["source_mode"] = "unknown";
    assert(!agent.executeAutoBaseCommand(request, error, detail) && agent.started == 2);
    assert(error == "unsupported CORS source mode");
    DynamicJsonDocument reference(1024);
    reference["ip"]="host"; reference["port"]=2101; reference["user"]="user";
    reference["password"]="pass"; reference["mountpoint"]="station";
    reference["reference_coords"]["lat"]=21; reference["reference_coords"]["lon"]=105; reference["reference_coords"]["alt"]=10;
    BackendAgent referenceImmediate; referenceImmediate.startImmediately=true;
    assert(referenceImmediate.executeReferenceCheckCommand(reference.as<JsonObject>(), error, detail));
    assert(referenceImmediate.agentState_=="running" && referenceImmediate.autoBaseProgress_=="running");
    BackendAgent referenceFailed; referenceFailed.startOk=false;
    assert(!referenceFailed.executeReferenceCheckCommand(reference.as<JsonObject>(), error, detail));
    assert(referenceFailed.agentState_=="ready" && referenceFailed.autoBaseProgress_=="old-progress");
}
'''
with tempfile.TemporaryDirectory(prefix='autobase-command-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + method + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: source mode and automatic apply validated before starting workflow')
