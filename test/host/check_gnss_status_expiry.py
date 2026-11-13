"""Ensure stale GNSS telemetry is cleared rather than retained by the backend cache."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root/'src/functions/backend/Backend_Agent_Status.cpp').read_text()
method = source[source.index('namespace {\nvoid appendNmeaHealth('):source.index('\nvoid BackendAgent::appendNtripStatus(')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <array>
#include <cassert>
struct GnssTelemetrySnapshot {
    struct { int ggaCount=0,gsaCount=0,gsvCount=0,gstCount=0,rtcmFrames=0,nmeaSentences=0,bytesRead=0; } traffic;
    int snrSamples=0,latestGsvSamples=0; double latestAverageSnr=0,averageSnr=0,gstSemiMajor=0,gstSemiMinor=0,gstHacc=0;
    uint32_t lastGsvMs=0,lastGstMs=0,lastDataMs=0; double latitude=0,longitude=0,altitude=0;
    std::array<char,16> fixStatus{}; int satellites=0; bool hasData=false;
};
struct BackendAgent {
    String sensorType_="Ublox",versionReadback_,versionReadbackError_,satelliteReadback_;
    uint32_t receiverInfoMs_=0,satelliteReadbackMs_=0,dopMs_=0,navigationMs_=0,unicoreQualityMs_=0;
    struct { int hdop=0,pdop=0; } dop_;
    struct { bool valid=false; int fixType=0,satellites=0,pdop=0,haccMm=0; } navigation_;
    double unicoreHorizontalSigma_=0;
    void appendGnssStatus(JsonDocument &, const GnssTelemetrySnapshot &, uint32_t) const;
};
'''
checks = r'''
int main() {
    BackendAgent agent; GnssTelemetrySnapshot gnss; DynamicJsonDocument doc(4096);
    agent.navigationMs_=100; agent.navigation_.valid=true; agent.navigation_.haccMm=1234;
    agent.dopMs_=100; agent.satelliteReadbackMs_=100; agent.satelliteReadback_="data";
    agent.receiverInfoMs_=100; agent.versionReadback_="version";
    agent.appendGnssStatus(doc,gnss,1000);
    assert(doc["gnss_quality"]["hacc_m"]==1.234 && doc["hacc"]==1234);
    assert(doc["gnss_dop"].is<JsonObject>() && doc["gnss_satellites"].is<JsonObject>() && doc["gnss_receiver"].is<JsonObject>());
    doc.clear(); agent.appendGnssStatus(doc,gnss,50000);
    for (const char *key : {"hacc","gnss_quality","gnss_dop","gnss_satellites","gnss_rf","gnss_spectrum","gnss_rf_monitor"})
        assert(doc.containsKey(key) && doc[key].isNull());
    assert(doc["gnss_receiver"]["payload_b64"] == "version");
    agent.versionReadback_.clear(); agent.versionReadbackError_="version unread";
    doc.clear(); agent.appendGnssStatus(doc,gnss,50000); assert(doc["gnss_receiver"].isNull());
    doc.clear(); agent.appendGnssStatus(doc,gnss,1000); assert(doc["gnss_receiver"]["error"]=="version unread");
    doc.clear(); agent.navigationMs_=1000; agent.navigation_.valid=false; agent.appendGnssStatus(doc,gnss,1000);
    assert(doc["gnss_quality"].is<JsonObject>() && doc.containsKey("hacc") && doc["hacc"].isNull());
}
'''
with tempfile.TemporaryDirectory(prefix='gnss-status-') as directory:
    path=Path(directory); (path/'check.cpp').write_text(harness+method+checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(root/'test/host'),'-I'+str(root/'.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: fresh GNSS telemetry and explicit expiry for cached fields')
