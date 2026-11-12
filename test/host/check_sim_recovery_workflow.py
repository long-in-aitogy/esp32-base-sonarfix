"""Do not switch a working Wi-Fi transport during a Rover workflow."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/main.cpp').read_text()
start = source.index('static void checkSimRecovery()\n{')
method = source[start:source.index('// Caller holds tcpStreamMutex', start)]
harness = r'''
#include <cstdint>
#include <cassert>
constexpr int WL_CONNECTED = 1;
uint32_t now = 120000, lastSimProbeMs = 0;
bool wifiFallbackActive = true, wifiConnected = true, active = false;
int simRecoverySuccesses = 1, switches = 0;
uint32_t millis() { return now; }
bool isWifiConnection() { return true; }
struct WiFiClass { static int status() { return wifiConnected ? WL_CONNECTED : 0; } };
struct { void disconnect() {} } WiFi;
struct { bool workflowActive() { return active; } } backendAgent;
struct { bool isNetworkConnected() { return true; } bool isGprsConnected() { return true; } } modem;
bool connectGSM(int) { return true; }
bool probeMqttTransport(bool) { return true; }
enum class ConnectionType { GSM };
void activateNetwork(ConnectionType, bool) { ++switches; }
void logNetworkStatus(bool) {}
struct { void println(const char *) {} } Serial;
'''
checks = r'''
int main() {
    active = true; checkSimRecovery();
    assert(switches == 0 && wifiFallbackActive);
    active = false; checkSimRecovery();
    assert(switches == 1 && !wifiFallbackActive);
    wifiFallbackActive = true; wifiConnected = false; active = true;
    now += 15000; checkSimRecovery();
    assert(switches == 2 && !wifiFallbackActive);
}
'''
with tempfile.TemporaryDirectory(prefix='sim-recovery-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + method + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined', str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: SIM recovery waits for workflow only while Wi-Fi is healthy')
