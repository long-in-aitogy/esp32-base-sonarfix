"""Verify bounded VALGET requests and replies matched by key."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/gnss/Ublox_Readback.cpp').read_text()
method = source[source.index('bool UbloxReadback::readOutputValues('):]
program = r'''
#include <Arduino.h>
#include <array>
#include <cassert>
#include <cstring>
#include "functions/gnss/Ubx_Reply.h"
#include "functions/gnss/Ubx_Config_Verification.h"
int queries = 0;
bool readable = true, duplicate = false;
bool query(uint8_t cls, uint8_t id, UbxReply &reply, String &, const uint8_t *payload, size_t length) {
    ++queries; assert(cls == 6 && id == 0x8b && length == 12);
    assert(payload[0] == 0 && payload[1] == 0 && payload[2] == 0 && payload[3] == 0);
    assert(UbxBaseStatus::u32(payload + 4) == 0x209100bb);
    reply.length = 22;
    reply.frame[6] = 1;
    // Reverse response order to prove matching uses keys.
    std::memcpy(reply.frame.data() + 10, payload + 8, 4); reply.frame[14] = 0;
    std::memcpy(reply.frame.data() + 15, payload + (duplicate ? 8 : 4), 4); reply.frame[19] = 1;
    return readable;
}
namespace UbloxReadback { bool readOutputValues(const uint8_t *, size_t, uint8_t *, String &); }
'''
checks = r'''
int main() {
    std::array<uint8_t, 10> expected{0xbb,0,0x91,0x20,1,0xc0,0,0x91,0x20,0};
    std::array<uint8_t, 2> values{}; String error;
    assert(UbloxReadback::readOutputValues(expected.data(), expected.size(), values.data(), error));
    assert(values[0] == 1 && values[1] == 0);
    duplicate = true;
    assert(!UbloxReadback::readOutputValues(expected.data(), expected.size(), values.data(), error));
    int previousQueries = queries;
    assert(!UbloxReadback::readOutputValues(expected.data(), 9, values.data(), error));
    assert(!UbloxReadback::readOutputValues(expected.data(), expected.size(), nullptr, error));
    assert(queries == previousQueries);
    duplicate = false; readable = false;
    assert(!UbloxReadback::readOutputValues(expected.data(), expected.size(), values.data(), error));
}
'''
with tempfile.TemporaryDirectory(prefix='ublox-output-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(program + method + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'include'), '-I' + str(root / 'test/host'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: VALGET payload, reordered replies, duplicates, invalid input and unread receiver')
