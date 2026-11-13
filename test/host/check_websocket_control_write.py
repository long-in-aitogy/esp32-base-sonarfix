"""Reject partial WebSocket control frames instead of reusing a damaged stream."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Websocket.cpp').read_text()
method = source[source.index('void BackendAgentWebsocket::sendControl('):]
harness = r'''
#include <Arduino.h>
#include <array>
#include <cassert>
#include <vector>
#define NATIVE_BUILD
long random(long) { return 1234; }
unsigned long micros() { return 5678; }
uint8_t maskByte(uint8_t value, uint8_t mask) { return value ^ mask; }
struct Client {
    int calls = 0, failAt = 0;
    std::vector<uint8_t> bytes;
    size_t write(const uint8_t *data, size_t length) {
        ++calls;
        if (calls == failAt) return 0;
        bytes.insert(bytes.end(), data, data + length);
        return length;
    }
};
struct BackendAgentWebsocket {
    bool connected_ = true;
    Client *client_;
    int disconnects = 0;
    void disconnect(bool) { ++disconnects; connected_ = false; }
    void sendControl(uint8_t, const uint8_t *, size_t);
};
'''
checks = r'''
int main() {
    const uint8_t payload[] = {'p', 'i'};
    for (int failed : {1, 2, 3, 4}) {
        Client client; client.failAt = failed;
        BackendAgentWebsocket socket{true, &client};
        socket.sendControl(9, payload, sizeof(payload));
        assert(socket.disconnects == 1 && !socket.connected_ && client.calls == failed);
    }
    Client client;
    BackendAgentWebsocket socket{true, &client};
    socket.sendControl(9, payload, sizeof(payload));
    assert(socket.connected_ && socket.disconnects == 0 && client.bytes.size() == 8);
    assert(client.bytes[0] == 0x89 && client.bytes[1] == 0x82);
    assert((client.bytes[6] ^ client.bytes[2]) == 'p');
    assert((client.bytes[7] ^ client.bytes[3]) == 'i');
    socket.sendControl(9, nullptr, 2);
    assert(client.calls == 4 && socket.connected_);
}
'''
with tempfile.TemporaryDirectory(prefix='esp-websocket-control-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + method + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined', '-I' + str(root / 'test/host'), str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: partial control frames disconnect; valid masked ping stays connected')
