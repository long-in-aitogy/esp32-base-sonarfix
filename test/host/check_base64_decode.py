"""Check complete Base64 input before accepting decoded receiver commands."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Codec.cpp').read_text()
methods = source[source.index('    int base64Value('):source.index('    bool delayMarker(')]
harness = r'''
#include <Arduino.h>
#include <array>
#include <cassert>
'''
checks = r'''
int main() {
    std::array<uint8_t, 8> out{};
    for (const char *value : {"TWFu", "T W\nFu"}) {
        assert(decodeBase64(value, out.data(), out.size()) == 3);
        assert(out[0] == 'M' && out[1] == 'a' && out[2] == 'n');
    }
    for (const char *value : {"TQ==", "TQ"})
        assert(decodeBase64(value, out.data(), out.size()) == 1 && out[0] == 'M');
    for (const char *value : {"T", "TR==", "TQ=", "TQ===", "TQ==junk", "TW=F", "TWFu!"})
        assert(decodeBase64(value, out.data(), out.size()) == 0);
    assert(decodeBase64("TWFu", out.data(), 2) == 0);
    assert(decodeBase64("TQ==", nullptr, 1) == 0);
}
'''
with tempfile.TemporaryDirectory(prefix='esp-base64-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + methods + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined', '-I' + str(root / 'test/host'), str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: complete, canonical Base64 commands; invalid padding and trailing data rejected')
