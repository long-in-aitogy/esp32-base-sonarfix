"""Exercise u-blox verification and the fixed 5 m accuracy policy."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Gnss.cpp').read_text()
a = source.index('void describeTmode(')
b = source.index('\n}', a) + 2
describe = source[a:b]
a = source.index('bool BackendAgent::verifyGnssConfig(')
b = source.index('\nvoid BackendAgent::saveSurveyResult(', a)
method = source[a:b]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
#include <cstring>
#include "functions/gnss/Ubx_Config_Verification.h"
constexpr size_t VERIFICATION_DOCUMENT_SIZE = 12288;
namespace GnssCmdBuilder { constexpr double BASE_ACCURACY_METERS = 5.0; }
std::array<uint8_t,40> expectedMode{}, actualMode{};
bool modeOk = true, outputOk = true, mismatch = false;
uint32_t millis() { return 100; }
size_t decodeBase64(const String &text, uint8_t *out, size_t capacity) {
    if (text == "mode" && capacity >= 40) { memcpy(out, expectedMode.data(), 40); return 40; }
    if (text == "output" && capacity >= 15) {
        const uint8_t records[] = {1,0,0x74,0x10,1,0xbb,0,0x91,0x20,1,0x69,3,0x91,0x20,1};
        memcpy(out, records, sizeof(records)); return sizeof(records);
    }
    return 0;
}
namespace UbloxReadback {
bool readTmode(uint8_t *out, String &error) { if (!modeOk) { error="unread"; return false; } memcpy(out,actualMode.data(),40); return true; }
bool readOutputValues(const uint8_t *, size_t length, uint8_t *out, String &error) {
    if (!outputOk) { error="unread"; return false; }
    for (size_t i=0;i<length/5;++i) out[i] = mismatch ? 0 : 1;
    return true;
}
bool readBaud(uint8_t, uint32_t &, String &) { return false; }
}
struct BackendAgent {
    String gnssVerification_; uint32_t gnssVerificationMs_ = 0;
    void markStatusDirty() {}
    bool verifyGnssConfig(JsonObjectConst, const String &, String &);
};
'''
checks = r'''
int main() {
    expectedMode[2]=2; expectedMode[3]=1;
    // Backend may request a different accuracy; firmware compares 5 m.
    expectedMode[20]=100;
    actualMode=expectedMode; actualMode[20]=0x50; actualMode[21]=0xc3;
    DynamicJsonDocument request(512), result(12288); String error;
    request["tmode_b64"]="mode"; request["output_b64"]="output";
    BackendAgent agent;
    assert(agent.verifyGnssConfig(request.as<JsonObjectConst>(), "one", error));
    assert(!deserializeJson(result, agent.gnssVerification_) && result["state"] == "match");
    mismatch=true; result.clear();
    assert(agent.verifyGnssConfig(request.as<JsonObjectConst>(), "two", error));
    assert(!deserializeJson(result, agent.gnssVerification_) && result["state"] == "mismatch");
    mismatch=false; modeOk=false; result.clear();
    assert(agent.verifyGnssConfig(request.as<JsonObjectConst>(), "three", error));
    assert(!deserializeJson(result, agent.gnssVerification_) && result["state"] == "unread");
    request["output_b64"]="bad";
    assert(!agent.verifyGnssConfig(request.as<JsonObjectConst>(), "four", error) && agent.gnssVerification_.isEmpty());
}
'''
with tempfile.TemporaryDirectory(prefix='ublox-verify-') as directory:
    path=Path(directory)
    (path/'check.cpp').write_text(harness+describe+method+checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(root/'test/host'),'-I'+str(root/'include'),
                    '-I'+str(root/'.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: u-blox verification match, mismatch, unread and 5 m accuracy')
