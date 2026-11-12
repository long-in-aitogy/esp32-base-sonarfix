"""Exercise SIM fallback and recovery with production network functions."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/main.cpp').read_text()
start = source.index('static bool tryWifiFallback(bool protocolsRunning)\n{')
end = source.index('/** @brief Implements settleModemBeforeNtrip.', start)
functions = source[start:end]
harness = r'''
#include <Arduino.h>
#include <cassert>
#include <string>
constexpr int WL_CONNECTED = 1;
enum class ConnectionType { WIFI, GSM };
ConnectionType connectionType = ConnectionType::GSM;
bool wifiFallbackActive = false, wifiConnected = false, wifiOk = false, probeOk = true;
bool mqttUp = false, ntripUp = false;
uint32_t now = 1000, lastSimProbeMs = 0;
int simRecoverySuccesses = 0, wifiAttempts = 0, probes = 0;
std::string events;
uint32_t millis() { return now; }
bool isWifiConnection() { return connectionType == ConnectionType::WIFI; }
bool isGsmConnection() { return connectionType == ConnectionType::GSM; }
struct WiFiClass { static int status() { return wifiConnected ? WL_CONNECTED : 0; } };
struct { void disconnect() { wifiConnected = false; events += 'D'; } } WiFi;
struct { bool connected() { return mqttUp; } void disconnect() { mqttUp = false; events += 'M'; } } mqtt;
struct { bool isNetworkConnected() { return true; } bool isGprsConnected() { return true; } } modem;
struct { void onNetworkChanged() { events += 'B'; } bool workflowActive() { return false; } } backendAgent;
bool isNtripConnected() { return ntripUp; }
void stopNtrip() { ntripUp = false; events += 'N'; }
void setupMQTT() { events += 'Q'; }
void setupNTRIP() { events += 'S'; }
void connectNTRIP() { ntripUp = true; events += 'C'; }
bool connectGSM(int) { return true; }
bool probeMqttTransport(bool) { ++probes; return probeOk; }
bool setupWiFi(bool (*validate)()) { ++wifiAttempts; wifiConnected = wifiOk; return wifiOk && validate(); }
static void activateNetwork(ConnectionType, bool);
static void logNetworkStatus(bool = false);
'''
checks = r'''
int main() {
    checkSimInternetFallback();
    now += 29999; checkSimInternetFallback(); assert(wifiAttempts == 0);
    ++now; checkSimInternetFallback();
    assert(wifiAttempts == 1 && isGsmConnection() && events.empty());
    now += 30000; wifiOk = true; checkSimInternetFallback();
    assert(isWifiConnection() && wifiFallbackActive && events == "MNBQSC");
    now += 60000; probeOk = false; checkSimRecovery();
    assert(isWifiConnection() && simRecoverySuccesses == 0);
    now += 60000; probeOk = true; checkSimRecovery();
    assert(isWifiConnection() && simRecoverySuccesses == 1);
    now += 60000; checkSimRecovery();
    assert(isGsmConnection() && !wifiFallbackActive && !wifiConnected && events == "MNBQSCMNBQSCD");
}
'''
# Supply only a stub for diagnostic logging; it is covered separately.
log_start = functions.index('static void logNetworkStatus(bool force)')
log_end = functions.index('/** @brief Implements checkSimInternetFallback.', log_start)
functions = functions[:log_start] + 'static void logNetworkStatus(bool) {}\n\n' + functions[log_end:]
with tempfile.TemporaryDirectory(prefix='network-lifecycle-') as directory:
    path = Path(directory)
    shim = (root / 'test/host/Arduino.h').read_text().replace('    void println(const char *) {}', '    void println(const char *) {}\n    void println(const String &) {}')
    (path / 'Arduino.h').write_text(shim)
    (path / 'check.cpp').write_text(harness + functions + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(path), str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: SIM fallback delay, failed Wi-Fi, recovery probes and route transition')
