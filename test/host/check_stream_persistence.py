"""Stream changes must not be applied when persistence fails."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Commands.cpp').read_text()
method = source[source.index('bool BackendAgent::applyServiceStreamCommand('):source.index('bool BackendAgent::applyLockCommand(')]
stream = source[source.index('bool BackendAgent::executeStreamCommand('):source.index('bool BackendAgent::executeBaseStatusCommand(')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
constexpr size_t CONFIG_DOCUMENT_SIZE = 1024;
String normalizedStreamValue(String s, bool) { return s; }
int streamServerId(JsonObjectConst) { return 0; }
bool applyTargetedStreamState(JsonObject, int, bool, const String &, const String &) { return false; }
void applyGlobalStreamState(JsonObject service, bool active, const String &mountpoint) {
    service["stream_active"] = active;
    if (active && !mountpoint.isEmpty()) service["active_mountpoint"] = mountpoint;
}
int setups = 0, connections = 0;
void setupNTRIP() { ++setups; }
void connectNTRIP() { ++connections; }
struct BackendAgent {
    String serviceConfig_ = "{\"stream_active\":false}";
    bool saveOk = false;
    bool workflowActive() { return false; }
    bool saveStatePreferences() { return saveOk; }
    static bool effectiveStreamActive(JsonObjectConst service, int, bool) { return service["stream_active"] | false; }
    bool applyServiceStreamCommand(JsonObject, String &);
    bool executeStreamCommand(JsonObject, String &, String &);
};
'''
checks = r'''
int main() {
    BackendAgent agent; String error, detail;
    DynamicJsonDocument request(128); request["active"] = true;
    const String previous = agent.serviceConfig_;
    assert(!agent.executeStreamCommand(request.as<JsonObject>(), error, detail));
    assert(error == "cannot save service configuration" && agent.serviceConfig_ == previous);
    assert(setups == 0 && connections == 0);
    agent.saveOk = true;
    assert(agent.executeStreamCommand(request.as<JsonObject>(), error, detail));
    assert(agent.serviceConfig_ != previous && setups == 1 && connections == 1);
    const String current = agent.serviceConfig_;
    DynamicJsonDocument large(4096); large["active"] = true;
    large["mountpoint"] = String(std::string(2000, 'x'));
    assert(!agent.executeStreamCommand(large.as<JsonObject>(), error, detail));
    assert(error == "service configuration exceeds memory capacity" && agent.serviceConfig_ == current);
    assert(setups == 1 && connections == 1);
}
'''
with tempfile.TemporaryDirectory(prefix='stream-persistence-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + method + stream + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined', '-I' + str(root / 'test/host'),
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: stream persistence failure and oversized config preserve connections')
