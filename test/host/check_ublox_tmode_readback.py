"""Reject incomplete/version-mismatched TMODE3 without changing caller data."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/gnss/Ublox_Readback.cpp').read_text()
method = source[source.index('bool UbloxReadback::readTmode('):source.index('/** @brief Implements UbloxReadback::readBaseStatus.')]
harness = r'''
#include <Arduino.h>
#include <array>
#include <cassert>
#include <cstring>
#include "functions/gnss/Ubx_Reply.h"
UbxReply response;
bool readable = true; int queries = 0;
bool query(uint8_t cls, uint8_t id, UbxReply &reply, String &) {
    assert(cls == 6 && id == 0x71); ++queries; reply = response; return readable;
}
namespace UbloxReadback { bool readTmode(uint8_t *, String &); }
'''
checks = r'''
int main() {
    String error; std::array<uint8_t, 40> payload; payload.fill(0xaa);
    const auto untouched = payload;
    assert(!UbloxReadback::readTmode(nullptr, error) && queries == 0);
    response.length = 47;
    assert(!UbloxReadback::readTmode(payload.data(), error) && payload == untouched);
    response.length = 48; response.frame[6] = 1;
    assert(!UbloxReadback::readTmode(payload.data(), error) && payload == untouched);
    response.frame[6] = 0; response.frame[8] = 2;
    assert(UbloxReadback::readTmode(payload.data(), error) && payload[0] == 0 && payload[2] == 2);
    payload = untouched; readable = false;
    assert(!UbloxReadback::readTmode(payload.data(), error) && payload == untouched);
}
'''
with tempfile.TemporaryDirectory(prefix='ublox-tmode-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + method + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'include'), '-I' + str(root / 'test/host'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: TMODE3 exact length/version, no partial writes and query failure')
