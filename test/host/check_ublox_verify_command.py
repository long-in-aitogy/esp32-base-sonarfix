"""Exercise u-blox verification and the fixed 5 m accuracy policy."""
from pathlib import Path
import subprocess
import tempfile
from host_coverage import compile_cpp, mapped, run_cpp
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Gnss.cpp').read_text()
a = source.index('void describeTmode(')
b = source.index('\n}', a) + 2
describe = source[a:b]
a = source.index('int ubxPortIndex(')
describe += '\n' + source[a:source.index('\n}', a) + 2]
a = source.index('int appendUbxPortValues(')
describe += '\n' + source[a:source.index('\n}', a) + 2]
a = source.index('bool matchUbxOutputValues(')
describe += '\n' + source[a:source.index('\n}', a) + 2]
a = source.index('void compareUbxOutputGroups(')
describe += '\n' + source[a:source.index('\n}', a) + 2]
a = source.index('bool BackendAgent::verifyGnssConfig(')
b = source.index('\nvoid BackendAgent::saveSurveyResult(', a)
method = source[a:b]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <array>
#include <cassert>
#include <cstring>
#include "functions/gnss/Ubx_Config_Verification.h"
constexpr size_t VERIFICATION_DOCUMENT_SIZE = 12288;
namespace GnssCmdBuilder { constexpr double BASE_ACCURACY_METERS = 5.0; }
std::array<uint8_t,40> expectedMode{}, actualMode{};
bool modeOk = true, outputOk = true, mismatch = false, missingInterface = false;
uint32_t millis() { return 100; }
size_t decodeBase64(const String &text, uint8_t *out, size_t capacity) {
    if (text == "mode" && capacity >= 40) { memcpy(out, expectedMode.data(), 40); return 40; }
    if (text == "output" && capacity >= 15) {
        const uint8_t records[] = {1,0,0x74,0x10,1,0xbb,0,0x91,0x20,1,0x69,3,0x91,0x20,1};
        memcpy(out, records, sizeof(records)); return sizeof(records);
    }
    if (text == "port" && capacity >= 20) {
        const uint8_t records[] = {5,0,0x52,0x10,1,1,0,0x74,0x10,1,0xbb,0,0x91,0x20,1,0x69,3,0x91,0x20,1};
        memcpy(out, records, sizeof(records));
        if (missingInterface) { out[0] = 4; out[1] = 0; out[2] = 0x74; out[3] = 0x10; }
        return sizeof(records);
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
    DynamicJsonDocument request(4096), result(12288); String error;
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
    modeOk=true; result.clear();
    JsonObject readback = request.createNestedObject("readback");
    JsonArray fields = readback.createNestedArray("fields");
    for (int i=0; i<4; ++i) fields.add(i);
    JsonArray ports = readback.createNestedArray("ports");
    for (const char *name : {"I2C", "UART1", "UART2", "USB", "SPI"}) {
        JsonObject port = ports.createNestedObject(); port["name"]=name; port["output_b64"]="port";
    }
    assert(agent.verifyGnssConfig(request.as<JsonObjectConst>(), "ports", error));
    assert(!deserializeJson(result, agent.gnssVerification_) && result["state"] == "match");
    missingInterface=true; result.clear();
    assert(agent.verifyGnssConfig(request.as<JsonObjectConst>(), "missing", error));
    assert(!deserializeJson(result, agent.gnssVerification_) && result["state"] == "unread");
    ports[4]["name"]="UART1";
    assert(!agent.verifyGnssConfig(request.as<JsonObjectConst>(), "duplicate", error));
    request.remove("readback");
    request["output_b64"]="bad";
    assert(!agent.verifyGnssConfig(request.as<JsonObjectConst>(), "four", error) && agent.gnssVerification_.isEmpty());
}
'''
with tempfile.TemporaryDirectory(prefix='ublox-verify-') as directory:
    path=Path(directory)
    source_path=root/'src/functions/backend/Backend_Agent_Gnss.cpp'
    (path/'check.cpp').write_text(harness+mapped(source_path,describe)+mapped(source_path,method)+checks)
    compile_cpp(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(root/'test/host'),'-I'+str(root/'include'),
                    '-I'+str(root/'.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    run_cpp([str(path/'check')],check=True)
print('PASS: u-blox verification match, mismatch, unread and 5 m accuracy')
