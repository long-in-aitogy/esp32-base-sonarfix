"""Control-plane failover must not interrupt a temporary Rover session."""
from pathlib import Path
import subprocess
import tempfile
from host_coverage import compile_cpp, mapped, run_cpp

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent.cpp').read_text()
method = source[source.index('void BackendAgent::evaluateControlPlaneFailover()'):source.index('void BackendAgent::loop()')]
ack = source[source.index('void BackendAgent::handleControlAck('):source.index('\nvoid BackendAgent::onMqttMessage(')]
harness = r'''
#include <Arduino.h>
#include <array>
#include <ArduinoJson.h>
#include <cstdint>
#include <cassert>
constexpr uint32_t BACKEND_CONTROL_STALE_MS = 10000, BACKEND_CONTROL_RECOVERY_MS = 6000;
uint32_t clockMs = 0;
uint32_t millis() { return clockMs; }
int setups = 0, connections = 0;
void setupNTRIP() { ++setups; }
void connectNTRIP() { ++connections; }
void xQueueOverwrite(int, const void *) {}
struct BackendAgent {
    struct AutoBaseLocationReply { static constexpr size_t capacity = 1536; std::array<char, capacity> json{}; };
    int autoBaseLocationQueue_ = 0;
    String statusBootId_ = "boot", serialNumber_ = "station";
    uint32_t lastControlCheckMs_ = 0, recoveryStartedMs_ = 0, controlPlaneArmedMs_ = 0;
    uint32_t lastMqttAckMs_ = 0, lastWebsocketAckMs_ = 0;
    int statusSequence_ = 1, failOpenEntrySequence_ = 0;
    int lastMqttAckSequence_ = 0, lastWebsocketAckSequence_ = 0;
    bool licenseValid_ = true, provisioned_ = true, controlPlaneFailOpen_ = false, active = false;
    bool workflowActive() { return active; }
    void evaluateControlPlaneFailover();
    void handleControlAck(const String &, const String &, bool);
};
'''
checks = r'''
int main() {
    BackendAgent agent;
    agent.active = true; clockMs = 12000;
    agent.evaluateControlPlaneFailover();
    assert(!agent.controlPlaneFailOpen_ && setups == 0 && connections == 0);
    agent.active = false; clockMs = 14000;
    agent.evaluateControlPlaneFailover();
    assert(agent.controlPlaneFailOpen_ && setups == 1 && connections == 1);
    agent.lastMqttAckSequence_ = 2; agent.lastMqttAckMs_ = 15000;
    clockMs = 16000; agent.evaluateControlPlaneFailover();
    agent.active = true; clockMs = 22000; agent.evaluateControlPlaneFailover();
    assert(agent.controlPlaneFailOpen_ && setups == 1 && connections == 1);
    agent.active = false; clockMs = 24000; agent.evaluateControlPlaneFailover();
    assert(!agent.controlPlaneFailOpen_ && setups == 2 && connections == 2);

    // Exercise the real ACK parser together with failover, including replayed ACKs.
    BackendAgent replay;
    setups = connections = 0;
    clockMs = 12000; replay.evaluateControlPlaneFailover();
    assert(replay.controlPlaneFailOpen_ && setups == 1);
    const String oldAck = R"({"type":"control_plane_ack","status_boot_id":"boot","serial":"station","status_sequence":1})";
    const String newAck = R"({"type":"control_plane_ack","status_boot_id":"boot","serial":"station","status_sequence":2})";
    const String wrongBoot = R"({"type":"control_plane_ack","status_boot_id":"old","serial":"station","status_sequence":2})";
    clockMs = 14000;
    replay.handleControlAck("mqtt", newAck, true);
    replay.handleControlAck("mqtt", wrongBoot, false);
    replay.handleControlAck("mqtt", oldAck, false);
    replay.evaluateControlPlaneFailover();
    assert(replay.controlPlaneFailOpen_ && replay.recoveryStartedMs_ == 0);
    replay.handleControlAck("websocket", newAck, false);
    clockMs = 16000; replay.evaluateControlPlaneFailover();
    assert(replay.recoveryStartedMs_ == 16000);
    clockMs = 18000; replay.handleControlAck("websocket", newAck, false);
    assert(replay.lastWebsocketAckMs_ == 14000);
    clockMs = 22000; replay.evaluateControlPlaneFailover();
    assert(!replay.controlPlaneFailOpen_ && setups == 2 && connections == 2);
}
'''
with tempfile.TemporaryDirectory(prefix='control-failover-') as directory:
    path = Path(directory)
    source_path = root / 'src/functions/backend/Backend_Agent.cpp'
    (path / 'check.cpp').write_text(harness + mapped(source_path, method) + mapped(source_path, ack) + checks)
    compile_cpp(['c++', '-std=c++17', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'),
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    run_cpp([str(path / 'check')], check=True)
print('PASS: failover, ACK replay and recovery during workflows')
