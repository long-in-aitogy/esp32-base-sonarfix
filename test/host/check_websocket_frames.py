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
    }
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
print('PASS: real WebSocket reader; partial/coalesced frames, 32KB limit, invalid headers, ping/close and command delivery')
