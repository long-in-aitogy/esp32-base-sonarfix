"""A persistent SOURCE ACK must not hold the transport lock for 10 seconds."""
from pathlib import Path
from host_coverage import compile_cpp, run_cpp, mapped
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/ntrip/NTRIP_Handler_IP.cpp').read_text()
handshake = 'bool waitForNtripResponse(' + source.split('bool waitForNtripResponse(', 1)[1].split('\nvoid sendRoverGgaIfAvailable', 1)[0]
shim = (root / 'test/host/Arduino.h').read_text().replace('#pragma once', '')
shim = shim.replace('    void trim() {', '''    int indexOf(const char *s) const { auto p = find(s); return p == npos ? -1 : int(p); }
    int indexOf(char c, int start) const { auto p = find(c, start); return p == npos ? -1 : int(p); }
    void trim() {''')
harness = r'''
#include <cassert>
uint32_t now = 0;
uint32_t millis() { return now; }
void delay(uint32_t ms) { now += ms; }
struct Client {
    String wire;
    size_t offset = 0;
    bool up = true;
    bool connected() { return up; }
    int available() { return offset < wire.size(); }
    int read() { return available() ? uint8_t(wire[offset++]) : -1; }
};
'''
checks = r'''
int main() {
    for (int server = 0; server < 2; ++server) {
        Client source; source.wire = "ICY 200 OK\r\n";
        assert(waitForNtripResponse(source));
    }
    assert(now == 0); // Both open SOURCE sockets ACK immediately, without blocking MQTT.
    Client rover; rover.wire = "ICY 200 OK\r\n"; rover.wire += char(0xD3);
    assert(waitForNtripResponse(rover));
    assert(rover.read() == 0xD3);
    Client http; String selected;
    http.wire = "HTTP/1.1 200 OK\r\nX-NTRIP-Selected-Mountpoint: station\r\n\r\n";
    http.wire += char(0xD3);
    assert(waitForNtripResponse(http, nullptr, &selected));
    assert(selected == "station" && http.read() == 0xD3);
    Client rejected; rejected.wire = "HTTP/1.1 401 Unauthorized\r\n\r\n";
    assert(!waitForNtripResponse(rejected));
    assert(now == 0);
    Client silent; String error;
    assert(!waitForNtripResponse(silent, &error));
    assert(now == 10000 && !error.isEmpty());
}
'''
with tempfile.TemporaryDirectory(prefix='esp-ntrip-handshake-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(shim + harness + mapped(root / 'src/functions/ntrip/NTRIP_Handler_IP.cpp', handshake) + checks)
    compile_cpp(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    run_cpp([str(path / 'check')], check=True)
print('PASS: two immediate SOURCE ACKs, rover bytes, HTTP mountpoint header, rejection and timeout')
