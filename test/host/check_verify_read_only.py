"""GNSS verification reports its result without writing backend NVS."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Commands.cpp').read_text()
method = source[source.index('void BackendAgent::recordCommandResult('):source.index('void BackendAgent::publishConfigState(')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
struct Epoch { long toInt() { return 123; } };
Epoch epochString() { return {}; }
struct BackendAgent {
    String lastCommandResult_;
    int saves = 0;
    bool saveStatePreferences() { ++saves; return true; }
    void recordCommandResult(const String &, const String &, const String &, const String &, const String &);
};
'''
checks = r'''
int main() {
    BackendAgent agent;
    agent.recordCommandResult("VERIFY_GNSS_CONFIG", "mqtt", "success", "ok", "a");
    assert(agent.saves == 0);
    DynamicJsonDocument doc(1024);
    assert(!deserializeJson(doc, agent.lastCommandResult_));
    assert(doc["command"] == "VERIFY_GNSS_CONFIG" && doc["command_id"] == "a");
    agent.recordCommandResult("DEPLOY_SERVICE_CONFIG", "mqtt", "success", "ok", "b");
    assert(agent.saves == 1);
}
'''
with tempfile.TemporaryDirectory(prefix='esp-verify-read-only-') as directory:
    path = Path(directory)
    shim = (root / 'test/host/Arduino.h').read_text().replace(
        '    bool isEmpty() const', '    String substring(size_t start, size_t end) const { return substr(start, end - start); }\n    bool isEmpty() const')
    (path / 'Arduino.h').write_text(shim)
    (path / 'check.cpp').write_text(harness + method + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined', '-I' + str(path), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'), str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: verification result remains visible without an NVS write')
