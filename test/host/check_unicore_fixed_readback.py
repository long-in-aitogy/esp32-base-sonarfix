"""Exercise real Unicore BESTNAV parsing and saved Fixed LLA confirmation together."""
from pathlib import Path
import subprocess
import tempfile
from host_coverage import compile_cpp, mapped, run_cpp

root = Path(__file__).resolve().parents[2]
readback = (root / 'src/functions/gnss/Unicore_Readback.cpp').read_text()
parser = readback[readback.index('    bool readBestPosition('):readback.index('    const char *modeKind(')]
startup = (root / 'src/functions/backend/Backend_Agent_Startup.cpp').read_text()
number = startup[startup.index('    double configNumber('):startup.index('\n}\n\nbool BackendAgent::readStartupReceiverMode')]
verify = startup[startup.index('bool BackendAgent::verifyStartupReadback('):startup.index('void BackendAgent::reconcileBaseStartupReadback(')]
shim = (root / 'test/host/Arduino.h').read_text()
shim = shim.replace('    void trim()', '''    int indexOf(char value, int start) const { auto p = find(value, start); return p == npos ? -1 : int(p); }
    String substring(unsigned start, unsigned end) const { return substr(start, end - start); }
    String substring(unsigned start) const { return substr(start); }
    void remove(unsigned start) { erase(start); }
    void trim()''')

def log(latitude, kind='FIXEDPOS'):
    text = f'#BESTNAVA,header;SOL_COMPUTED,{kind},{latitude},105.75,9.5,1.0,WGS84,0.03,0.04,0.1'
    crc = 0
    for byte in text[1:].encode():
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xedb88320 if crc & 1 else 0)
    return f'{text}*{crc:08x}'

harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
#include <cmath>
#include <array>
#include <cstring>
#include "functions/gnss/gnss_cmd_builder.h"
#include "functions/gnss/Unicore_Log.h"
String response;
bool queryUnicoreLine(const char *query, const char *prefix, String &out, String &) {
    assert(!strcmp(query,"BESTNAVA") && !strcmp(prefix,"#BESTNAVA,")); out = response; return true;
}
struct BackendAgent {
    struct StartupPosition { double latitude, longitude, altitude; bool ellipsoid; };
    String receiverBaseReadback_;
    bool verifyStartupReadback(GnssCmdBuilder::GnssSensorType, bool, const StartupPosition &, String &);
};
'''
checks = r'''
int main() {
    BackendAgent agent; String error;
    BackendAgent::StartupPosition expected{21.25,105.75,10.5,true};
    auto verify = [&](const String &line) {
        response = line;
        DynamicJsonDocument doc(2048);
        doc["state"] = "ok"; doc["mode_kind"] = "base";
        JsonObject best = doc.createNestedObject("bestpos");
        if (!readBestPosition(best, error)) return false;
        agent.receiverBaseReadback_.clear(); serializeJson(doc, agent.receiverBaseReadback_);
        return agent.verifyStartupReadback(GnssCmdBuilder::GnssSensorType::Unicore, true, expected, error);
    };
    assert(verify(R"LOG(VALID)LOG"));
    assert(!verify(R"LOG(WRONG)LOG"));
    assert(error == "Receiver fixed coordinates do not match the saved coordinates");
    assert(!verify(R"LOG(NOTFIXED)LOG"));
    assert(error == "Receiver has not confirmed the saved fixed position");
    String corrupt = R"LOG(VALID)LOG"; corrupt[corrupt.size()-1] = corrupt.back() == '0' ? '1' : '0';
    assert(!verify(corrupt));
    assert(error == "Unicore BESTNAV checksum mismatch");
}
'''.replace('VALID', log('21.25')).replace('WRONG', log('21.26')).replace('NOTFIXED', log('21.25', 'SINGLE'))
with tempfile.TemporaryDirectory(prefix='unicore-fixed-readback-') as directory:
    path = Path(directory)
    (path / 'Arduino.h').write_text(shim)
    startup_path = root / 'src/functions/backend/Backend_Agent_Startup.cpp'
    (path / 'check.cpp').write_text(harness + mapped(startup_path, number) +
                                    mapped(root / 'src/functions/gnss/Unicore_Readback.cpp', parser) + mapped(startup_path, verify) + checks)
    compile_cpp(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(path), '-I' + str(root / 'include'),
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), str(root / 'src/functions/gnss/Unicore_Log.cpp'),
                    '-o', str(path / 'check')], check=True)
    run_cpp([str(path / 'check')], check=True)
print('PASS: real BESTNAV checksum and parser feed Fixed LLA verification')
