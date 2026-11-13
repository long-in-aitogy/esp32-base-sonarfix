"""Ensure large verification statuses survive WebSocket wrapping."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent.cpp').read_text()
begin = source.index('        DynamicJsonDocument message(256);', source.index('void BackendAgent::publishStatus('))
end = source.index('\n    }', begin)
wrap = source[begin:end]
program = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
struct Socket { String sent; void sendText(const String &text) { sent = text; } } socket;
int main() {
    Socket *websocket_ = &socket;
    String payload = "{\"verification\":\"";
    payload += String(9000, 'x');
    payload += "\"}";
'''
checks = r'''
    DynamicJsonDocument decoded(12000);
    assert(!deserializeJson(decoded, socket.sent));
    assert(decoded["type"] == "status_update");
    assert(strlen(decoded["payload"]["verification"].as<const char *>()) == 9000);
}
'''
with tempfile.TemporaryDirectory(prefix='status-websocket-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(program + wrap + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: WebSocket preserves status payload larger than 8 KB')
