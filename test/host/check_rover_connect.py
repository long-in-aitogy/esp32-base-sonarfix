"""Check Rover connection errors and workflow transport-lock handling."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
rover = (root / 'src/functions/ntrip/ntrip_rover.cpp').read_text()
start = rover[rover.index('bool startNtripRover('):rover.index('/** @brief Implements loopNtripRover.')]
common = (root / 'src/functions/ntrip/ntrip_common.cpp').read_text()
wait = common[common.index('    bool waitForNtripResponse('):common.index('\n} // namespace ntrip_common')]
shim = (root / 'test/host/Arduino.h').read_text().replace('#pragma once', '')
shim = shim.replace('    void trim()', '''    bool startsWith(const String &value) const { return compare(0, value.size(), value) == 0; }
    void remove(unsigned start, unsigned count) { erase(start, count); }
    int indexOf(const char *s) const { auto p = find(s); return p == npos ? -1 : int(p); }
    String substring(unsigned start, unsigned end) const { return substr(start, end - start); }
    void trim()''').replace('    void println(const char *) {}', '    void println(const char *) {}\n    void println(const String &) {}')
harness = r'''
#include <array>
#include <cassert>
uint32_t now = 0;
uint32_t millis() { return now; }
void delay(uint32_t ms) { now += ms; }
const char *AGENT_VERSION = "test";
struct RoverSession {
    bool active = false, authenticated = false;
    uint32_t bytesReceived = 0, packetsReceived = 0, lastGgaMs = 0;
    const char *lastError = "old error";
} session;
RoverSession &roverSession() { return session; }
struct Client {
    String reply, request;
    size_t offset = 0;
    bool up = false, connectOk = true;
    int connects = 0;
    void stop() { up = false; }
    void setTimeout(int) {}
    bool connect(const char *, uint16_t) { ++connects; up = connectOk; return up; }
    bool connected() { return up; }
    int available() { return offset < reply.size(); }
    int read() { return available() ? static_cast<unsigned char>(reply[offset++]) : -1; }
    size_t print(const String &s) { request = s; return s.size(); }
} client;
Client &clientFor(int) { return client; }
bool safeNtripField(const String &s) { return s.find_first_of("\r\n") == String::npos; }
String base64Encode(const String &) { return "encoded"; }
void sendRoverGgaIfAvailable(Client &, bool) {}
'''
checks = r'''
int main() {
    for (const char *reason : {"ERROR - NO STATION WITHIN 20 KM", "ERROR - FIXED STATION IN RANGE UNAVAILABLE",
                               "ERROR - FIXED STATION CATALOG UNAVAILABLE", "ERROR - AUTONEAREST NOT ENABLED"}) {
        client = Client{}; client.reply = String(reason) + "\r\n\r\n";
        assert(!startNtripRover("host", 2101, "user", "secret", "/mount", 1));
        assert(String(session.lastError) == reason && !session.active && !session.authenticated);
    }
    client = Client{}; client.reply = "HTTP/1.1 401 secret\r\n\r\n";
    assert(!startNtripRover("host", 2101, "user", "secret", "mount", 2));
    assert(String(session.lastError) == "cannot connect to CORS rover mountpoint");
    client = Client{}; client.connectOk = false;
    assert(!startNtripRover("host", 2101, "user", "secret", "mount", 1));
    assert(String(session.lastError) == "cannot connect to CORS rover mountpoint");
    client = Client{};
    assert(!startNtripRover("host\r\nInjected", 2101, "user", "secret", "mount", 1));
    assert(client.connects == 0 && String(session.lastError) == "cannot connect to CORS rover mountpoint");
    client = Client{}; client.reply = "ICY 200 OK\r\n";
    assert(startNtripRover("host", 2101, "user", "secret", "mount", 1));
    assert(session.active && session.authenticated && String(session.lastError) == "CORS rover connection lost");
}
'''
with tempfile.TemporaryDirectory(prefix='rover-connect-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(shim + harness + wait + start + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: allowlisted caster errors, sanitized fallback, invalid input and successful Rover connection')

workflow = (root / 'src/functions/backend/Backend_Agent_Workflows.cpp').read_text()
methods = []
for name in ('startAutoBaseRover', 'startReferenceRover'):
    begin = workflow.index('bool BackendAgent::' + name + '(')
    end = workflow.index('\nbool BackendAgent::', begin + 5)
    methods.append(workflow[begin:end])
wrapper_harness = r'''
#include <cassert>
constexpr int MUTEX_TIMEOUT_MS = 1500, pdTRUE = 1;
int tcpStreamMutex = 1, releases = 0, stops = 0;
bool lockOk = true, startOk = true;
int pdMS_TO_TICKS(int ms) { return ms; }
int xSemaphoreTake(int, int) { return lockOk; }
void xSemaphoreGive(int) { ++releases; }
void stopNtrip() { ++stops; }
bool startNtripRover(const String &, uint16_t, const String &, const String &, const String &, uint8_t) { return startOk; }
const char *ntripRoverLastError() { return "ERROR - NO STATION WITHIN 20 KM"; }
struct BackendAgent {
    bool startAutoBaseRover(const String &, uint16_t, const String &, const String &, const String &, uint8_t, String &);
    bool startReferenceRover(const String &, uint16_t, const String &, const String &, const String &, String &);
};
'''
wrapper_checks = r'''
int main() {
    BackendAgent agent; String error;
    lockOk = false;
    assert(!agent.startAutoBaseRover("host", 2101, "user", "password", "mount", 1, error));
    assert(error == "network transport is busy" && releases == 0 && stops == 0);
    assert(!agent.startReferenceRover("host", 2101, "user", "password", "mount", error));
    assert(error == "network transport is busy" && releases == 0 && stops == 0);
    lockOk = true; startOk = false;
    assert(!agent.startAutoBaseRover("host", 2101, "user", "password", "mount", 1, error));
    assert(error == "ERROR - NO STATION WITHIN 20 KM" && releases == 1 && stops == 1);
    assert(!agent.startReferenceRover("host", 2101, "user", "password", "mount", error));
    assert(error == "ERROR - NO STATION WITHIN 20 KM" && releases == 2 && stops == 2);
    startOk = true;
    assert(agent.startAutoBaseRover("host", 2101, "user", "password", "mount", 1, error));
    assert(releases == 3 && stops == 3);
}
'''
with tempfile.TemporaryDirectory(prefix='rover-connect-wrapper-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(shim + wrapper_harness + '\n'.join(methods) + wrapper_checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: workflow distinguishes busy transport from caster errors and releases mutex')
