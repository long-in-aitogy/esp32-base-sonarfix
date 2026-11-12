"""Exercise the real source loop across reconnect, backoff and dual-server states."""
from pathlib import Path
import subprocess
import tempfile
from host_coverage import compile_cpp, mapped, run_cpp
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/ntrip/ntrip_base.cpp').read_text()
loop = source[source.index('int loopNTRIP('):source.index('/** @brief Implements stopNtrip.')]
harness = r'''
#include <array>
#include <cassert>
#include <cstdint>
#include <string>
using String = std::string;
constexpr uint8_t NTRIP_SERVER_COUNT = 2;
constexpr uint32_t RECONNECT_INTERVAL_MS = 5000;
constexpr int NTRIP_MODE = 1;
struct NtripEndpoint {
    bool enabled = true, authenticated = false, stream = true;
    uint32_t lastReconnectMs = 0;
};
struct Client {
    bool up = false;
    bool connected() { return up; }
    void stop() { up = false; }
};
std::array<NtripEndpoint, 2> endpoints;
std::array<Client, 2> clients;
std::array<bool, 2> accept, failWrites;
std::array<int, 2> attempts;
int sends = 0, updates = 0;
bool roverActive = false;
bool workflowActive = false;
struct { bool workflowActive() const { return ::workflowActive; } } backendAgent;
uint32_t now = 5000;
uint32_t millis() { return now; }
bool ntripRoverSessionStarted() { return roverActive; }
NtripEndpoint &endpointFor(uint8_t i) { return endpoints[i]; }
Client &clientFor(uint8_t i) { return clients[i]; }
bool streamActive(uint8_t i) { return endpoints[i].stream; }
void clearEndpointState(NtripEndpoint &e) { e.authenticated = false; }
bool connectEndpoint(uint8_t i) {
    ++attempts[i]; endpoints[i].lastReconnectMs = now;
    clients[i].up = endpoints[i].authenticated = accept[i];
    return accept[i];
}
bool sendEndpointRtcm(NtripEndpoint &endpoint, Client &client, const String &data) {
    ++sends;
    if (failWrites[&endpoint - endpoints.data()]) { client.stop(); endpoint.authenticated=false; return false; }
    return !data.empty();
}
void updateBps(NtripEndpoint &) { ++updates; }
void reset() {
    endpoints = {}; clients = {}; accept = {}; failWrites = {}; attempts = {};
    sends = updates = 0; roverActive = false; now = 5000;
}
'''
checks = r'''
int main() {
    String empty, data = "RTCM";
    reset(); endpoints[1].enabled = false; accept[0] = true;
    assert(loopNTRIP(empty) == NTRIP_MODE); // Reconnect is reported in this same iteration.
    assert(attempts[0] == 1 && attempts[1] == 0 && sends == 0);
    assert(loopNTRIP(data) == NTRIP_MODE + 4 && sends == 1 && updates == 1);
    reset();
    assert(loopNTRIP(empty) == 504 && attempts[0] == 1 && attempts[1] == 1);
    now += 4999;
    assert(loopNTRIP(empty) == 504 && attempts[0] == 1 && attempts[1] == 1);
    ++now; accept[1] = true;
    assert(loopNTRIP(empty) == NTRIP_MODE && attempts[1] == 2);
    reset(); clients[1].up = endpoints[1].authenticated = true;
    assert(loopNTRIP(empty) == NTRIP_MODE && attempts[0] == 1 && attempts[1] == 0);
    endpoints[1].stream = false;
    assert(loopNTRIP(empty) == 504 && !clients[1].up && !endpoints[1].authenticated);
    reset(); clients[0].up = endpoints[0].authenticated = true; endpoints[1].enabled = false; failWrites[0] = true;
    assert(loopNTRIP(data) == 504 && !clients[0].up && !endpoints[0].authenticated);
    reset(); clients[0].up = endpoints[0].authenticated = true; clients[1].up = endpoints[1].authenticated = true; failWrites[0] = true;
    assert(loopNTRIP(data) == NTRIP_MODE + 4 && !clients[0].up && clients[1].up && endpoints[1].authenticated);
    reset(); roverActive = true;
    assert(loopNTRIP(data) == 504 && attempts[0] == 0 && attempts[1] == 0 && sends == 0);
    roverActive = false; workflowActive = true;
    assert(loopNTRIP(data) == 504 && attempts[0] == 0 && attempts[1] == 0 && sends == 0);
}
'''
with tempfile.TemporaryDirectory(prefix='ntrip-reconnect-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + mapped(root / 'src/functions/ntrip/ntrip_base.cpp', loop) + checks)
    compile_cpp(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    run_cpp([str(path / 'check')], check=True)
print('PASS: immediate reconnect status, retry backoff, dual servers, stream gates and Rover exclusion')
