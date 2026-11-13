"""An oversized saved service configuration must not be replaced at boot."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Storage.cpp').read_text()
method = source[source.index('void BackendAgent::ensureDefaultServiceConfig()'):source.index('bool BackendAgent::saveStatePreferences()')]
shim = (root / 'test/host/Arduino.h').read_text().replace('#pragma once', '')
shim = shim.replace('    void trim()', '    bool startsWith(const char *s) const { return find(s) == 0; }\n    void remove(size_t p, size_t n) { erase(p, n); }\n    void trim()')
harness = r'''
#include <ArduinoJson.h>
#include <cassert>
constexpr size_t CONFIG_DOCUMENT_SIZE = 6144;
constexpr const char *NTRIP_CASTER_ADDRESS = "legacy", *NTRIP_MOUNTPOINT = "mount", *NTRIP_AUTH_BASE_STATION = "password";
constexpr uint16_t NTRIP_CASTER_PORT = 2101;
struct Preferences {
    void begin(const char *, bool) {} void end() {}
    String getString(const char *, const String &fallback) { return fallback; }
    uint16_t getUShort(const char *, uint16_t fallback) { return fallback; }
} prefs;
struct BackendAgent {
    String serviceConfig_ = "{}"; int saves = 0;
    bool saveStatePreferences() { ++saves; return true; }
    void ensureDefaultServiceConfig();
};
'''
checks = r'''
int main() {
    BackendAgent agent;
    agent.serviceConfig_ = String("{\"legacy\":\"") + String(std::string(7000, 'x')) + "\"}";
    const String original = agent.serviceConfig_;
    agent.ensureDefaultServiceConfig();
    assert(agent.serviceConfig_ == original && agent.saves == 0);
    agent.serviceConfig_ = "{}"; agent.ensureDefaultServiceConfig();
    assert(agent.serviceConfig_ != "{}" && agent.saves == 1);
}
'''
with tempfile.TemporaryDirectory(prefix='service-startup-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(shim + harness + method + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined',
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: boot preserves oversized service config and still initializes empty config')
