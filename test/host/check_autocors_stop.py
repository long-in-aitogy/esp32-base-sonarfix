"""Stopping pending AutoNearest must prevent the scheduler from starting it."""
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[2]
source=(root/'src/functions/backend/Backend_Agent_Commands.cpp').read_text()
a=source.index('bool BackendAgent::executeStopWorkflowCommand('); b=source.index('\nbool BackendAgent::executeVerifyGnssCommand(',a)
method=source[a:b]
harness=r'''
#include <Arduino.h>
#include <cassert>
#include <ArduinoJson.h>
constexpr int CONFIG_DOCUMENT_SIZE=6144;
struct BackendAgent {
    String baseStartupState_="awaiting_auto_base", baseStartupError_, baseConfig_="{}", phase, state;
    bool active=false, cancelled=false, dirty=false, restored=false, restarted=false, restoreOk=true, restartOk=true, saveOk=true;
    bool restoreWorkflowBase(JsonObjectConst) { restored=true; if (restoreOk) baseStartupState_="configured"; return restoreOk; }
    bool restartConfiguredNtrip(bool locked) { assert(locked); restarted=true; return restartOk; }
    bool saveStatePreferences() { return saveOk; }
    void publishConfigState(const char *) {}
    bool workflowActive() { return active; }
    void requestWorkflowStop() { cancelled=true; }
    void setWorkflowProgress(const char *value,int,int) { phase=value; }
    void setAgentState(const String &value) { state=value; }
    String normalAgentState() { return "ready"; }
    void markStatusDirty() { dirty=true; }
    bool executeStopWorkflowCommand(String &, String &);
};
'''
checks=r'''
int main() {
    String error, detail; BackendAgent pending;
    assert(pending.executeStopWorkflowCommand(error, detail));
    assert(pending.baseStartupState_=="awaiting_configuration" && pending.phase=="stopped" && pending.dirty);
    BackendAgent saved; saved.baseConfig_=R"({"base_setup_method":"AUTO_CORS","coords":{"lat":21,"lon":105,"alt":7}})";
    assert(saved.executeStopWorkflowCommand(error, detail));
    assert(saved.restored && saved.restarted && saved.baseStartupState_=="configured");
    BackendAgent failed; failed.baseConfig_=saved.baseConfig_; failed.restoreOk=false;
    assert(!failed.executeStopWorkflowCommand(error, detail));
    assert(failed.restored && !failed.restarted && !error.isEmpty());
    BackendAgent survey; survey.baseConfig_=R"({"base_setup_method":"AUTO_CORS","auto_base_previous_config":{"base_setup_method":"SURVEY_IN","survey_in_duration":300}})";
    assert(survey.executeStopWorkflowCommand(error, detail));
    assert(survey.restored && survey.restarted);
    DynamicJsonDocument restored(1024); assert(!deserializeJson(restored, survey.baseConfig_));
    assert(restored["base_setup_method"]=="SURVEY_IN" && restored["survey_in_duration"]==300);
    BackendAgent saveFailure; saveFailure.baseConfig_=R"({"base_setup_method":"AUTO_CORS","auto_base_previous_config":{"base_setup_method":"SURVEY_IN"}})";
    const String pendingConfig=saveFailure.baseConfig_; saveFailure.saveOk=false;
    assert(!saveFailure.executeStopWorkflowCommand(error, detail));
    assert(saveFailure.baseConfig_==pendingConfig && !error.isEmpty());
    BackendAgent streamFailure; streamFailure.baseConfig_=saved.baseConfig_; streamFailure.restartOk=false;
    assert(!streamFailure.executeStopWorkflowCommand(error, detail));
    assert(streamFailure.restored && streamFailure.restarted && !error.isEmpty());
    BackendAgent active; active.active=true;
    assert(active.executeStopWorkflowCommand(error, detail));
    assert(active.cancelled && active.phase=="stopping");
}
'''
with tempfile.TemporaryDirectory(prefix='autocors-stop-') as directory:
    path=Path(directory); (path/'check.cpp').write_text(harness+method+checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(root/'test/host'),'-I'+str(root/'.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: pending and active AutoNearest stop handling')
