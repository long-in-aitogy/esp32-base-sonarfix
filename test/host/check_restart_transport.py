"""Restart closes both SOURCE connections and the active network transport."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
helper = (root / 'src/helper.cpp').read_text()
shutdown = helper[helper.index('void shutdownTcpTransportBeforeRestart()'):helper.index('String formDeviceHealthString(')]
ntrip = (root / 'src/functions/ntrip/ntrip_base.cpp').read_text()
stop = ntrip[ntrip.index('void stopNtrip()'):ntrip.index('bool isNtripConnected()')]
harness = r'''
#include <Arduino.h>
#include <cassert>
#include <string>
constexpr int NTRIP_SERVER_COUNT = 2;
std::string events;
bool gsm = true;
struct { void disconnect() { events += 'M'; } } mqtt;
struct { bool isGprsConnected() { return true; } void gprsDisconnect() { events += 'G'; } } modem;
struct { void disconnect() { events += 'W'; } } WiFi;
bool isGsmConnection() { return gsm; }
bool isWifiConnection() { return !gsm; }
void delay(int) {}
void stopEndpoint(int index) { events += char('0' + index); }
void clearNtripRoverSession() { events += 'R'; }
'''
checks = r'''
int main() {
    shutdownTcpTransportBeforeRestart(); assert(events == "M01RG");
    events.clear(); gsm = false;
    shutdownTcpTransportBeforeRestart(); assert(events == "M01RW");
}
'''
with tempfile.TemporaryDirectory(prefix='esp-restart-transport-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + stop + shutdown + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined', '-I' + str(root / 'test/host'), str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: restart closes both SOURCE endpoints, rover state and the active transport')
