"""Run CORS-generated Unicore verification requests through firmware.

Usage: python3 test/host/check_cors_unicore_verify.py /path/to/cors
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
source = (root / 'src/functions/backend/Backend_Agent_Gnss.cpp').read_text()
a = source.index('bool BackendAgent::verifyUnicoreConfig(')
method = source[a:source.index('\nnamespace\n{', a)]
shim = (root / 'test/host/Arduino.h').read_text().replace('#pragma once', '')
shim = shim.replace('    bool isEmpty() const', '    bool startsWith(const String &value) const { return compare(0, value.size(), value) == 0; }\n    bool isEmpty() const')
harness = r'''
#include <ArduinoJson.h>
#include "functions/gnss/Unicore_Config_Verification.h"
#include <cassert>
#include <cmath>
#include <cstring>
#include <iostream>
constexpr size_t VERIFICATION_DOCUMENT_SIZE = 12288;
constexpr uint8_t GNSS_UNICORE_PORT = 0;
uint32_t millis() { return 100; }
namespace UnicoreReadback {
String mode, logs; bool readable = true;
bool readMode(String &out, String &error) { if (!readable) { error="timeout"; return false; } out=mode; return true; }
const char *modeKind(const String &value) { return value.startsWith("MODE BASE") ? "base" : "rover"; }
bool readLogList(String &out, String &error) { if (!readable) { error="timeout"; return false; } out=logs; return true; }
}
struct BackendAgent {
    String gnssVerification_; uint32_t gnssVerificationMs_ = 0;
    void markStatusDirty() {}
    bool verifyUnicoreConfig(JsonObjectConst, const String &, String &);
};
'''
checks = r'''
int main(int argc, char **argv) {
    assert(argc == 2);
    std::string line; std::getline(std::cin, line);
    DynamicJsonDocument request(8192), result(16384);
    assert(!deserializeJson(request, line));
    const bool current = request["port"] == "CURRENT";
    const String port = current ? "COM2" : "COM3";
    const String lat = request["coords"]["lat"] | "";
    const String lon = request["coords"]["lon"] | "";
    const String alt = request["coords"]["alt"] | "";
    UnicoreReadback::mode = String("MODE BASE ") + (!std::strcmp(argv[1], "position") ? String("22") : lat) + " " + lon + " " + alt;
    bool skip = !std::strcmp(argv[1], "output");
    const bool multiplePorts = !std::strcmp(argv[1], "multiple_ports");
    UnicoreReadback::logs = String("#UNILOGLIST,header;< ") + String(request["logs"].size() - (skip ? 1 : 0) + (multiplePorts ? 1 : 0)) + "\r\n";
    for (JsonVariantConst log : request["logs"].as<JsonArrayConst>()) {
        if (skip) { skip = false; continue; }
        UnicoreReadback::logs += String("< ") + log.as<String>() + " " + port + " 1\r\n";
    }
    if (multiplePorts) UnicoreReadback::logs += String("< RTCM1006 ") + (current ? "COM3" : "COM2") + " 1\r\n";
    UnicoreReadback::logs += "\r\n";
    if (!std::strcmp(argv[1], "unread")) UnicoreReadback::readable = false;
    BackendAgent agent; String error;
    assert(agent.verifyUnicoreConfig(request.as<JsonObjectConst>(), "cors", error));
    assert(!deserializeJson(result, agent.gnssVerification_));
    const char *expected = !std::strcmp(argv[1], "match") || (multiplePorts && !current) ? "match" :
                           !UnicoreReadback::readable || (multiplePorts && current) ? "unread" : "mismatch";
    if (result["state"] != expected) std::cerr << agent.gnssVerification_.c_str() << '\n';
    assert(result["state"] == expected);
    if (UnicoreReadback::readable && !(multiplePorts && current)) assert(result["details"]["compare_ports"][0] == port);
    if (multiplePorts && current) assert(result["details"]["compare_ports"].size() == 0);
}
'''
with tempfile.TemporaryDirectory(prefix='cors-unicore-verify-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(shim + harness + method + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined', '-I' + str(root / 'include'),
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'), str(path / 'check.cpp'),
                    str(root / 'src/functions/gnss/Unicore_Log.cpp'), '-o', str(path / 'check')], check=True)
    for msm in (4, 7, 'both'):
        for current in (False, True):
            config = {'base_setup_method': 'FIXED_LLA', 'coords': {'lat': '21.0849895837', 'lon': '105.7866564469', 'alt': '-7.9340'},
                      'accuracy': 5, 'gnss_options': {'output_mode': 'rtcm_only', 'msm_level': msm}}
            payload = builder.build_unicore_verification_payload(config, current_port=current)
            for scenario in ('match', 'position', 'output', 'unread', 'multiple_ports'):
                subprocess.run([str(path / 'check'), scenario], input=json.dumps(payload) + '\n', text=True, check=True)
print('PASS: real CORS Unicore payloads match simulated readback and detect mismatches')
