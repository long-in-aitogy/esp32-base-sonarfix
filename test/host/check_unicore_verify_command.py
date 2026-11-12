"""Exercise the backend Unicore verification against simulated receiver replies."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Gnss.cpp').read_text()
begin = source.index('bool BackendAgent::verifyUnicoreConfig(')
end = source.index('\nvoid BackendAgent::saveSurveyResult(', begin)
method = source[begin:end]
shim = (root / 'test/host/Arduino.h').read_text().replace('#pragma once', '')
shim = shim.replace('    bool isEmpty() const', '''    bool startsWith(const String &value) const { return compare(0, value.size(), value) == 0; }
    bool isEmpty() const''')
harness = r'''
#include <ArduinoJson.h>
#include "functions/gnss/Unicore_Config_Verification.h"
#include <cassert>
#include <cmath>
constexpr size_t VERIFICATION_DOCUMENT_SIZE = 12288;
constexpr uint8_t GNSS_UNICORE_PORT = 0;
uint32_t millis() { return 100; }
namespace UnicoreReadback {
String mode = "MODE BASE 21 105 12";
String logs = "#UNILOGLIST,header;< 2\r\n< GPGGA COM2 1\r\n< RTCM1074 COM2 1\r\n\r\n";
bool readable = true;
bool readMode(String &out, String &error) { if (!readable) { error = "mode unavailable"; return false; } out = mode; return true; }
const char *modeKind(const String &value) { return value.startsWith("MODE BASE") ? "base" : "rover"; }
bool readLogList(String &out, String &error) { if (!readable) { error = "logs unavailable"; return false; } out = logs; return true; }
}
struct BackendAgent {
    String gnssVerification_; uint32_t gnssVerificationMs_ = 0; bool dirty = false;
    void markStatusDirty() { dirty = true; }
    bool verifyUnicoreConfig(JsonObjectConst, const String &, String &);
};
'''
checks = r'''
int main() {
    DynamicJsonDocument doc(2048), result(12288);
    JsonObject request = doc.to<JsonObject>();
    request["coords"]["lat"] = 21; request["coords"]["lon"] = 105; request["coords"]["alt"] = 12;
    request["port"] = "COM2"; request["logs"].add("GPGGA"); request["logs"].add("RTCM1074");
    BackendAgent agent; String error;
    assert(agent.verifyUnicoreConfig(request, "cmd-1", error));
    assert(!deserializeJson(result, agent.gnssVerification_));
    assert(result["state"] == "match" && result["command_id"] == "cmd-1" && agent.dirty);
    UnicoreReadback::mode = "MODE BASE 22 105 12";
    assert(agent.verifyUnicoreConfig(request, "cmd-2", error)); result.clear();
    assert(!deserializeJson(result, agent.gnssVerification_) && result["state"] == "mismatch");
    UnicoreReadback::readable = false;
    assert(agent.verifyUnicoreConfig(request, "cmd-3", error)); result.clear();
    assert(!deserializeJson(result, agent.gnssVerification_) && result["state"] == "unread");
    request["coords"]["lat"] = 999;
    assert(!agent.verifyUnicoreConfig(request, "cmd-4", error) && agent.gnssVerification_.isEmpty());
}
'''
with tempfile.TemporaryDirectory(prefix='unicore-verify-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(shim + harness + method + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'include'), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), str(root / 'src/functions/gnss/Unicore_Log.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: Unicore verification match, mismatch, unread and invalid request')
