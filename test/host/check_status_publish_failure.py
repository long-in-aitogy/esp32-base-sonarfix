"""Do not publish a partial or empty status when JSON allocation fails."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
agent = (root / 'src/functions/backend/Backend_Agent.cpp').read_text()
publish = agent[agent.index('void BackendAgent::publishStatus('):agent.index('String BackendAgent::lwtPayload()')]
status = (root / 'src/functions/backend/Backend_Agent_Status.cpp').read_text()
start = status.index('    if (doc.overflowed())', status.index('String BackendAgent::buildStatusPayload()'))
finish = status[start:status.index('\n}', start) + 2]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
constexpr unsigned BACKEND_STATUS_INTERVAL_MS = 1000;
unsigned now = 100;
unsigned millis() { return now; }
struct Mqtt { int calls = 0; bool publish(const char *, const char *, bool) { ++calls; return true; } } mqtt;
struct Socket { int calls = 0; void sendText(const String &) { ++calls; } } socket;
struct BackendAgent {
    String serialNumber_ = "station", nextPayload;
    bool statusDirty_ = false, statusPublishConfirmed_ = false;
    unsigned statusSequence_ = 0, controlPlaneArmedMs_ = 0, lastStatusMs_ = 0;
    Socket *websocket_ = &socket;
    String buildStatusPayload() { return nextPayload; }
    bool mqttConnected() { return true; }
    bool websocketConnected() { return true; }
    String statusTopic() { return "status"; }
    void publishStatus(bool);
};
String finishStatus(DynamicJsonDocument &doc) {
'''
checks = r'''
int main() {
    DynamicJsonDocument good(256); good["serial"] = "station";
    String payload = finishStatus(good);
    assert(payload == "{\"serial\":\"station\"}");
    DynamicJsonDocument overflow(32); overflow["long"] = String(512, 'x');
    assert(overflow.overflowed() && finishStatus(overflow).isEmpty());
    BackendAgent agent;
    agent.publishStatus(true);
    assert(mqtt.calls == 0 && socket.calls == 0);
    assert(agent.lastStatusMs_ == now);
    agent.nextPayload = payload;
    agent.publishStatus(false); // Allocation failure retries at the normal interval.
    assert(mqtt.calls == 0 && socket.calls == 0);
    now += BACKEND_STATUS_INTERVAL_MS;
    agent.publishStatus(false);
    assert(mqtt.calls == 1 && socket.calls == 1);
}
'''
with tempfile.TemporaryDirectory(prefix='status-publish-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + finish + publish + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'),
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: incomplete status is not published and retries at the normal interval')
