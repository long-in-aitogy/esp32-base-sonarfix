"""Check modem/client construction order and mux ownership using firmware initializers."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]

def function(path, signature):
    text = (root / path).read_text()
    start = text.index(signature)
    opening = text.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]

setup = function('src/main.cpp', 'void setup()')
setup_start = setup.index('(void)getModem();')
setup_end = setup.index('initializeBackendGsmClient();', setup_start) + len('initializeBackendGsmClient();')
assert setup_end < setup.index('xTaskCreatePinnedToCore(')
initializers = [
    ('src/hardware/Sim_handler.cpp', 'TinyGsm &getModem()'),
    ('src/functions/mqtt/MQTT_Manager.cpp', 'MqttGsmClient &gsmMqttClient()'),
    ('src/functions/mqtt/MQTT_Manager.cpp', 'MqttGsmClient &gsmProbeClient()'),
    ('src/functions/mqtt/MQTT_Manager.cpp', 'void initializeMqttGsmClients()'),
    ('src/functions/ntrip/ntrip_common.cpp', 'TinyGsmClient &gsmNtripClient1()'),
    ('src/functions/ntrip/ntrip_common.cpp', 'TinyGsmClient &gsmNtripClient2()'),
    ('src/functions/ntrip/ntrip_common.cpp', 'void initializeGsmClients()'),
    ('src/functions/backend/Backend_Agent.cpp', 'TinyGsmClient &backendWebsocketGsmClient()'),
    ('src/functions/backend/Backend_Agent.cpp', 'void initializeBackendGsmClient()'),
]
parts = [function(*entry) for entry in initializers]
harness = r'''
#include <cassert>
int Serial2 = 0;
#define SerialAT Serial2
int modemCount = 0;
int clientCounts[5] = {};
struct TinyGsm { explicit TinyGsm(int &) { ++modemCount; } };
struct TinyGsmClient {
    TinyGsmClient(TinyGsm &, int mux) { assert(modemCount == 1); ++clientCounts[mux]; }
};
using MqttGsmClient = TinyGsmClient;
'''
program = harness + parts[0] + '\n' + '\n'.join(parts[1:4])
program += '\nnamespace ntrip_common {\n' + '\n'.join(parts[4:7]) + '\n}\n'
program += '\n' + '\n'.join(parts[7:])
program += '\nint main() {\n' + setup[setup_start:setup_end]
program += '\nassert(modemCount == 1); for (int n : clientCounts) assert(n == 1);\n'
program += setup[setup_start:setup_end]
program += '\nassert(modemCount == 1); for (int n : clientCounts) assert(n == 1); }\n'
with tempfile.TemporaryDirectory(prefix='modem-init-') as directory:
    source = Path(directory) / 'check.cpp'
    binary = Path(directory) / 'check'
    source.write_text(program)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print('PASS: modem initializes before five unique clients, once, before tasks')
