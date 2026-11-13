"""Exercise the actual WebSocket connect path with a deterministic client and crypto boundary."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Websocket.cpp').read_text()
connect = source[source.index('void BackendAgentWebsocket::connectNow()'):source.index('bool BackendAgentWebsocket::readFrame(')]
harness = r'''
#include <Arduino.h>
#include <array>
#include <cassert>
#include <cstring>
#include <string>
#include "functions/backend/Websocket_Protocol.h"
uint32_t now = 0;
uint32_t millis() { return now; }
void delay(uint32_t ms) { now += ms; }
String websocketNonce() { return "dGhlIHNhbXBsZSBub25jZQ=="; }
bool cryptoOk = true;
int mbedtls_sha1_ret(const unsigned char *input, size_t length, unsigned char *output) {
    assert(std::string(reinterpret_cast<const char *>(input), length) == "dGhlIHNhbXBsZSBub25jZQ==258EAFA5-E914-47DA-95CA-C5AB0DC85B11");
    std::memset(output, 0, 20); return cryptoOk ? 0 : -1;
}
int mbedtls_base64_encode(unsigned char *out, size_t cap, size_t *length, const unsigned char *, size_t digestLength) {
    const std::string accept = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=";
    assert(cap >= accept.size() && digestLength == 20);
    std::memcpy(out, accept.data(), accept.size()); *length = accept.size(); return 0;
}
struct Client {
    String input, request;
    size_t offset = 0;
    unsigned stops = 0;
    void stop() { ++stops; }
    void setTimeout(int) {}
    bool connect(const char *, uint16_t) { return true; }
    size_t print(const String &value) { request = value; return value.length(); }
    int available() { return offset < input.size(); }
    int read() { return available() ? static_cast<unsigned char>(input[offset++]) : -1; }
};
struct BackendAgent {
    bool websocketConnected_ = false;
    int publishes = 0;
    void publishStatus(bool) { ++publishes; }
};
struct BackendAgentWebsocket {
    Client *client_;
    BackendAgent *owner_;
    String host_ = "caster.example", path_ = "/socket";
    uint16_t port_ = 8000;
    uint32_t nextAttemptMs_ = 0, lastPingMs_ = 0;
    bool connected_ = false;
    void connectNow();
};
'''
checks = r'''
int main() {
    const String response = "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n";
    Client good; good.input = response + "X";
    BackendAgent owner;
    BackendAgentWebsocket ws{&good, &owner};
    ws.connectNow();
    assert(ws.connected_ && owner.websocketConnected_ && owner.publishes == 1);
    assert(good.read() == 'X'); // Keep the first frame byte after HTTP headers.
    assert(good.request.find("Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n") != String::npos);
    Client bad; bad.input = "HTTP/1.1 101 Switching Protocols\r\n\r\n";
    BackendAgent other; BackendAgentWebsocket rejected{&bad, &other};
    rejected.connectNow(); assert(!rejected.connected_ && bad.stops == 2 && other.publishes == 0);
    Client crypto; crypto.input = response; BackendAgentWebsocket failed{&crypto, &other};
    cryptoOk = false; failed.connectNow(); assert(!failed.connected_ && crypto.stops == 2); cryptoOk = true;
    Client incomplete; incomplete.input = "HTTP/1.1 101 Switching Protocols\r\n";
    BackendAgentWebsocket timedOut{&incomplete, &other}; now = 0xFFFFFF00U;
    const uint32_t started = now; timedOut.connectNow();
    assert(!timedOut.connected_ && uint32_t(now - started) == 5000 && incomplete.stops == 2);
}
'''
with tempfile.TemporaryDirectory(prefix='websocket-upgrade-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + connect + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'), '-I' + str(root / 'include'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: handshake validation, challenge input, first frame, crypto failure and timer rollover')
