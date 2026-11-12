"""Ensure configuration notifications retain a full, near-capacity Base or service config."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
agent = (root / 'src/functions/backend/Backend_Agent.cpp').read_text()
copy = agent[agent.index('    bool copyJsonObject('):agent.index('\n} // namespace BackendAgentInternal')]
commands = (root / 'src/functions/backend/Backend_Agent_Commands.cpp').read_text()
publish = commands[commands.index('void BackendAgent::publishConfigState('):commands.index('bool BackendAgent::applyServiceStreamCommand(')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
#include <cstring>
constexpr size_t CONFIG_DOCUMENT_SIZE = 6144, PROGRESS_DOCUMENT_SIZE = 8192;
struct Timestamp { long toInt() const { return 123; } };
Timestamp epochString() { return {}; }
bool mqttConnected() { return true; }
struct Mqtt {
    String payload; unsigned count = 0;
    bool publish(const char *, const char *value, bool) { payload = value; ++count; return true; }
} mqtt;
struct BackendAgent {
    String serialNumber_ = "station", baseConfig_, serviceConfig_;
    void publishConfigState(const char *);
};
'''
checks = r'''
int main() {
    BackendAgent agent;
    // Locate a configuration that fits alone but leaves no room for notification metadata.
    String input;
    size_t expectedCount = 0;
    for (int count = 1; count < 200; ++count) {
        DynamicJsonDocument source(CONFIG_DOCUMENT_SIZE);
        for (int i = 0; i < count; ++i) source[String("field") + String(i)] = String(12, 'x');
        if (source.overflowed()) break;
        String serialized; serializeJson(source, serialized);
        DynamicJsonDocument parsed(CONFIG_DOCUMENT_SIZE), oldEnvelope(CONFIG_DOCUMENT_SIZE);
        assert(!deserializeJson(parsed, serialized));
        oldEnvelope["serial"] = "station"; oldEnvelope["timestamp"] = 123;
        oldEnvelope["type"] = "base_config_state";
        oldEnvelope.createNestedObject("config").set(parsed.as<JsonObjectConst>());
        if (oldEnvelope.overflowed()) { input = serialized; expectedCount = count; break; }
    }
    assert(expectedCount > 0);
    agent.baseConfig_ = input; agent.serviceConfig_ = input;
    for (const char *kind : {"base_config_state", "service_config_state"}) {
        agent.publishConfigState(kind);
        DynamicJsonDocument output(CONFIG_DOCUMENT_SIZE + 1024);
        assert(!deserializeJson(output, mqtt.payload));
        assert(output["type"] == kind && output["config"].size() == expectedCount);
    }
    const unsigned published = mqtt.count;
    agent.baseConfig_ = "{invalid";
    agent.publishConfigState("base_config_state");
    agent.baseConfig_ = "[1,2]";
    agent.publishConfigState("base_config_state");
    agent.baseConfig_ = String("{\"value\":\"") + String(CONFIG_DOCUMENT_SIZE + 1, 'x') + "\"}";
    agent.publishConfigState("base_config_state");
    assert(mqtt.count == published);
    agent.baseConfig_ = "{}";
    agent.publishConfigState("base_config_state");
    assert(mqtt.count == published + 1);
}
'''
with tempfile.TemporaryDirectory(prefix='config-publish-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + copy + publish + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'),
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: Base and service notifications preserve near-capacity configuration')
