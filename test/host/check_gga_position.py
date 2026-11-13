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
std::string withChecksum(const char *text) {
    std::string line=text;
    auto star=line.find('*');
    if (star==std::string::npos) return line;
    unsigned char checksum=0;
    for (size_t i=1;i<star;++i) checksum ^= static_cast<unsigned char>(line[i]);
    char suffix[4]; std::snprintf(suffix,sizeof(suffix),"*%02X",checksum);
    line.replace(star,3,suffix);
    return line;
}
void parseChecked(const char *text) { parseNmeaSentence(withChecksum(text).c_str()); }
int main() {
    parseChecked("$GNGGA,010000,2105.0994,N,10547.19936,E,4,20,0.7,20.5000,M,-28.5624,M,,*00");
    assert(telemetry.traffic.ggaCount == 1 && telemetry.satellites == 20);
    assert(strcmp(telemetry.fixStatus.data(), "RTK_FIXED") == 0);
    assert(fabs(telemetry.latitude - 21.08499) < 1e-9);
    assert(fabs(telemetry.longitude - 105.786656) < 1e-9);
    assert(fabs(telemetry.altitude + 8.0624) < 1e-9);
    assert(telemetry.lastGgaMs == now);
    std::string corrupt=withChecksum("$GNGGA,010000,2105.0994,N,10547.19936,E,4,20,0.7,20.5000,M,-28.5624,M,,*00");
    corrupt[20] = corrupt[20] == '1' ? '2' : '1';
    now += 100; parseNmeaSentence(corrupt.c_str());
    assert(telemetry.lastGgaMs == 1000 && telemetry.traffic.ggaCount == 1);
    parseNmeaSentence("$GNGGA,010000,2105.0994,N,10547.19936,E,4,20,0.7,20.5,M,0,M,,*Q1");
    assert(telemetry.lastGgaMs == 1000 && telemetry.traffic.ggaCount == 1);
    parseNmeaSentence("$GNGGA,010000,2105.0994,N,10547.19936,E,4,20,0.7,20.5,M,0,M,,*0");
    assert(telemetry.lastGgaMs == 1000 && telemetry.traffic.ggaCount == 1);
    parseNmeaSentence("$GNGGA,010000,2105.0994,N,10547.19936,E,4,20,0.7,20.5,M,0,M,,");
    assert(telemetry.lastGgaMs == now && telemetry.traffic.ggaCount == 2);
    const auto previousGgaCount = telemetry.traffic.ggaCount;
    parseChecked("$LONGNAMEGGA,010000,2105.0994,N,10547.19936,E,4,20,0.7,20.5000,M,-28.5624,M,,*00");
    assert(telemetry.traffic.ggaCount == previousGgaCount + 1);
    parseChecked("$GNGSA,A,3,,,,,,,,,,,,,1.0,0.7,0.8*00");
    assert(strcmp(telemetry.fixStatus.data(), "RTK_FIXED") == 0);
    parseChecked("$GNGGA,010001,2105.0994,N,10547.19936,E,4,20,0.7,20.5,M,,M,,*00");
    assert(std::isnan(telemetry.altitude)); // Missing N is unknown, never zero.
    parseChecked("$GNGGA,010002,,,,,4,20,0.7,20.5,M,-28.5624,M,,*00");
    assert(std::isnan(telemetry.latitude) && std::isnan(telemetry.longitude));
    assert(std::isnan(telemetry.altitude)); // New epoch cannot reuse previous coordinates.
    parseChecked("$GNGGA,010003,2105.0994,N,10547.19936,E,4,20,0.7,20.5,F,-28.5624,M,,*00");
    assert(std::isnan(telemetry.altitude)); // Both height units must be metres.
    parseChecked("$GNGGA,010004,2105.0994,N,10547.19936,E,4,20,0.7,20.5x,M,-28.5624,M,,*00");
    assert(std::isnan(telemetry.altitude)); // Reject partially parsed numbers.
    parseChecked("$GNGGA,010005,2105.0994,N,10547.19936,E,4,20,0.7,,M,-28.5624,M,,*00");
    assert(std::isnan(telemetry.altitude)); // Missing H is unknown too.
    parseChecked("$GNGGA,010006,2105.0994,N,10547.19936,E,4,20,0.7,20.5,M,0,M,,*00");
    assert(telemetry.altitude == 20.5); // A real zero N is valid.
    for (const char *bad : {
        "$GNGGA,010007,garbage,N,10547.19936,E,4,20,0.7,20.5,M,0,M,,*00",
        "$GNGGA,010007,2160.0000,N,10547.19936,E,4,20,0.7,20.5,M,0,M,,*00",
        "$GNGGA,010007,2105.0994,E,10547.19936,N,4,20,0.7,20.5,M,0,M,,*00",
        "$GNGGA,010007,nan,N,10547.19936,E,4,20,0.7,20.5,M,0,M,,*00",
        "$GNGGA,010007,9000.0001,N,10547.19936,E,4,20,0.7,20.5,M,0,M,,*00"}) {
        parseChecked(bad);
        assert(std::isnan(telemetry.latitude) && std::isnan(telemetry.longitude) && std::isnan(telemetry.altitude));
    }
    parseChecked("$GNGGA,010008,2105.0994,N,10547.19936,E,4bad,20,0.7,20.5,M,0,M,,*00");
    assert(strcmp(telemetry.fixStatus.data(), "NO_FIX") == 0);
    parseChecked("$GNGGA,010009,0000.0000,S,00000.0000,W,4,20,0.7,20.5,M,0,M,,*00");
    assert(telemetry.latitude == 0 && telemetry.longitude == 0 && telemetry.altitude == 20.5);
    parseChecked("$GNGGA,010010,0000.0000,S");
    assert(strcmp(telemetry.fixStatus.data(), "NO_FIX") == 0 && std::isnan(telemetry.latitude));
}
'''
with tempfile.TemporaryDirectory(prefix='esp-gga-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(shim + harness + telemetry + '\nGnssTelemetrySnapshot telemetry;\n' + functions + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined',
                    '-I' + str(root / 'include'), str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: real GGA telemetry parses RTK Fixed LLH; h=H+N; missing height/coordinates never reuse a prior sample')
