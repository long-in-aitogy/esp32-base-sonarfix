"""Saved transport takes precedence over the firmware's first-boot default."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/hardware/Connection_type.cpp').read_text()
method = source[source.index('void loadConnectionTypeFromPrefs('):]
main = (root / 'src/main.cpp').read_text()
init = main[main.index('void initPrefs()\n{'):]
assert 'prefs.putString("CONNECTION_TYPE", CONNECTION_PREFERENCE)' in init
harness = r'''
#include <hardware/Connection_type.h>
#include <cassert>
const char *CONNECTION_PREFERENCE = "4G";
struct Preferences {
    bool hasValue = false;
    String value;
    String getString(const char *, const char *fallback) { return hasValue ? value : String(fallback); }
} prefs;
ConnectionType connectionType = ConnectionType::GSM;
'''
checks = r'''
int main() {
    loadConnectionTypeFromPrefs(); assert(connectionType == ConnectionType::GSM);
    CONNECTION_PREFERENCE = "WIFI";
    loadConnectionTypeFromPrefs(); assert(connectionType == ConnectionType::WIFI);
    prefs.hasValue = true; prefs.value = "4G";
    loadConnectionTypeFromPrefs(); assert(connectionType == ConnectionType::GSM);
    prefs.value = "wifi";
    loadConnectionTypeFromPrefs(); assert(connectionType == ConnectionType::WIFI);
    prefs.value = "invalid";
    loadConnectionTypeFromPrefs(); assert(connectionType == ConnectionType::GSM);
}
'''
with tempfile.TemporaryDirectory(prefix='esp-connection-default-') as directory:
    path = Path(directory)
    shim = (root / 'test/host/Arduino.h').read_text().replace(
        '    void println(const char *) {}', '    void println(const char *) {}\n    void println(const String &) {}')
    (path / 'Arduino.h').write_text(shim)
    (path / 'check.cpp').write_text(harness + method + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined', '-I' + str(path), '-I' + str(root / 'include'), str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: firmware default and saved transport preference, including invalid legacy values')
