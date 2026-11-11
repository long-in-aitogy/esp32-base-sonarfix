"""Run the real WebSocket frame reader with fragmented and hostile wire input.

An optional firmware source root allows running the same checks before a refactor.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
source_root = Path(sys.argv[1]) if len(sys.argv) > 1 else root
source = next((source_root / 'src/functions').rglob('Backend_Agent_Websocket.cpp')).read_text()
start = source.index('bool BackendAgentWebsocket::readFrame(') if 'bool BackendAgentWebsocket::readFrame(' in source else source.index('void BackendAgentWebsocket::parseFrames(')
source = source[start:source.index('\nvoid BackendAgentWebsocket::sendControl', start)]
shim = (root / 'test/host/Arduino.h').read_text().replace('#pragma once', '')
harness = r'''
#include <cassert>
#include <cstddef>
#include <vector>
struct Owner {
    std::vector<String> messages;
    void handleWebsocketText(const String &message) { messages.push_back(message); }
};
struct BackendAgentWebsocket {
    Owner owner;
    Owner *owner_ = &owner;
    bool connected_ = true;
    std::vector<uint8_t> rx_, controls;
    bool readFrame(uint8_t &, String &);
    void parseFrames();
    void disconnect(bool) { connected_ = false; rx_.clear(); }
    void sendControl(uint8_t opcode, const uint8_t *, size_t) { controls.push_back(opcode); }
};
std::vector<uint8_t> frame(uint8_t first, const String &payload) {
    std::vector<uint8_t> out{first};
    if (payload.size() < 126) out.push_back(uint8_t(payload.size()));
    else { out.push_back(126); out.push_back(uint8_t(payload.size() >> 8)); out.push_back(uint8_t(payload.size())); }
    out.insert(out.end(), payload.begin(), payload.end());
    return out;
}
'''
checks = r'''
int main() {
    for (size_t length : {size_t(0), size_t(1), size_t(125), size_t(126), size_t(1024), size_t(32768)}) {
        BackendAgentWebsocket ws;
        const String message(length, 'x');
        const auto bytes = frame(0x81, message);
        for (size_t i = 0; i < bytes.size(); ++i) {
            ws.rx_.push_back(bytes[i]); ws.parseFrames();
            assert(ws.connected_);
            assert(ws.owner.messages.size() == (i + 1 == bytes.size() ? 1 : 0));
        }
        assert(ws.owner.messages[0] == message && ws.rx_.empty());
        if (length > 4096) assert(ws.rx_.capacity() == 0); // Release large idle buffers.
    }
    BackendAgentWebsocket pending;
    pending.rx_.reserve(8192);
    const auto firstFrame = frame(0x81, "first");
    pending.rx_.insert(pending.rx_.end(), firstFrame.begin(), firstFrame.end());
    pending.rx_.push_back(0x81); // First byte of the next frame.
    pending.parseFrames();
    assert(pending.rx_.size() == 1 && pending.rx_.capacity() >= 8192);
    pending.rx_.push_back(1); pending.rx_.push_back('x');
    pending.parseFrames();
    assert(pending.rx_.empty() && pending.rx_.capacity() == 0 && pending.owner.messages.size() == 2);
    for (const auto &bad : std::vector<std::vector<uint8_t>>{
            {0x81, 0x80}, {0x01, 0}, {0xC1, 0}, {0x80, 0}, {0x83, 0},
            {0x89, 126, 0, 126}, {0x88, 1}, {0x81, 126, 0, 125},
            {0x81, 127, 0, 0, 0, 0, 0, 0, 0, 126}, {0x81, 126, 0x80, 1}}) {
        BackendAgentWebsocket ws; ws.rx_ = bad; ws.parseFrames();
        assert(!ws.connected_ && ws.owner.messages.empty());
    }
    BackendAgentWebsocket ws;
    for (const auto &bytes : {frame(0x81, "first"), frame(0x89, "ping"), frame(0x82, "binary"), frame(0x81, "second"), frame(0x88, "")})
        ws.rx_.insert(ws.rx_.end(), bytes.begin(), bytes.end());
    ws.parseFrames();
    assert((ws.owner.messages == std::vector<String>{"first", "second"}));
    assert((ws.controls == std::vector<uint8_t>{0xA, 0x8}));
    assert(!ws.connected_);
}
'''
with tempfile.TemporaryDirectory(prefix='esp-websocket-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(shim + harness + source + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: WebSocket parser; partial/coalesced frames, payload limits, invalid headers, ping/close and command delivery')

# Exercise the actual receive loop too: its buffer cap applies to frame headers as well.
full_source = (root / 'src/functions/backend/Backend_Agent_Websocket.cpp').read_text()
loop = full_source[full_source.index('void BackendAgentWebsocket::loop()'):full_source.index('bool BackendAgentWebsocket::connected()')]
loop_harness = r"""
#include <cassert>
#include <cstddef>
#include <array>
#include <vector>
#include <algorithm>
uint32_t millis() { return 0; }
struct Client {
    std::vector<uint8_t> input;
    bool up = true;
    bool connected() { return up; }
    int available() { return input.size(); }
    int read(uint8_t *buffer, size_t size) {
        size = std::min(size, input.size());
        std::copy_n(input.begin(), size, buffer);
        input.erase(input.begin(), input.begin() + size);
        return size;
    }
};
struct Owner {
    std::vector<String> messages;
    void handleWebsocketText(const String &message) { messages.push_back(message); }
};
struct BackendAgentWebsocket {
    Client client;
    Client *client_ = &client;
    Owner owner;
    Owner *owner_ = &owner;
    bool connected_ = true;
    uint32_t nextAttemptMs_ = 0, lastPingMs_ = 0;
    std::vector<uint8_t> rx_;
    void loop();
    bool readFrame(uint8_t &, String &);
    void parseFrames();
    void connectNow() {}
    void disconnect(bool) { connected_ = false; rx_.clear(); }
    void sendControl(uint8_t, const uint8_t *, size_t) {}
};
"""
loop_checks = r"""
int main() {
    BackendAgentWebsocket ws;
    ws.client.input = {0x81, 5, 'h', 'e'};
    ws.loop(); assert(ws.connected_ && ws.owner.messages.empty());
    ws.client.input = {'l', 'l', 'o'};
    ws.loop(); assert(ws.connected_ && ws.owner.messages.size() == 1 && ws.owner.messages[0] == "hello");
    ws.client.input = {0x01, 1, 'x'}; // Fragmented text is rejected, never dispatched.
    ws.loop(); assert(!ws.connected_ && ws.owner.messages.size() == 1);
    BackendAgentWebsocket full;
    full.client.input = {0x81, 126, 0x80, 0x00};
    full.client.input.resize(32772, 'x');
    full.loop(); assert(!full.connected_ && full.owner.messages.empty());
}
"""
with tempfile.TemporaryDirectory(prefix='esp-websocket-loop-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(shim + loop_harness + loop + source + loop_checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: actual receive loop handles split data, rejects fragmentation and bounds total buffering')

# Verify disconnect frees its buffer while preserving reconnect scheduling.
disconnect = full_source[full_source.index('void BackendAgentWebsocket::disconnect('):full_source.index('bool BackendAgentWebsocket::sendText(')]
disconnect_harness = r'''
#include <cassert>
#include <vector>
uint32_t millis() { return 1000; }
struct Client { int stops = 0; void stop() { ++stops; } };
struct Owner { bool websocketConnected_ = true; };
struct BackendAgentWebsocket {
    Client *client_;
    Owner *owner_;
    std::vector<uint8_t> rx_;
    bool connected_ = true;
    uint32_t nextAttemptMs_ = 0;
    void disconnect(bool);
};
'''
disconnect_checks = r'''
int main() {
    Client client; Owner owner;
    BackendAgentWebsocket ws{&client, &owner, {}, true, 0};
    ws.rx_.resize(8192, 1);
    ws.disconnect(false);
    assert(client.stops == 1 && !owner.websocketConnected_ && !ws.connected_);
    assert(ws.rx_.empty() && ws.rx_.capacity() == 0 && ws.nextAttemptMs_ == 11000);
    ws.rx_.resize(10, 1); ws.disconnect(true);
    assert(ws.rx_.empty() && ws.rx_.capacity() == 0 && ws.nextAttemptMs_ == 61000);
    BackendAgentWebsocket withoutClient{nullptr, nullptr, {}, true, 0};
    withoutClient.disconnect(false); assert(!withoutClient.connected_);
}
'''
with tempfile.TemporaryDirectory(prefix='esp-websocket-disconnect-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(shim + disconnect_harness + disconnect + disconnect_checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: disconnect frees buffers and preserves reconnect scheduling')
