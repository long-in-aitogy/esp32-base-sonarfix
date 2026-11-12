"""Reject invalid SOURCE ports rather than connecting to a fallback port."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/ntrip/ntrip_common.cpp').read_text()
method = source[source.index('uint16_t endpointPort('):source.index('/** @brief Implements base64Encode.')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
#include <cstdlib>
'''
checks = r'''
int main() {
    DynamicJsonDocument doc(512);
    JsonObject service = doc.to<JsonObject>();
    assert(endpointPort(service, 0, 2200) == 2200 && endpointPort(service, 1, 2200) == 2101);
    service["port1"] = 65535; assert(endpointPort(service, 0, 2200) == 65535);
    service["port1"] = "2102"; assert(endpointPort(service, 0, 2200) == 2102);
    for (int port : {0, -1, 65536, 70000}) {
        service["port1"] = port; assert(endpointPort(service, 0, 2200) == 0);
    }
    service["port1"] = "2102bad"; assert(endpointPort(service, 0, 2200) == 0);
    service["port1"] = true; assert(endpointPort(service, 0, 2200) == 0);
    service.remove("port1"); service["serverport1"] = 2300;
    assert(endpointPort(service, 0, 2200) == 2300);
    service.remove("serverport1"); service["port"] = 2400;
    assert(endpointPort(service, 0, 2200) == 2400);
    service["port2"] = 70000; assert(endpointPort(service, 1, 2200) == 0);
}
'''
with tempfile.TemporaryDirectory(prefix='ntrip-port-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + method + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'),
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: missing SOURCE port uses defaults; invalid explicit port disables endpoint')
