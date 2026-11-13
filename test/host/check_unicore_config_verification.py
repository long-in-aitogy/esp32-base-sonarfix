"""Validate receiver MODE and bounded UNILOGLIST parsing."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
program = r'''
#include "functions/gnss/Unicore_Config_Verification.h"
#include <cassert>
#include <string>
int main() {
    double lat, lon, alt;
    assert(UnicoreConfigVerification::parseFixedMode("MODE BASE 21.25 105.75 10.5", lat, lon, alt));
    assert(lat == 21.25 && lon == 105.75 && alt == 10.5);
    assert(!UnicoreConfigVerification::parseFixedMode("MODE BASE 91 105 10", lat, lon, alt));
    assert(!UnicoreConfigVerification::parseFixedMode("MODE BASE 21 105 10 extra", lat, lon, alt));
    std::vector<UnicoreConfigVerification::Log> logs;
    std::string list = "#UNILOGLIST,header;< 2\r\n< GPGGA COM2 1\r\n< RTCM1074 COM2 ONTIME 1\r\n\r\n";
    assert(UnicoreConfigVerification::parseLogs(list.data(), list.size(), logs));
    assert(logs.size() == 2 && UnicoreConfigVerification::comparisonPort(0, logs) == 2);
    list.resize(list.size() - 2);
    assert(!UnicoreConfigVerification::parseLogs(list.data(), list.size(), logs));
    list = "#UNILOGLIST,header;< 2\r\n< GPGGA COM2 1\r\n< GPGGA COM2 1\r\n\r\n";
    assert(!UnicoreConfigVerification::parseLogs(list.data(), list.size(), logs));
    list = "#UNILOGLIST,header;< 1\r\n< RTCM1074 COM9 1\r\n\r\n";
    assert(!UnicoreConfigVerification::parseLogs(list.data(), list.size(), logs));
    list = "#UNILOGLIST,header;< 1\r\n< RTCM1074 COM2 nan\r\n\r\n";
    assert(!UnicoreConfigVerification::parseLogs(list.data(), list.size(), logs));
}
'''
with tempfile.TemporaryDirectory(prefix='unicore-config-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(program)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'include'), str(path / 'check.cpp'),
                    str(root / 'src/functions/gnss/Unicore_Log.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: Unicore MODE, log entries, ports, truncated and invalid responses')
