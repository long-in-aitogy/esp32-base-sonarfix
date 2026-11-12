"""Province overrides require review and Fixed LLA, as in geodetic."""
from pathlib import Path
import tempfile
from host_coverage import compile_cpp, mapped, run_cpp

root = Path(__file__).resolve().parents[2]
source_path = root / 'src/functions/backend/Backend_Agent_Commands.cpp'
source = source_path.read_text()
method = source[source.index('bool BackendAgent::executeProvinceCommand('):source.index('bool BackendAgent::executeBasicCommand(')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
struct BackendAgent { bool executeProvinceCommand(JsonObject, String &, String &); };
'''
checks = r'''
int main() {
    BackendAgent agent; DynamicJsonDocument payload(256); String error, detail;
    payload["province_code"] = "HA_NOI";
    assert(!agent.executeProvinceCommand(payload.as<JsonObject>(), error, detail));
    assert(error == "Review Auto Base results and apply Fixed LLA; province overrides no longer write the receiver");
}
'''
with tempfile.TemporaryDirectory(prefix='province-command-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + mapped(source_path, method) + checks)
    compile_cpp(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                 '-I' + str(root / 'test/host'), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                 str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    run_cpp([str(path / 'check')], check=True)
print('PASS: province override requires review and does not write receiver')
