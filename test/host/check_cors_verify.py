"""Run real CORS verification payloads through firmware verification.

Usage: python3 test/host/check_cors_verify.py /path/to/cors
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
builder_path = Path(sys.argv[1]) / 'cors_dashboard/backend/app/command_builder.py'
spec = importlib.util.spec_from_file_location('cors_command_builder', builder_path)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
gnss = (root / 'src/functions/backend/Backend_Agent_Gnss.cpp').read_text()
a = gnss.index('void describeTmode(')
describe = gnss[a:gnss.index('\n}', a) + 2]
a = gnss.index('bool BackendAgent::verifyGnssConfig(')
verify = gnss[a:gnss.index('\nvoid BackendAgent::saveSurveyResult(', a)]
codec = (root / 'src/functions/backend/Backend_Agent_Codec.cpp').read_text()
decode = codec[codec.index('    int base64Value('):codec.index('    bool delayMarker(')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include "functions/gnss/Ubx_Config_Verification.h"
#include <array>
#include <cassert>
#include <cstring>
#include <iostream>
constexpr size_t VERIFICATION_DOCUMENT_SIZE = 12288;
namespace GnssCmdBuilder { constexpr double BASE_ACCURACY_METERS = 5.0; }
std::array<uint8_t, 40> actualMode{};
std::array<uint8_t, 32> actualValues{};
uint32_t millis() { return 100; }
'''
boundary = r'''
namespace UbloxReadback {
bool readTmode(uint8_t *out, String &) { memcpy(out, actualMode.data(), actualMode.size()); return true; }
bool readOutputValues(const uint8_t *, size_t length, uint8_t *out, String &) {
    for (size_t i=0; i<length/5; ++i) out[i] = actualValues[i];
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
    std::string line; std::getline(std::cin, line);
    DynamicJsonDocument request(8192), result(16384);
    assert(!deserializeJson(request, line));
    assert(decodeBase64(request["tmode_b64"] | "", actualMode.data(), actualMode.size()) == 40);
    actualMode[20]=0x50; actualMode[21]=0xc3; actualMode[22]=actualMode[23]=0;
    for (size_t i=0; i<actualValues.size(); ++i) actualValues[i] = request["readback"]["expected"][i].as<uint8_t>();
    BackendAgent agent; String error;
    assert(agent.verifyGnssConfig(request.as<JsonObjectConst>(), "cors", error));
    assert(!deserializeJson(result, agent.gnssVerification_));
    if (result["state"] != "match") std::cerr << agent.gnssVerification_.c_str() << '\n';
    assert(result["state"] == "match" && result["details"]["ports"].size() == 5);
    assert(result["details"]["fixed"]["expected"]["accuracy_m"] == 5.0);
}
'''
with tempfile.TemporaryDirectory(prefix='cors-verify-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + decode + boundary + describe + verify + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'), '-I' + str(root / 'include'),
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    for msm in (4, 7, 'both'):
        for gal, bds in ((True, False), (False, True), (True, True)):
            config = {'base_setup_method': 'FIXED_LLA', 'coords': {'lat': '21.0849895837', 'lon': '105.7866564469', 'alt': '-7.9340'},
                      'accuracy': 3, 'gnss_options': {'ports': ['USB', 'UART2'], 'output_mode': 'rtcm_only', 'msm_level': msm,
                      'constellations': {'gps': True, 'glo': True, 'gal': gal, 'bds': bds}}}
            payload = builder.build_ublox_verification_payload(config, route_to_uart1=True)
            subprocess.run([str(path / 'check')], input=json.dumps(payload) + '\n', text=True, check=True)
print('PASS: 9 real CORS verification payloads match simulated 5 m u-blox readback')
