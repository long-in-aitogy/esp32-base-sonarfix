"""Verify Auto Base source and automatic-apply request validation."""
from pathlib import Path
import subprocess
import tempfile
from host_coverage import compile_cpp, mapped, run_cpp
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Commands.cpp').read_text()
begin = source.index('bool BackendAgent::executeAutoBaseCommand(')
end = source.index('\nbool BackendAgent::', begin + 5)
method = mapped(root / 'src/functions/backend/Backend_Agent_Commands.cpp', source[begin:end])
reference_begin = source.index('bool BackendAgent::executeReferenceCheckCommand(')
reference_end = source.index('\nbool BackendAgent::', reference_begin + 5)
method += mapped(root / 'src/functions/backend/Backend_Agent_Commands.cpp', source[reference_begin:reference_end])
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
constexpr size_t CONFIG_DOCUMENT_SIZE = 6144;
bool enforceBaseAccuracy(JsonObject base) { base["accuracy"] = 5; return true; }
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
    request["auto_base_config"]["gnss_options"]["msm_level"] = "7";
    assert(agent.executeAutoBaseCommand(request, error, detail) && agent.started == 2);
    DynamicJsonDocument saved(1024); assert(!deserializeJson(saved,agent.baseConfig_));
    assert(saved["base_setup_method"]=="AUTO_CORS" && saved["auto_cors_source_mode"]=="nearest");
    assert(saved["gnss_options"]["msm_level"]=="7" && saved["accuracy"]==5 && agent.published == 1);
    assert(agent.baseStartupState_=="auto_base_running");
    progress.clear(); assert(!deserializeJson(progress, agent.progress));
    assert(progress["note"] == "Collect RTK Fixed LLH and apply Base coordinates after quality checks.");
    DynamicJsonDocument pending(1024); pending["source_mode"]="nearest"; pending["auto_apply"]=true;
    BackendAgent local;
    assert(local.executeAutoBaseCommand(pending.as<JsonObject>(), error, detail));
    assert(local.baseStartupState_=="awaiting_auto_base" && local.started==0);
    saved.clear(); assert(!deserializeJson(saved,local.baseConfig_));
    assert(saved["base_setup_method"]=="AUTO_CORS" && saved["auto_cors_source_mode"]=="nearest");
    assert(saved["auto_base_previous_config"].isNull() && saved["accuracy"]==5);
    BackendAgent failed; failed.roverOk=false;
    assert(!failed.executeAutoBaseCommand(pending.as<JsonObject>(), error, detail));
    assert(error=="cannot switch GNSS receiver to Rover mode" && failed.restarts==1);
    saved.clear(); assert(!deserializeJson(saved,failed.baseConfig_) && saved["base_setup_method"]=="AUTO_CORS");
    BackendAgent nvsFailed; nvsFailed.saveOk=false;
    assert(!nvsFailed.executeAutoBaseCommand(pending.as<JsonObject>(), error, detail));
    assert(error=="cannot save nearest CORS request");
    DynamicJsonDocument startup(1024); startup["source_mode"]="nearest"; startup["auto_apply"]=true; startup["startup_auto"]=true;
    startup["startup_boot_id"]="old-boot"; startup["startup_request_id"]="other-request";
    BackendAgent boot; boot.baseConfig_=R"({"base_setup_method":"AUTO_CORS"})";
    assert(boot.executeAutoBaseCommand(startup.as<JsonObject>(), error, detail));
    saved.clear(); assert(!deserializeJson(saved,boot.baseConfig_));
    assert(saved["auto_base_started_boot_id"]=="old-boot" && saved["auto_base_started_request_id"]=="other-request");
    BackendAgent immediate; immediate.startImmediately=true;
    assert(immediate.executeAutoBaseCommand(startup.as<JsonObject>(), error, detail));
    assert(immediate.agentState_=="running" && immediate.autoBaseProgress_=="running" && immediate.baseStartupState_=="running");
    BackendAgent startFailed; startFailed.startOk=false; startFailed.baseStartupState_="configured"; startFailed.baseStartupError_="previous-error";
    assert(!startFailed.executeAutoBaseCommand(startup.as<JsonObject>(), error, detail));
    saved.clear(); assert(!deserializeJson(saved,startFailed.baseConfig_) && saved["base_setup_method"]=="AUTO_CORS");
    assert(error=="cannot start auto base workflow" && startFailed.published==1);
    assert(startFailed.agentState_=="ready" && startFailed.autoBaseProgress_=="old-progress");
    assert(startFailed.baseStartupState_=="configured" && startFailed.baseStartupError_=="previous-error");
    pending["ip"]="partial"; BackendAgent partial;
    assert(partial.executeAutoBaseCommand(pending.as<JsonObject>(), error, detail));
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
    compile_cpp(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    run_cpp([str(path / 'check')], check=True)
print('PASS: source mode and automatic apply validated before starting workflow')
