"""Exercise NAV-PVT/NAV-DOP decoding and actual GNSS status serialization."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Status.cpp').read_text()
status = source[source.index('void BackendAgent::appendGnssStatus('):source.index('void BackendAgent::appendNtripStatus(')]
header = (root / 'include/functions/ntrip/RTCM_Receiver.h').read_text()
snapshot = header[header.index('inline constexpr size_t RTCM_SUPPORTED_MESSAGE_TYPE_COUNT'):header.index('String receiveRtcmFromGnss();')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <array>
#include <cassert>
#include <cmath>
#include "functions/gnss/Ubx_Navigation.h"
'''
agent = r'''
struct BackendAgent {
    String sensorType_ = "Ublox";
    UbxNavigation navigation_;
    UbxDop dop_;
    uint32_t navigationMs_ = 0, dopMs_ = 0, satelliteReadbackMs_ = 0;
    String satelliteReadback_, versionReadback_, versionReadbackError_;
    uint32_t receiverInfoMs_ = 0;
    float unicoreHorizontalSigma_ = 0;
    uint32_t unicoreQualityMs_ = 0;
    void appendGnssStatus(JsonDocument &, const GnssTelemetrySnapshot &, uint32_t) const;
};
'''
checks = r'''
int main() {
    std::array<uint8_t, 92> pvt{};
    pvt[20] = 3; pvt[21] = 1; pvt[23] = 17;
    pvt[40] = 0x2C; pvt[41] = 0x01; // 300 mm
    pvt[76] = 234;
    UbxNavigation nav;
    assert(!nav.decode(nullptr, pvt.size()) && !nav.decode(pvt.data(), 91));
    assert(nav.decode(pvt.data(), pvt.size()) && nav.valid && nav.haccMm == 300);
    assert(nav.satellites == 17 && nav.pdop == 234);
    pvt[78] = 1; assert(nav.decode(pvt.data(), pvt.size()) && !nav.valid);
    pvt[78] = 0; pvt[21] = 0; assert(nav.decode(pvt.data(), pvt.size()) && !nav.valid);
    pvt[21] = 1; pvt[20] = 6; assert(!nav.decode(pvt.data(), pvt.size()));
    pvt[20] = 3; assert(nav.decode(pvt.data(), pvt.size()) && nav.valid);
    std::array<uint8_t, 18> bytes{};
    bytes[6] = 234; bytes[12] = 123;
    UbxDop dop;
    assert(!dop.decode(nullptr, bytes.size()) && !dop.decode(bytes.data(), 17));
    assert(dop.decode(bytes.data(), bytes.size()) && dop.pdop == 234 && dop.hdop == 123);
    BackendAgent agent;
    agent.satelliteReadback_ = "payload"; agent.satelliteReadbackMs_ = 1000;
    agent.versionReadback_ = "version"; agent.receiverInfoMs_ = 1000;
    DynamicJsonDocument satelliteDoc(4096); GnssTelemetrySnapshot satelliteGnss;
    agent.appendGnssStatus(satelliteDoc, satelliteGnss, 46000);
    assert(satelliteDoc["gnss_satellites"]["payload_b64"] == "payload");
    assert(satelliteDoc["gnss_receiver"]["payload_b64"] == "version");
    satelliteDoc.clear(); agent.appendGnssStatus(satelliteDoc, satelliteGnss, 46001);
    assert(satelliteDoc["gnss_satellites"].isNull());
    assert(satelliteDoc["gnss_receiver"].isNull());
    agent.navigation_ = nav; agent.navigationMs_ = 1000;
    agent.dop_ = dop; agent.dopMs_ = 1000;
    GnssTelemetrySnapshot gnss;
    gnss.gstHacc = 0.4f; gnss.lastGstMs = 45000;
    DynamicJsonDocument doc(4096);
    agent.appendGnssStatus(doc, gnss, 46000);
    assert(doc["satellite_count"] == 17 && doc["hacc"] == 300);
    assert(doc["gnss_quality"]["source"] == "ubx_nav_pvt");
    assert(std::abs(doc["gnss_quality"]["hacc_m"].as<double>() - 0.3) < 1e-8);
    assert(std::abs(doc["gnss_dop"]["hdop"].as<double>() - 1.23) < 1e-8);
    doc.clear(); agent.navigation_.valid = false;
    agent.appendGnssStatus(doc, gnss, 46000);
    assert(doc["gnss_quality"]["hacc_m"].isNull() && doc["hacc"].isNull());
    doc.clear(); agent.appendGnssStatus(doc, gnss, 46001);
    assert(doc["gnss_quality"]["source"] == "nmea_gst" && doc["gnss_dop"].isNull());
    assert(std::abs(doc["hacc"].as<double>() - 400.0) < 0.01);
    doc.clear(); gnss.hdop = 0.8f; agent.appendGnssStatus(doc, gnss, 61001);
    assert(doc["hacc"].isNull()); // Dimensionless HDOP is not an accuracy measurement.
    doc.clear(); agent.sensorType_ = "Unicorecomm"; agent.unicoreQualityMs_ = 61001;
    agent.unicoreHorizontalSigma_ = 0.05f;
    agent.appendGnssStatus(doc, gnss, 62001);
    assert(doc["gnss_quality"]["source"] == "unicore_bestnav_sigma");
    assert(std::abs(doc["gnss_quality"]["hacc_m"].as<double>() - 0.05) < 1e-6);
    assert(std::abs(doc["hacc"].as<double>() - 50.0) < 0.01);
    doc.clear(); agent.appendGnssStatus(doc, gnss, 106002);
    assert(doc["gnss_quality"].isNull() && doc["hacc"].isNull());
}
'''
with tempfile.TemporaryDirectory(prefix='ublox-nav-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + snapshot + agent + status + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'), '-I' + str(root / 'include'),
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: NAV-PVT/NAV-DOP decoding, validity, freshness, accuracy units and GST fallback')

# Exercise actual readback entry points with fake query boundaries; transport parsing
# and checksum validation remain owned by the existing shared UBX query.
readback = (root / 'src/functions/gnss/Ublox_Readback.cpp').read_text()
readback = readback[readback.index('bool UbloxReadback::readNavigation('):readback.index('bool UbloxReadback::readVersion(')]
query_harness = r'''
#include <Arduino.h>
#include <cassert>
#include "functions/gnss/Ublox_Readback.h"
#include "functions/gnss/Ubx_Reply.h"
uint8_t lastClass = 0, lastId = 0;
bool ok = true, badPayload = false;
bool query(uint8_t cls, uint8_t id, UbxReply &reply, String &error) {
    lastClass = cls; lastId = id;
    if (!ok) { error = "timeout"; return false; }
    const size_t size = badPayload ? 1 : id == 7 ? 92 : 18;
    reply.length = size + 8;
    if (id == 7 && size == 92) {
        reply.frame[6 + 20] = 3; reply.frame[6 + 21] = 1;
        reply.frame[6 + 23] = 11; reply.frame[6 + 40] = 50;
    }
    if (id == 4 && size == 18) reply.frame[6 + 12] = 90;
    return true;
}
'''
query_checks = r'''
int main() {
    String error;
    UbxNavigation nav;
    UbxDop dop;
    assert(UbloxReadback::readNavigation(nav, error));
    assert(lastClass == 1 && lastId == 7 && nav.valid && nav.satellites == 11 && nav.haccMm == 50);
    assert(UbloxReadback::readDop(dop, error) && lastId == 4 && dop.hdop == 90);
    badPayload = true;
    assert(!UbloxReadback::readNavigation(nav, error) && error == "Invalid NAV-PVT response");
    assert(!UbloxReadback::readDop(dop, error) && error == "Invalid NAV-DOP response");
    ok = false;
    assert(!UbloxReadback::readNavigation(nav, error) && error == "timeout");
}
'''
with tempfile.TemporaryDirectory(prefix='ublox-nav-query-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(query_harness + readback + query_checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'), '-I' + str(root / 'include'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: NAV-PVT/NAV-DOP query IDs, invalid payloads and timeout propagation')

poll_source = (root / 'src/functions/backend/Backend_Agent_Gnss.cpp').read_text()
poll = poll_source[poll_source.index('void BackendAgent::pollGnssStatus()'):]
poll_harness = r'''
#include <Arduino.h>
#include <cassert>
#include "functions/gnss/Ubx_Navigation.h"
uint32_t now = 0;
uint32_t millis() { return now; }
int reads = 0, navigationReads = 0, dopReads = 0;
bool navigationOk = true, dopOk = true;
namespace UbloxReadback {
bool readVersion(String &version, String &) { version = "ver"; return true; }
bool readSatellites(String &satellites, String &) { satellites = "sat"; return true; }
bool readNavigation(UbxNavigation &nav, String &) { ++navigationReads; nav.valid = true; nav.haccMm = 250; return navigationOk; }
bool readDop(UbxDop &dop, String &) { ++dopReads; dop.hdop = 120; return dopOk; }
}
struct BackendAgent {
    String sensorType_ = "Ublox";
    struct { bool all = false; } stationLock_;
    bool working = false;
    bool workflowActive() const { return working; }
    uint32_t lastReceiverPollMs_ = 0, navigationMs_ = 0, dopMs_ = 0, satelliteReadbackMs_ = 0;
    String satelliteReadback_, versionReadback_, versionReadbackError_;
    uint32_t receiverInfoMs_ = 0;
    UbxNavigation navigation_;
    UbxDop dop_;
    bool refreshReceiverReadback(String &) { ++reads; lastReceiverPollMs_ = millis(); return true; }
    void markStatusDirty() {}
    void pollGnssStatus();
};
'''
poll_checks = r'''
int main() {
    BackendAgent agent;
    now = 4999; agent.pollGnssStatus(); assert(reads == 0);
    now = 5000; agent.working = true; agent.pollGnssStatus(); assert(reads == 0);
    agent.working = false; agent.stationLock_.all = true; agent.pollGnssStatus(); assert(reads == 0);
    agent.stationLock_.all = false; agent.pollGnssStatus();
    assert(reads == 1 && navigationReads == 1 && dopReads == 1);
    assert(agent.navigationMs_ == 5000 && agent.dopMs_ == 5000 && agent.navigation_.haccMm == 250);
    now = 34999; agent.pollGnssStatus(); assert(reads == 1);
    now = 35000; navigationOk = false; agent.pollGnssStatus();
    assert(reads == 2 && navigationReads == 2 && dopReads == 2);
    assert(agent.navigationMs_ == 5000 && agent.dopMs_ == 35000);
    agent.sensorType_ = "Unicorecomm"; now = 65000; agent.pollGnssStatus();
    assert(reads == 3 && navigationReads == 2 && dopReads == 2);
}
'''
with tempfile.TemporaryDirectory(prefix='ublox-nav-poll-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(poll_harness + poll + poll_checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'), '-I' + str(root / 'include'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: polling cadence, workflow/lock exclusion and failed-read freshness')
