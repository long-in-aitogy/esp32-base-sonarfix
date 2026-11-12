"""A 504-byte correction read must not collide with the Rover disconnect status."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/ntrip/ntrip_rover.cpp').read_text()
loop = source[source.index('int loopNtripRover()'):source.index('/** @brief Implements stopNtripRover.')]
harness = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <vector>
#include <string>
using std::min;
struct Session {
    struct Datum { std::vector<uint8_t> received; void feed(const uint8_t *data, size_t n) { received.insert(received.end(), data, data + n); } } datum;
    bool active = true, authenticated = true;
    uint32_t bytesReceived = 0, packetsReceived = 0;
    const char *lastError = "CORS rover connection lost";
} session;
Session &roverSession() { return session; }
struct Client {
    bool connected_ = true;
    std::vector<uint8_t> input;
    bool connected() { return connected_; }
    int available() { return input.size(); }
    int read(uint8_t *data, size_t size) {
        size = min(size, input.size());
        std::copy_n(input.begin(), size, data);
        input.erase(input.begin(), input.begin() + size);
        return size;
    }
} client;
Client &clientFor(int) { return client; }
void sendRoverGgaIfAvailable(Client &) {}
struct {
    std::vector<uint8_t> output;
    bool shortWrite = false;
    size_t write(const uint8_t *data, size_t size) {
        const size_t written = shortWrite ? size / 2 : size;
        output.insert(output.end(), data, data + written);
        return written;
    }
} Serial1;
struct Logger { template <typename... T> void printf(const char *, T...) {} };
[[maybe_unused]] Logger Serial;
constexpr int MUTEX_TIMEOUT_MS = 1500, pdTRUE = 1;
int rtcmBufferMutex = 1, releases = 0;
bool lockAvailable = true;
int pdMS_TO_TICKS(int ms) { return ms; }
int xSemaphoreTake(int, int) { return lockAvailable; }
void xSemaphoreGive(int) { ++releases; }
'''
checks = r'''
int main() {
    for (const size_t size : {504U, 1U, 200U, 512U}) {
        client.input.assign(size, 0xD3);
        Serial1.output.clear();
        const auto received = session.bytesReceived, packets = session.packetsReceived;
        assert(loopNtripRover() == 200);
        assert(Serial1.output == std::vector<uint8_t>(size, 0xD3));
        assert(session.bytesReceived == received + size && session.packetsReceived == packets + 1);
    }
    assert(session.datum.received == std::vector<uint8_t>(504 + 1 + 200 + 512, 0xD3));
    assert(loopNtripRover() == 200 && releases == 4);
    client.input.assign(504, 0xD3); lockAvailable = false;
    assert(loopNtripRover() == 200 && client.input.size() == 504 && releases == 4);
    lockAvailable = true;
    Serial1.shortWrite = true;
    assert(loopNtripRover() == 504 && releases == 5);
    assert(std::string(session.lastError) == "GNSS UART did not accept all CORS bytes");
    assert(session.bytesReceived == 504 + 1 + 200 + 512 + 504 && session.packetsReceived == 5);
    client.connected_ = false;
    assert(loopNtripRover() == 504 && !session.active && !session.authenticated);
    assert(loopNtripRover() == 504 && releases == 5);
}
'''
with tempfile.TemporaryDirectory(prefix='rover-status-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + loop + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: Rover status, 504-byte read, counters, UART delivery, busy mutex and disconnect')
