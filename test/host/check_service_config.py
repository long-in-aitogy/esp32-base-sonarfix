"""Repeated service config must preserve connections; real changes must reconnect."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Commands.cpp').read_text()
method = source[source.index('bool BackendAgent::executeServiceConfigCommand('):source.index('bool BackendAgent::executeRawCommand(')]
agent = (root / 'src/functions/backend/Backend_Agent.cpp').read_text()
boolean = agent[agent.index('    bool jsonBool('):agent.index('    String jsonString(')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <array>
#include <cassert>
constexpr size_t CONFIG_DOCUMENT_SIZE = 4096;
int setups = 0, connections = 0;
void setupNTRIP() { ++setups; }
void connectNTRIP() { ++connections; }
struct BackendAgent {
    String serviceConfig_ = "{}";
    int published = 0, saves = 0;
    bool saveOk = true;
    bool saveStatePreferences() { ++saves; return saveOk; }
    void publishConfigState(const String &) { ++published; }
    bool executeServiceConfigCommand(JsonObject, String &, String &);
};
'''
checks = r'''
int main() {
    BackendAgent agent;
    DynamicJsonDocument request(2048);
    request["serverhost1"] = "caster.example";
    request["port1"] = 2101;
    String error, detail;
    assert(agent.executeServiceConfigCommand(request.as<JsonObject>(), error, detail));
    assert(setups == 1 && connections == 1 && agent.published == 1 && agent.saves == 1);
    assert(agent.executeServiceConfigCommand(request.as<JsonObject>(), error, detail));
    assert(setups == 1 && connections == 1 && agent.published == 2 && agent.saves == 1);
    request["port1"] = 2102;
    const String beforeFailure = agent.serviceConfig_;
    agent.saveOk = false;
    assert(!agent.executeServiceConfigCommand(request.as<JsonObject>(), error, detail));
    assert(error == "cannot save service configuration" && agent.serviceConfig_ == beforeFailure);
    assert(setups == 1 && connections == 1 && agent.published == 2);
    agent.saveOk = true;
    assert(agent.executeServiceConfigCommand(request.as<JsonObject>(), error, detail));
    assert(setups == 2 && connections == 2);
    const String previous = agent.serviceConfig_;
    DynamicJsonDocument large(12000);
    large["serverhost1"] = String(std::string(6000, 'x'));
    assert(!agent.executeServiceConfigCommand(large.as<JsonObject>(), error, detail));
    assert(error == "service configuration exceeds memory capacity");
    assert(agent.serviceConfig_ == previous && setups == 2 && connections == 2 && agent.published == 3);
    request.clear(); request.to<JsonObject>();
    assert(!agent.executeServiceConfigCommand(request.as<JsonObject>(), error, detail));
    assert(setups == 2 && connections == 2 && agent.published == 3);
}
'''
with tempfile.TemporaryDirectory(prefix='service-config-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + boolean + method + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'),
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: repeated config preserves connections, changed config reconnects, empty config is rejected')
