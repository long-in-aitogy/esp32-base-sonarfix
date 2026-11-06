"""Run the real source loop with reconnect outcomes and validate transition-only logs."""
from pathlib import Path
import subprocess
import tempfile
from host_coverage import compile_cpp, run_cpp, cpp_output, mapped

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/ntrip/NTRIP_Handler_IP.cpp').read_text()
loop = 'int loopNTRIP(String &rtcmData) {' + source.split('int loopNTRIP(String &rtcmData) {', 1)[1].split('\nvoid stopNtrip()', 1)[0]
shim = (root / 'test/host/Arduino.h').read_text().replace('#pragma once', '')
shim = shim.replace('    void trim() {', '''    String(unsigned long value, int) { char text[24]; snprintf(text, sizeof(text), "%lx", value); assign(text); }
    void trim() {''')
main = (root / 'src/main.cpp').read_text()
logging = main.split('            #if PROGRAM_DEBUG\n', 1)[1].split('            #endif', 1)[0]
shim = shim.replace('struct HostSerial {', 'struct HostSerial { unsigned events = 0;')
shim = shim.replace('void printf(const char *, Args...) {}', 'void printf(const char *, Args...) { ++events; }')
harness = r'''
#include <cassert>
constexpr int NTRIP_MODE = 1, HEX = 16;
constexpr unsigned NTRIP_SERVER_COUNT = 2, RECONNECT_INTERVAL_MS = 5000;
unsigned now = 10000;
unsigned millis() { return now; }
bool roverSessionActive = false;
struct { bool active = false; bool workflowActive() { return active; } } backendAgent;
struct NtripEndpoint {
    bool enabled = false, authenticated = false, active = true;
    unsigned lastReconnectMs = 0, lastKeepAliveMs = 0, bytesInWindow = 0;
    unsigned version = 1;
} endpoints[2];
struct Client {
    bool up = false, accept = false;
    unsigned attempts = 0, writes = 0;
    String wire;
    bool connected() { return up; }
    void stop() { up = false; }
    void print(const String &text) { wire += text; }
    size_t write(const uint8_t *data, size_t length) { ++writes; wire.append((const char*)data, length); return length; }
} clients[2];
Client &clientFor(unsigned i) { return clients[i]; }
bool streamActive(unsigned i) { return endpoints[i].active; }
void clearEndpointState(NtripEndpoint &endpoint) { endpoint.authenticated = false; }
void updateBps(NtripEndpoint &) {}
bool connectEndpoint(unsigned i) {
    ++clients[i].attempts; endpoints[i].lastReconnectMs = now;
    return clients[i].up = endpoints[i].authenticated = clients[i].accept;
}
void reset() { for (unsigned i = 0; i < 2; ++i) { endpoints[i] = {}; clients[i] = {}; } }
'''
checks = r'''
int main() {
    String payload = "abc", empty;
    reset(); endpoints[0].enabled = true; clients[0].accept = true;
    assert(loopNTRIP(empty) == 1); // Successful reconnect must never report 504.
    assert(clients[0].attempts == 1 && clients[0].writes == 0);
    assert(loopNTRIP(payload) == 5 && clients[0].wire == "abc");
    assert(loopNTRIP(empty) == 1);
    reset(); endpoints[0].enabled = true;
    assert(loopNTRIP(payload) == 504 && clients[0].attempts == 1);
    assert(loopNTRIP(payload) == 504 && clients[0].attempts == 1); // Backoff retained.
    endpoints[1].enabled = endpoints[1].authenticated = clients[1].up = true;
    assert(loopNTRIP(payload) == 5 && clients[1].wire == "abc");
    reset(); endpoints[0].enabled = true; endpoints[0].active = false;
    assert(loopNTRIP(payload) == 504 && clients[0].attempts == 0);
    reset(); endpoints[0].enabled = endpoints[0].authenticated = clients[0].up = true;
    endpoints[0].version = 2;
    assert(loopNTRIP(payload) == 5 && clients[0].wire == "3\r\nabc\r\n");
    roverSessionActive = true;
    assert(loopNTRIP(payload) == 504);
    roverSessionActive = false; backendAgent.active = true;
    assert(loopNTRIP(payload) == 504);
}
'''
loop = mapped(root / 'src/functions/ntrip/NTRIP_Handler_IP.cpp', loop)
with tempfile.TemporaryDirectory(prefix='esp-ntrip-reconnect-') as directory:
    path = Path(directory)
    log_check = 'void checkLogs() { bool ntripStatusLogged = false, ntripWasConnected = false; for (int loopStatus : {1, 5, 1, 504, 504, 1, 5}) {\n' + logging + '\n} assert(Serial.events == 3); }\n'
    checks = checks.replace('int main() {', 'int main() { checkLogs();')
    (path / 'check.cpp').write_text(shim + harness + loop + log_check + checks)
    compile_cpp(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    run_cpp([str(path / 'check')], check=True)
print('PASS: reconnect status, retry backoff, two endpoints, disabled streams, Rover exclusion v2 framing and transition-only logs')
