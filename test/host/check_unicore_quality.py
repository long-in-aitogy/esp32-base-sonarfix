"""Exercise BESTNAV position/sigma parsing with a fake query boundary."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/gnss/Unicore_Readback.cpp').read_text()
method = source[source.index('    bool readBestPosition('):source.index('    const char *modeKind(')]
shim = (root / 'test/host/Arduino.h').read_text().replace('#pragma once', '')
shim = shim.replace('    void trim()', '''    int indexOf(char value, int start) const { auto p = find(value, start); return p == npos ? -1 : int(p); }
    String substring(unsigned start, unsigned end) const { return substr(start, end - start); }
    String substring(unsigned start) const { return substr(start); }
    void remove(unsigned start) { erase(start); }
    void trim()''')
harness = r'''
#include <ArduinoJson.h>
#include <array>
#include <cassert>
#include <cmath>
#include <cstdlib>
String response;
bool checksumOk = true, queryOk = true;
bool queryUnicoreLine(const char *, const char *, String &out, String &error) {
    if (!queryOk) { error = "timeout"; return false; }
    out = response; return true;
}
bool validUnicoreLogChecksum(const char *, size_t) { return checksumOk; }
'''
checks = r'''
int main() {
    DynamicJsonDocument doc(2048);
    String error;
    response = "#BESTNAVA,header;SOL_COMPUTED,FIXEDPOS,21.25,105.75,9.5,1.0,WGS84,0.03,0.04,0.1*12345678";
    assert(readBestPosition(doc.to<JsonObject>(), error));
    assert(doc["state"] == "ok" && doc["undulation"] == 1.0);
    assert(std::abs(doc["horizontal_sigma_m"].as<double>() - 0.05) < 1e-8);
    response = "#BESTNAVA,header;SOL_COMPUTED,FIXEDPOS,21.25,105.75,9.5,1.0,WGS84,-1,0.04*12345678";
    doc.clear(); assert(readBestPosition(doc.to<JsonObject>(), error));
    assert(doc["horizontal_sigma_m"].isNull());
    response = "#BESTNAVA,header;SOL_COMPUTED,FIXEDPOS,21.25,105.75,9.5,1.0,OTHER,0.03,0.04*12345678";
    doc.clear(); assert(!readBestPosition(doc.to<JsonObject>(), error));
    assert(error == "Unicore BESTNAV undulation/datum is invalid");
    checksumOk = false;
    assert(!readBestPosition(doc.to<JsonObject>(), error) && error == "Unicore BESTNAV checksum mismatch");
    queryOk = false;
    assert(!readBestPosition(doc.to<JsonObject>(), error) && error == "timeout");
}
'''
with tempfile.TemporaryDirectory(prefix='unicore-quality-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(shim + harness + method + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined',
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: BESTNAV sigma, invalid sigma/datum, checksum and timeout')

source = (root / 'src/functions/backend/Backend_Agent_Gnss.cpp').read_text()
refresh = source[source.index('bool BackendAgent::refreshUnicoreReadback('):source.index('bool BackendAgent::refreshReceiverReadback(')]
refresh_harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
#include <cinttypes>
#include <cstring>
uint32_t now = 1000;
uint32_t millis() { return now; }
bool modeOk = true, positionOk = true, sigmaPresent = true;
namespace UnicoreReadback {
bool readMode(String &mode, String &error) { mode = "MODE BASE"; error = "timeout"; return modeOk; }
const char *modeKind(const String &) { return "base"; }
bool readBestPosition(JsonObject position, String &) {
    if (!positionOk) return false;
    position["position_type"] = "FIXEDPOS";
    if (sigmaPresent) position["horizontal_sigma_m"] = 0.05;
    return true;
}
}
struct BackendAgent {
    float unicoreHorizontalSigma_ = 0;
    uint32_t unicoreQualityMs_ = 0, receiverBaseReadbackRevision_ = 0, receiverBaseReadbackMs_ = 0;
    uint32_t surveyInStartedMs_ = 0, surveyInTargetSeconds_ = 0;
    bool surveyInMonitoring_ = false, surveyInReadbackHasPosition_ = false, surveyInReadbackReady_ = false;
    String receiverBaseReadback_;
    void saveSurveyResult(JsonObject, const String &) {}
    void reconcileBaseStartupReadback() {}
    void markStatusDirty() {}
    bool refreshUnicoreReadback(String &);
};
'''
refresh_checks = r'''
int main() {
    BackendAgent agent;
    String error;
    assert(agent.refreshUnicoreReadback(error));
    assert(agent.unicoreQualityMs_ == 1000 && agent.unicoreHorizontalSigma_ > 0.049f);
    sigmaPresent = false; now = 2000;
    assert(agent.refreshUnicoreReadback(error) && agent.unicoreQualityMs_ == 0);
    sigmaPresent = true; positionOk = false; now = 3000;
    assert(agent.refreshUnicoreReadback(error) && agent.unicoreQualityMs_ == 0);
    modeOk = false; now = 4000;
    assert(!agent.refreshUnicoreReadback(error) && agent.unicoreQualityMs_ == 0);
}
'''
with tempfile.TemporaryDirectory(prefix='unicore-quality-refresh-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(refresh_harness + refresh + refresh_checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'),
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: failed or missing BESTNAV measurements invalidate old Unicore quality')
