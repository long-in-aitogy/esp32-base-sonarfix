"""Survey-In fallback must not be reported as an unverified fixed result."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Status.cpp').read_text()
begin = source.index('void BackendAgent::appendAutoBaseProgress(')
end = source.index('\nvoid BackendAgent::appendSystemInfo(', begin)
method = source[begin:end]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <array>
#include <cassert>
struct GnssTelemetrySnapshot {
    std::array<char, 128> lastGga{};
    std::array<char, 16> fixStatus{};
    double latitude = 21, longitude = 105, altitude = 10;
};
int ntripRoverBytesReceived() { return 12; }
int ntripRoverPacketsReceived() { return 2; }
struct BackendAgent { void appendAutoBaseProgress(JsonDocument &, const GnssTelemetrySnapshot &, uint32_t) const; };
'''
checks = r'''
int main() {
    BackendAgent agent; GnssTelemetrySnapshot gnss; DynamicJsonDocument doc(2048);
    doc["auto_base_progress"]["phase"] = "completed";
    doc["auto_base_progress"]["mode"] = "survey_in";
    agent.appendAutoBaseProgress(doc, gnss, 0);
    assert(doc["auto_base_progress"]["phase"] == "completed");
    doc["auto_base_progress"].remove("mode");
    agent.appendAutoBaseProgress(doc, gnss, 0);
    assert(doc["auto_base_progress"]["phase"] == "unverified");
    doc["auto_base_progress"]["phase"] = "completed";
    doc["auto_base_progress"]["fixed_samples_only"] = true;
    agent.appendAutoBaseProgress(doc, gnss, 0);
    assert(doc["auto_base_progress"]["phase"] == "completed");
}
'''
with tempfile.TemporaryDirectory(prefix='auto-base-status-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + method + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: Survey-In fallback remains completed; old fixed results remain unverified')
