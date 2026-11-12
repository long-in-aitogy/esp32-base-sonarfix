"""Exercise multiline UNILOGLIST collection and checksum validation."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/gnss/Unicore_Readback.cpp').read_text()
parser = source[source.index('        bool appendUnicoreCandidate('):source.index('/** @brief Implements processUnicoreQueryByte.')]
reader = source[source.index('    bool readLogList('):source.index('/** @brief Implements readMode.')]
shim = (root / 'test/host/Arduino.h').read_text().replace('#pragma once', '')
shim = shim.replace('    bool isEmpty() const', '''    String(char value) : std::string(1, value) {}
    bool startsWith(const String &value) const { return compare(0, value.size(), value) == 0; }
    void remove(size_t start) { erase(start); }
    bool isEmpty() const''')
harness = r'''
#include <cassert>
bool validUnicoreLogChecksum(const char *, size_t);
String input;
bool queryUnicoreLine(const char *, const char *, String &response, String &, bool multiline) {
    assert(multiline); response = input; return true;
}
'''
checks = r'''
int main() {
    String candidate, response;
    const String lines = String("#UNILOGLIST,header\r\n") + String(500, 'x') + "\r\nCOM1,RTCM\r\n\r\n";
    for (char c : lines) appendUnicoreCandidate(c, "#UNILOGLIST,", true, candidate, response);
    assert(response == lines);
    candidate.clear(); response.clear();
    for (char c : String("#MODE,BASE\r\n")) appendUnicoreCandidate(c, "#MODE", false, candidate, response);
    assert(response == "#MODE,BASE");
    candidate.clear(); response.clear();
    for (char c : String("#UNILOGLIST,data*12345678\r\n")) appendUnicoreCandidate(c, "#UNILOGLIST,", true, candidate, response);
    assert(response == "#UNILOGLIST,data*12345678");
    String error; input = response;
    assert(!readLogList(response, error) && error == "Unicore UNILOGLIST checksum mismatch");
    input = "#UNILOGLIST,header\r\nCOM1,RTCM\r\n\r\n"; error.clear(); response.clear();
    assert(readLogList(response, error) && response == input);
}
'''
with tempfile.TemporaryDirectory(prefix='unicore-log-list-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(shim + harness + parser + reader + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'include'), '-I' + str(root / 'test/host'), str(path / 'check.cpp'),
                    str(root / 'src/functions/gnss/Unicore_Log.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: multiline UNILOGLIST, single-line MODE and invalid checksum')
