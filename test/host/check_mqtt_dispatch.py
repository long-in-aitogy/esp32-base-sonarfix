"""Exercise actual MQTT dispatch and reconnect policy without a modem/broker."""
from pathlib import Path
import subprocess
import tempfile
from host_coverage import compile_cpp, run_cpp, cpp_output, mapped

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/mqtt/MQTT_Manager.cpp').read_text()
callback = 'void mqttCallback(' + source.split('void mqttCallback(', 1)[1].split('\nbool probeMqttTransport', 1)[0]
connect = 'int connectMQTT() {' + source.split('int connectMQTT() {', 1)[1].split('\nint publishHealth', 1)[0]
shim = (root / 'test/host/Arduino.h').read_text().replace('#pragma once', '')
shim = shim.replace('    void println(', '    template<class T> void print(const T &) {}\n    void println(')
harness = r'''
#include <cassert>
#include <cstring>
#include <vector>
using byte = uint8_t;
constexpr const char *TOPIC_SUB_CMD = "legacy", *MQTT_USER = "test-user", *MQTT_PASS = "test-password";
constexpr unsigned HEX = 16;
uint32_t now = 100, lastMqttConnectAttemptMs = 0;
uint32_t millis() { return now; }
long random(long) { return 1; }
unsigned dispatched = 0, backendMessages = 0, shutdowns = 0, restarts = 0;
bool restartRequested = false;
enum cmd_action_t { CMD_ACTION_NONE, CMD_ACTION_ESP_RESTART };
std::vector<String> splitCommand(const String &) { return {}; }
cmd_action_t handleCommand(std::vector<String> &) { ++dispatched; return restartRequested ? CMD_ACTION_ESP_RESTART : CMD_ACTION_NONE; }
void shutdownTcpTransportBeforeRestart() { ++shutdowns; }
struct { void restart() { ++restarts; } } ESP;
struct {
    bool locked = false;
    unsigned online = 0, offline = 0;
    bool isLocked() { return locked; }
    void onMqttMessage(const char *, const uint8_t *, size_t) { ++backendMessages; }
    String serial() { return "esp_test"; }
    String lwtPayload() { return "{}"; }
    void onMqttConnected() { ++online; }
    void onMqttDisconnected() { ++offline; }
} backendAgent;
struct {
    bool ready = false, accept = false;
    unsigned attempts = 0;
    std::vector<std::string> topics;
    bool connected() { return ready; }
    template<class... Args> bool connect(Args...) { ++attempts; return ready = accept; }
    bool subscribe(const char *topic, int = 0) { topics.emplace_back(topic); return true; }
    int state() { return -1; }
} mqtt;
struct {
    void begin(const char *, bool) {}
    void end() {}
    String getString(const char *, const String &fallback) { return fallback; }
} prefs;
'''
checks = r'''
int main() {
    char topic[] = "legacy", jsonTopic[] = "pi/devices/esp_test/command";
    byte command[] = "ATG CONFIG RESET";
    mqttCallback(nullptr, command, 1); mqttCallback(topic, nullptr, 1); mqttCallback(topic, command, 0);
    assert(backendMessages == 0);
    mqttCallback(jsonTopic, command, sizeof(command)-1); assert(dispatched == 0 && backendMessages == 1);
    backendAgent.locked = true; mqttCallback(topic, command, sizeof(command)-1); assert(dispatched == 0);
    backendAgent.locked = false;
    mqttCallback(topic, command, sizeof(command)); assert(dispatched == 0); // Embedded NUL.
    std::vector<byte> oversized(1025, 'A'); mqttCallback(topic, oversized.data(), oversized.size()); assert(dispatched == 0);
    mqttCallback(topic, command, sizeof(command)-1); assert(dispatched == 1);
    restartRequested = true; mqttCallback(topic, command, sizeof(command)-1);
    assert(dispatched == 2 && shutdowns == 1 && restarts == 1);
    assert(connectMQTT() == -1 && mqtt.attempts == 1 && backendAgent.offline == 1);
    now = 1000; assert(connectMQTT() == -1 && mqtt.attempts == 1);
    now = 5100; mqtt.accept = true;
    assert(connectMQTT() == 0 && mqtt.attempts == 2 && backendAgent.online == 1);
    assert(mqtt.topics.size() == 5);
    assert(mqtt.topics[0] == "pi/devices/esp_test/command" && mqtt.topics[4] == "pi/devices/esp_test/control_ack");
    assert(connectMQTT() == 0 && mqtt.attempts == 2 && backendAgent.online == 1);
}
'''
callback = mapped(root / 'src/functions/mqtt/MQTT_Manager.cpp', callback)
connect = mapped(root / 'src/functions/mqtt/MQTT_Manager.cpp', connect)
with tempfile.TemporaryDirectory(prefix='mqtt-dispatch-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(shim + harness + callback + connect + checks)
    compile_cpp(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    run_cpp([str(path / 'check')], check=True)
print('PASS: MQTT JSON/legacy routing, locked/NUL/oversized input, restart cleanup, reconnect backoff and subscriptions')
