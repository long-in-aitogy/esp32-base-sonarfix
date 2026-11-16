"""Check Rover connection errors and workflow transport-lock handling."""
from pathlib import Path
import subprocess
import tempfile
from host_coverage import compile_cpp, mapped, run_cpp
root = Path(__file__).resolve().parents[2]
rover = (root / 'src/functions/ntrip/ntrip_rover.cpp').read_text()
start = rover[rover.index('String buildNtripRoverRequest('):rover.index('/** @brief Implements loopNtripRover.')]
common = (root / 'src/functions/ntrip/ntrip_common.cpp').read_text()
wait = common[common.index('    void readNtripResponse('):common.index('\n} // namespace ntrip_common')]
shim = (root / 'test/host/Arduino.h').read_text().replace('#pragma once', '')
shim = shim.replace('    void trim()', '''    bool startsWith(const String &value) const { return compare(0, value.size(), value) == 0; }
    void remove(unsigned start, unsigned count) { erase(start, count); }
    void remove(unsigned start) { erase(start); }
    int indexOf(const char *s) const { auto p = find(s); return p == npos ? -1 : int(p); }
    int indexOf(char c, unsigned start) const { auto p = find(c, start); return p == npos ? -1 : int(p); }
    String substring(unsigned start, unsigned end) const { return substr(start, end - start); }
    void trim()''').replace('    void println(const char *) {}', '    void println(const char *) {}\n    void println(const String &) {}')
harness = r'''
#include <array>
#include <cassert>
uint32_t now = 0;
uint32_t millis() { return now; }
void delay(uint32_t ms) { now += ms; }
const char *AGENT_VERSION = "test";
struct GnssTelemetrySnapshot { std::array<char, 128> lastGga{}; uint32_t lastGgaMs = 0; } snapshot;
GnssTelemetrySnapshot getGnssTelemetrySnapshot() { return snapshot; }
struct NtripRoverOptions {
    uint8_t version = 1;
    String *selectedMountpoint = nullptr;
    String receiverId;
};
struct RoverSession {
    struct Datum { int resets = 0; void reset() { ++resets; } } datum;
    bool active = false, authenticated = false;
    uint32_t bytesReceived = 0, bytesWritten = 0, packetsReceived = 0, lastGgaMs = 0, lastDiagnosticMs = 0;
    const char *lastError = "old error";
} session;
RoverSession &roverSession() { return session; }
struct Client {
    String reply, request;
    size_t offset = 0;
    bool up = false, connectOk = true, shortWrite = false;
    int connects = 0;
    void stop() { up = false; }
    void setTimeout(int) {}
    bool connect(const char *, uint16_t) { ++connects; up = connectOk; return up; }
    bool connected() { return up; }
    int available() { return offset < reply.size(); }
    int read() { return available() ? static_cast<unsigned char>(reply[offset++]) : -1; }
    size_t print(const String &s) { request = s; return shortWrite ? s.size() - 1 : s.size(); }
} client;
Client &clientFor(int) { return client; }
bool safeNtripField(const String &s) { return s.find_first_of("\r\n") == String::npos; }
String base64Encode(const String &) { return "encoded"; }
void sendRoverGgaIfAvailable(Client &, bool) {}
'''
declarations = r'''
bool waitForNtripResponse(Client &, String *, String * = nullptr);
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
    client = Client{}; client.reply = "ICY 200 OK\r\n"; client.shortWrite = true;
    assert(!startNtripRover("host", 2101, "user", "secret", "mount", 1));
    assert(!client.up && !session.active && !session.authenticated && String(session.lastError) == "incomplete NTRIP request write");
    client = Client{}; client.connectOk = false;
    assert(!startNtripRover("host", 2101, "user", "secret", "mount", 1));
    assert(String(session.lastError) == "cannot connect to CORS rover mountpoint");
    client = Client{};
    assert(!startNtripRover("host\r\nInjected", 2101, "user", "secret", "mount", 1));
    assert(client.connects == 0 && String(session.lastError) == "cannot connect to CORS rover mountpoint");
    client = Client{}; client.reply = "ICY 200 OK\r\n";
    assert(startNtripRover("host", 2101, "user", "secret", "mount", 1));
    assert(session.active && session.authenticated && String(session.lastError) == "CORS rover connection lost");
    assert(session.datum.resets > 0);
    String selected = "old";
    client = Client{}; client.reply = "HTTP/1.1 200 OK\r\nX-NTRIP-Selected-Mountpoint:  STATION1  \r\n\r\n";
    client.reply += char(0xD3);
    assert(startNtripRover("host", 2101, "user", "secret", "AutoNearest", 2, &selected, "receiver"));
    assert(selected == "STATION1" && client.read() == 0xD3);
    assert(client.request.find("X-NTRIP-Report-Selected: 1\r\n") != String::npos);
    assert(client.request.find("User-Agent: NTRIP ESP32-Agent/test/receiver\r\n") != String::npos);
    client = Client{}; client.reply = "ICY 200 OK\r\n";
    assert(!startNtripRover("host", 2101, "user", "secret", "AutoNearest", 1, &selected));
    assert(selected.isEmpty() && !client.up && !session.active);
    assert(String(session.lastError) == "Caster did not confirm the selected mountpoint");
    client = Client{};
    assert(!startNtripRover("host", 2101, "user", "secret", "mount", 1, &selected, "bad\r\nheader"));
    assert(client.connects == 0 && selected.isEmpty());
    for (uint8_t version : {1, 2}) {
        client = Client{}; client.reply = "ICY 200 OK\r\n"; now = 10000;
        std::snprintf(snapshot.lastGga.data(), snapshot.lastGga.size(), "%s", "$GNGGA,valid*00\r\n");
        snapshot.lastGgaMs = 7000;
        assert(startNtripRover("host", 2101, "user", "secret", "mount", version));
        assert(client.request.find("Ntrip-GGA: $GNGGA,valid*00\r\n\r\n") != String::npos);
        client = Client{}; client.reply = "ICY 200 OK\r\n"; snapshot.lastGgaMs = 6999;
        assert(startNtripRover("host", 2101, "user", "secret", "mount", version));
        assert(client.request.find("Ntrip-GGA:") == String::npos); // Stale GGA.
        client = Client{}; client.reply = "ICY 200 OK\r\n"; snapshot.lastGgaMs = 10000;
        std::snprintf(snapshot.lastGga.data(), snapshot.lastGga.size(), "%s", "$GNGGA,valid\r\nInjected: value");
        assert(startNtripRover("host", 2101, "user", "secret", "mount", version));
        assert(client.request.find("Ntrip-GGA:") == String::npos && client.request.find("Injected:") == String::npos);
        client = Client{}; client.reply = "ICY 200 OK\r\n"; snapshot.lastGgaMs = 0;
        assert(startNtripRover("host", 2101, "user", "secret", "mount", version));
        assert(client.request.find("Ntrip-GGA:") == String::npos);
        client = Client{}; client.reply = "ICY 200 OK\r\n";
        std::snprintf(snapshot.lastGga.data(), snapshot.lastGga.size(), "%s", "$GNGGA,valid*00");
        now = 500; snapshot.lastGgaMs = UINT32_MAX - 999;
        assert(startNtripRover("host", 2101, "user", "secret", "mount", version));
        assert(client.request.find("Ntrip-GGA: $GNGGA,valid*00\r\n") != String::npos);
    }
}
'''
with tempfile.TemporaryDirectory(prefix='rover-connect-') as directory:
    path = Path(directory)
    prototype = 'bool startNtripRover(const String &, uint16_t, const String &, const String &, String, const NtripRoverOptions &);\n'
    compatibility = r'''
bool startNtripRover(const String &host, uint16_t port, const String &username,
                     const String &password, const String &mountpoint, uint8_t version,
                     String *selection = nullptr, const String &receiver = String()) {
    return startNtripRover(host, port, username, password, mountpoint,
                           NtripRoverOptions{version, selection, receiver});
}
'''
    (path / 'check.cpp').write_text(shim + harness + declarations + prototype + mapped(root / 'src/functions/ntrip/ntrip_common.cpp', wait) + mapped(root / 'src/functions/ntrip/ntrip_rover.cpp', start) + compatibility + checks)
    compile_cpp(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    run_cpp([str(path / 'check')], check=True)
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
String passedReceiver;
String *passedSelection = nullptr;
struct NtripRoverOptions { uint8_t version = 1; String *selectedMountpoint = nullptr; String receiverId; };
bool startNtripRover(const String &, uint16_t, const String &, const String &, const String &, const NtripRoverOptions &options) {
    passedSelection = options.selectedMountpoint; passedReceiver = options.receiverId;
    if (options.selectedMountpoint && startOk) *options.selectedMountpoint = "station";
    return startOk;
}
const char *ntripRoverLastError() { return "ERROR - NO STATION WITHIN 20 KM"; }
struct BackendAgent {
    String serialNumber_ = "esp-test";
    bool startAutoBaseRover(const String &, uint16_t, const String &, const String &, const String &, uint8_t, String &, String * = nullptr);
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
    assert(releases == 3 && stops == 3 && passedSelection == nullptr && passedReceiver.isEmpty());
    String selected;
    assert(agent.startAutoBaseRover("host", 2101, "user", "password", "nearest", 1, error, &selected));
    assert(selected == "station" && passedSelection == &selected && passedReceiver == "esp-test");
}
'''
with tempfile.TemporaryDirectory(prefix='rover-connect-wrapper-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(shim + wrapper_harness + ''.join(mapped(root / 'src/functions/backend/Backend_Agent_Workflows.cpp', method) for method in methods) + wrapper_checks)
    compile_cpp(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    run_cpp([str(path / 'check')], check=True)
print('PASS: workflow distinguishes busy transport from caster errors and releases mutex')
