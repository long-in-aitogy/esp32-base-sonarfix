"""Exercise the actual shared handshake with persistent SOURCE and rover sockets."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/ntrip/ntrip_common.cpp').read_text()
function = source[source.index('    bool waitForNtripResponse('):source.index('\n} // namespace ntrip_common')]
shim = (root / 'test/host/Arduino.h').read_text().replace('#pragma once', '')
shim = shim.replace('    void trim()', '''    int indexOf(const char *s) const { auto p = find(s); return p == npos ? -1 : int(p); }
    int indexOf(char c, unsigned start) const { auto p = find(c, start); return p == npos ? -1 : int(p); }
    String substring(unsigned start, unsigned end) const { return substr(start, end - start); }
    void trim()''')
harness = r'''
#include <cassert>
uint32_t now = 0;
uint32_t millis() { return now; }
void delay(uint32_t ms) { now += ms; }
struct Client {
    String wire;
    size_t offset = 0;
    bool connected() { return true; }
    int available() { return offset < wire.size(); }
    int read() { return available() ? uint8_t(wire[offset++]) : -1; }
};
'''
declarations = r'''
bool waitForNtripResponse(Client &, String *, String * = nullptr);
'''
checks = r'''
int main() {
    for (int server = 0; server < 2; ++server) {
        Client source; source.wire = "ICY 200 OK\r\n";
        assert(waitForNtripResponse(source, nullptr));
    }
    assert(now == 0);
    Client rover; rover.wire = "ICY 200 OK\r\n"; rover.wire += char(0xD3);
    assert(waitForNtripResponse(rover, nullptr) && rover.read() == 0xD3);
    Client http; http.wire = "HTTP/1.1 200 OK\r\nServer: caster\r\n\r\n";
    http.wire += char(0xD3);
    assert(waitForNtripResponse(http, nullptr) && http.read() == 0xD3);
    Client customReason; customReason.wire = "HTTP/1.0 200 Success\r\n\r\n";
    assert(waitForNtripResponse(customReason, nullptr));
    Client rejected; rejected.wire = "HTTP/1.1 401 Unauthorized\r\n\r\n";
    assert(!waitForNtripResponse(rejected, nullptr));
    assert(now == 0);
    Client spoofed; spoofed.wire = "HTTP/1.1 401 Unauthorized\r\nX-Diagnostic: HTTP/1.1 200 OK\r\n\r\n";
    assert(!waitForNtripResponse(spoofed, nullptr));
    Client wrongStatus; wrongStatus.wire = "HTTP/1.1 2000 OK\r\n\r\n";
    assert(!waitForNtripResponse(wrongStatus, nullptr));
    Client partial; partial.wire = "HTTP/1.1 200 OK\r\nServer: caster\r\n";
    assert(!waitForNtripResponse(partial, nullptr));
    now = 0;
    Client silent; String error;
    assert(!waitForNtripResponse(silent, &error));
    assert(now == 10000 && !error.isEmpty());
    now = UINT32_MAX - 500;
    Client wraparound;
    assert(!waitForNtripResponse(wraparound, nullptr));
    assert(now == static_cast<uint32_t>(UINT32_MAX - 500U + 10000U));
}
'''
with tempfile.TemporaryDirectory(prefix='ntrip-handshake-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(shim + harness + declarations + function + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: SOURCE ACK, preserved RTCM bytes, HTTP headers, rejection and timeout')
