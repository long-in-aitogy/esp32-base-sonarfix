"""Run local AutoNearest only after connectivity, license and lock checks."""
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[2]
source=(root/'src/functions/backend/Backend_Agent_Startup.cpp').read_text()
method=source[source.index('void BackendAgent::startBootAutoBaseWhenReady('):]
harness=r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
constexpr size_t CONFIG_DOCUMENT_SIZE=4096;
constexpr int WL_CONNECTED=3;
bool gsm=false, connected=false;
bool isGsmConnection() { return gsm; }
struct { bool isGprsConnected() { return connected; } } modem;
struct { int status() { return connected ? WL_CONNECTED : 0; } } WiFi;
struct BackendAgent {
    String baseStartupState_="awaiting_auto_base",baseStartupError_,statusBootId_="boot";
    struct { bool all=false; } stationLock_;
    bool licenseValid_=true,active=false,startOk=true,dirty=false;
    int calls=0; String requestJson;
    bool workflowActive() { return active; }
    void markStatusDirty() { dirty=true; }
    bool executeAutoBaseCommand(JsonObject request,String &error,String &) {
        ++calls; serializeJson(request,requestJson); error="start failed"; return startOk;
    }
    void startBootAutoBaseWhenReady();
};
'''
checks=r'''
int main() {
    BackendAgent agent; agent.startBootAutoBaseWhenReady(); assert(agent.calls==0);
    connected=true; agent.licenseValid_=false; agent.startBootAutoBaseWhenReady(); assert(agent.calls==0);
    agent.licenseValid_=true; agent.stationLock_.all=true; agent.startBootAutoBaseWhenReady(); assert(agent.calls==0);
    agent.stationLock_.all=false; agent.active=true; agent.startBootAutoBaseWhenReady(); assert(agent.calls==0);
    agent.active=false; agent.startBootAutoBaseWhenReady(); assert(agent.calls==1 && agent.baseStartupState_=="auto_base_running");
    DynamicJsonDocument request(4096); assert(!deserializeJson(request,agent.requestJson));
    assert(request["source_mode"]=="nearest" && request["auto_apply"]==true && request["startup_auto"]==true);
    assert(request["enable_itrf_vn2000_transform"]==false && request["startup_boot_id"]=="boot");
    agent.startBootAutoBaseWhenReady(); assert(agent.calls==1);
    BackendAgent failed; failed.startOk=false; gsm=true; failed.startBootAutoBaseWhenReady();
    assert(failed.calls==1 && failed.baseStartupState_=="error" && failed.baseStartupError_=="start failed" && failed.dirty);
}
'''
with tempfile.TemporaryDirectory(prefix='autocors-scheduler-') as directory:
    path=Path(directory); (path/'check.cpp').write_text(harness+method+checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(root/'test/host'),'-I'+str(root/'.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: AutoNearest scheduler connectivity, license, lock and duplicate-start gating')
