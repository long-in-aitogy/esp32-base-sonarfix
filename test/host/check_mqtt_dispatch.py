"""Exercise actual MQTT JSON/legacy dispatch and device-lock validation."""
from pathlib import Path
import subprocess
import tempfile
from host_coverage import compile_cpp, mapped, run_cpp
root=Path(__file__).resolve().parents[2]
source=(root/'src/functions/mqtt/MQTT_Manager.cpp').read_text()
callback=source[source.index('void mqttCallback('):source.index('/** @brief Implements probeMqttTransport.')]
shim=(root/'test/host/Arduino.h').read_text().replace('#pragma once','')
shim=shim.replace('    void println(const char *) {}', '    template<class T> void print(const T &) {}\n    void println(const char *) {}\n    void println(const String &) {}')
harness=r'''
#include <cassert>
#include <cstring>
#include <vector>
using byte=uint8_t;
constexpr const char *TOPIC_SUB_CMD="legacy";
String configuredTopic = TOPIC_SUB_CMD;
unsigned dispatched=0, backendMessages=0, shutdowns=0, restarts=0;
bool restartRequested=false;
enum cmd_action_t { CMD_ACTION_NONE, CMD_ACTION_ESP_RESTART };
std::vector<String> splitCommand(const String &) { return {}; }
cmd_action_t handleCommand(std::vector<String> &) { ++dispatched; return restartRequested ? CMD_ACTION_ESP_RESTART : CMD_ACTION_NONE; }
void shutdownTcpTransportBeforeRestart() { ++shutdowns; }
struct { void restart() { ++restarts; } } ESP;
struct {
    bool locked=false;
    bool isLocked() { return locked; }
    void onMqttMessage(const char *,const uint8_t *,size_t) { ++backendMessages; }
} backendAgent;
'''
checks=r'''
int main() {
    char topic[]="legacy", jsonTopic[]="pi/devices/esp_test/command"; byte command[]="ATG CONFIG RESET";
    mqttCallback(nullptr,command,1); mqttCallback(topic,nullptr,1); mqttCallback(topic,command,0);
    assert(backendMessages==0);
    mqttCallback(jsonTopic,command,sizeof(command)-1); assert(dispatched==0 && backendMessages==1);
    backendAgent.locked=true; mqttCallback(topic,command,sizeof(command)-1); assert(dispatched==0);
    backendAgent.locked=false; mqttCallback(topic,command,sizeof(command)); assert(dispatched==0);
    std::vector<byte> oversized(1025,'A'); mqttCallback(topic,oversized.data(),oversized.size()); assert(dispatched==0);
    mqttCallback(topic,command,sizeof(command)-1); assert(dispatched==1);
    configuredTopic="custom/topic"; char customTopic[]="custom/topic";
    mqttCallback(topic,command,sizeof(command)-1); assert(dispatched==2);
    backendAgent.locked=true; mqttCallback(customTopic,command,sizeof(command)-1); assert(dispatched==2);
    backendAgent.locked=false;
    mqttCallback(customTopic,command,sizeof(command)-1); assert(dispatched==2);
    restartRequested=true; mqttCallback(topic,command,sizeof(command)-1); assert(dispatched==3 && shutdowns==1 && restarts==1);
}
'''
with tempfile.TemporaryDirectory(prefix='mqtt-dispatch-') as directory:
    path=Path(directory); (path/'check.cpp').write_text(shim+harness+mapped(root/'src/functions/mqtt/MQTT_Manager.cpp',callback)+checks)
    compile_cpp(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-sign-compare','-fsanitize=address,undefined',str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    run_cpp([str(path/'check')],check=True)
print('PASS: MQTT routing rejects locked, NUL and oversized legacy commands')
