"""Run the actual GGA telemetry parser, including ellipsoid height and invalid epochs."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/ntrip/RTCM_Receiver.cpp').read_text()
functions = source[source.index('    double nmeaCoordinate('):source.index('/** @brief Implements resetRtcmParser.')]
header = (root / 'include/functions/ntrip/RTCM_Receiver.h').read_text()
telemetry = header[header.index('inline constexpr size_t RTCM_SUPPORTED_MESSAGE_TYPE_COUNT'):header.index('String receiveRtcmFromGnss();')]
shim = (root / 'test/host/Arduino.h').read_text().replace('#pragma once', '')
shim = shim.replace('    void trim()', '    bool startsWith(const String &value) const { return compare(0, value.size(), value) == 0; }\n    void trim()')
harness = r'''
#include "functions/backend/Base_Sample.h"
#include <array>
#include <cstring>
#include <cassert>
#include <cmath>
using std::min;
unsigned now = 1000;
unsigned millis() { return now; }
int constrain(int value, int low, int high) { return std::max(low, std::min(value, high)); }
#define portENTER_CRITICAL(x) ((void)0)
#define portEXIT_CRITICAL(x) ((void)0)
constexpr size_t MAX_NMEA_LENGTH = 512;
struct {
    void setDetectedChipIfUnknown(const String &) {}
    void enqueueNmea(const uint8_t *, size_t) {}
} backendAgent;
'''
checks = r'''
int main() {
    parseNmeaSentence("$GNGGA,010000,2105.0994,N,10547.19936,E,4,20,0.7,20.5000,M,-28.5624,M,,*00");
    assert(telemetry.traffic.ggaCount == 1 && telemetry.satellites == 20);
    assert(strcmp(telemetry.fixStatus.data(), "RTK_FIXED") == 0);
    assert(fabs(telemetry.latitude - 21.08499) < 1e-9);
    assert(fabs(telemetry.longitude - 105.786656) < 1e-9);
    assert(fabs(telemetry.altitude + 8.0624) < 1e-9);
    assert(telemetry.lastGgaMs == now);
    parseNmeaSentence("$GNGSA,A,3,,,,,,,,,,,,,1.0,0.7,0.8*00");
    assert(strcmp(telemetry.fixStatus.data(), "RTK_FIXED") == 0);
    parseNmeaSentence("$GNGGA,010001,2105.0994,N,10547.19936,E,4,20,0.7,20.5,M,,M,,*00");
    assert(std::isnan(telemetry.altitude)); // Missing N is unknown, never zero.
    parseNmeaSentence("$GNGGA,010002,,,,,4,20,0.7,20.5,M,-28.5624,M,,*00");
    assert(std::isnan(telemetry.latitude) && std::isnan(telemetry.longitude));
    assert(std::isnan(telemetry.altitude)); // New epoch cannot reuse previous coordinates.
    parseNmeaSentence("$GNGGA,010003,2105.0994,N,10547.19936,E,4,20,0.7,20.5,F,-28.5624,M,,*00");
    assert(std::isnan(telemetry.altitude)); // Both height units must be metres.
    parseNmeaSentence("$GNGGA,010004,2105.0994,N,10547.19936,E,4,20,0.7,20.5x,M,-28.5624,M,,*00");
    assert(std::isnan(telemetry.altitude)); // Reject partially parsed numbers.
    parseNmeaSentence("$GNGGA,010005,2105.0994,N,10547.19936,E,4,20,0.7,,M,-28.5624,M,,*00");
    assert(std::isnan(telemetry.altitude)); // Missing H is unknown too.
    parseNmeaSentence("$GNGGA,010006,2105.0994,N,10547.19936,E,4,20,0.7,20.5,M,0,M,,*00");
    assert(telemetry.altitude == 20.5); // A real zero N is valid.
}
'''
with tempfile.TemporaryDirectory(prefix='esp-gga-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(shim + harness + telemetry + '\nGnssTelemetrySnapshot telemetry;\n' + functions + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined',
                    '-I' + str(root / 'include'), str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: real GGA telemetry parses RTK Fixed LLH; h=H+N; missing height/coordinates never reuse a prior sample')
