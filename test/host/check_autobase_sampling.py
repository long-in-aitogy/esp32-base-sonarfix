"""Exercise the real Auto Base wait and sampling loops with simulated telemetry."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Workflows.cpp').read_text()
methods = source[source.index('bool BackendAgent::waitForAutoBaseFix('):source.index('String BackendAgent::buildAutoBaseResult(')]
methods += source[source.index('bool BackendAgent::waitForReferenceFix('):source.index('String BackendAgent::buildReferenceCheckResult(')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include "functions/backend/Base_Sample.h"
#include <array>
#include <cassert>
#include <cmath>
#include <vector>
uint32_t now = 1000;
int mode = 0;
uint32_t millis() { return now; }
int pdMS_TO_TICKS(int ms) { return ms; }
void vTaskDelay(int ms) { now += ms; }
const char *ntripRoverLastError() { return "caster disconnected"; }
struct GnssTelemetrySnapshot {
    uint32_t lastGgaMs;
    std::array<char, 16> fixStatus;
    double latitude, longitude, altitude;
};
GnssTelemetrySnapshot getGnssTelemetrySnapshot() {
    GnssTelemetrySnapshot s{mode == 1 ? 1000U : mode == 5 ? (now < 2000 ? 1000U : 2000U) : now, {}, 21, 105, 12};
    std::snprintf(s.fixStatus.data(), s.fixStatus.size(), "%s", mode == 2 ? "RTK_FLOAT" : "RTK_FIXED");
    if (mode == 3) s.latitude = NAN;
    return s;
}
struct BackendAgent {
    bool workflowCancelRequested_ = false;
    int loopNtripRoverLocked() { return mode == 4 ? 504 : 200; }
    void setWorkflowProgress(const String &, int, int, const String &) {}
    bool waitForAutoBaseFix(uint32_t, uint8_t, bool &, String &, const String &);
    bool collectAutoBaseSamples(int, std::vector<double> &, std::vector<double> &, std::vector<double> &, bool &, String &, const String &);
    bool waitForReferenceFix(uint32_t, String &);
    bool collectReferenceSamples(uint16_t, std::vector<double> &, std::vector<double> &, std::vector<double> &, String &);
};
'''
checks = r'''
int main() {
    BackendAgent agent; bool cancelled = false; String error;
    assert(agent.waitForAutoBaseFix(10, 3, cancelled, error, "station"));
    mode = 2; now = 1000;
    assert(!agent.waitForAutoBaseFix(3, 2, cancelled, error, "station") && error == "RTK fix timeout");
    mode = 4; now = 1000;
    assert(!agent.waitForAutoBaseFix(3, 2, cancelled, error, "station") && error == "caster disconnected");
    agent.workflowCancelRequested_ = true; mode = 0; cancelled = false;
    assert(!agent.waitForAutoBaseFix(3, 2, cancelled, error, "station") && cancelled);
    agent.workflowCancelRequested_ = false; cancelled = false;
    std::vector<double> lat, lon, alt;
    now = 1000; assert(agent.collectAutoBaseSamples(60, lat, lon, alt, cancelled, error, "station"));
    assert(lat.size() == 60 && lon.size() == 60 && alt.size() == 60);
    for (int invalid : {1, 2, 3}) {
        mode = invalid; now = 1000; lat.clear(); lon.clear(); alt.clear();
        assert(!agent.collectAutoBaseSamples(60, lat, lon, alt, cancelled, error, "station"));
        assert(error == "insufficient valid RTK samples" && lat.size() <= 1);
    }
    mode = 4; now = 1000; lat.clear(); lon.clear(); alt.clear();
    assert(!agent.collectAutoBaseSamples(60, lat, lon, alt, cancelled, error, "station") && error == "caster disconnected");
    mode = 0; agent.workflowCancelRequested_ = true; cancelled = false;
    assert(!agent.collectAutoBaseSamples(60, lat, lon, alt, cancelled, error, "station") && cancelled);
    agent.workflowCancelRequested_ = false; mode = 0; now = 1000;
    assert(agent.waitForReferenceFix(3, error));
    lat.clear(); lon.clear(); alt.clear();
    assert(agent.collectReferenceSamples(5, lat, lon, alt, error) && lat.size() == 5);
    mode = 5; now = 1000; lat.clear(); lon.clear(); alt.clear();
    assert(!agent.collectReferenceSamples(5, lat, lon, alt, error));
    assert(error == "insufficient valid reference samples" && lat.size() == 2);
}
'''
with tempfile.TemporaryDirectory(prefix='autobase-sampling-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + methods + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined', '-I' + str(root / 'test/host'),
                    '-I' + str(root / 'include'), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: Auto Base and reference sampling reject stale or duplicate RTK data')
