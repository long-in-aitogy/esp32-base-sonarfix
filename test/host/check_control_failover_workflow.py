"""Control-plane failover must not interrupt a temporary Rover session."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent.cpp').read_text()
method = source[source.index('void BackendAgent::evaluateControlPlaneFailover()'):source.index('void BackendAgent::loop()')]
harness = r'''
#include <cstdint>
#include <cassert>
constexpr uint32_t BACKEND_CONTROL_STALE_MS = 10000, BACKEND_CONTROL_RECOVERY_MS = 6000;
uint32_t clockMs = 0;
uint32_t millis() { return clockMs; }
int setups = 0, connections = 0;
void setupNTRIP() { ++setups; }
void connectNTRIP() { ++connections; }
struct { void println(const char *) {} } Serial;
struct BackendAgent {
    uint32_t lastControlCheckMs_ = 0, recoveryStartedMs_ = 0, controlPlaneArmedMs_ = 0;
    uint32_t lastMqttAckMs_ = 0, lastWebsocketAckMs_ = 0;
    int statusSequence_ = 1, failOpenEntrySequence_ = 0;
    int lastMqttAckSequence_ = 0, lastWebsocketAckSequence_ = 0;
    bool licenseValid_ = true, provisioned_ = true, controlPlaneFailOpen_ = false, active = false;
    bool workflowActive() { return active; }
    void evaluateControlPlaneFailover();
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
}
'''
with tempfile.TemporaryDirectory(prefix='control-failover-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + method + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined', str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: failover and recovery wait for active workflow')
