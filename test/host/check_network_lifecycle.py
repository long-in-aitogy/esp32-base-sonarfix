"""Exercise SIM fallback and recovery with production network functions."""
from pathlib import Path
import subprocess
import tempfile
from host_coverage import compile_cpp, mapped, run_cpp

root = Path(__file__).resolve().parents[2]
source = (root / 'src/main.cpp').read_text()
start = source.index('static bool tryWifiFallback(bool protocolsRunning)\n{')
end = source.index('/** @brief Implements settleModemBeforeNtrip.', start)
functions = source[start:end]
loop = source[source.index('void loop()\n{'):source.index('// Called with the shared modem mutex held once worker tasks are running.')]
harness = r'''
#include <Arduino.h>
#include <cassert>
#include <string>
constexpr int WL_CONNECTED = 1;
enum class ConnectionType { WIFI, GSM };
ConnectionType connectionType = ConnectionType::GSM;
bool wifiFallbackActive = false, wifiConnected = false, wifiOk = false, probeOk = true;
bool mqttUp = false, ntripUp = false, networkOk = true, workflowActive = false;
bool gprsUp = true, gsmOk = true, lockOk = true;
int locks = 0, unlocks = 0;
void *tcpStreamMutex = reinterpret_cast<void *>(1);
constexpr int MUTEX_TIMEOUT_MS = 1500, LED_PIN = 1, HIGH = 1, LOW = 0;
#define TCP_IP 1
#define RTCM_COMMUNICATION_PROTOCOL TCP_IP
int pdMS_TO_TICKS(int ms) { return ms; }
bool xSemaphoreTake(void *, int) { if (!lockOk) return false; ++locks; return true; }
void xSemaphoreGive(void *) { ++unlocks; }
void vTaskDelay(int) {}
void digitalWrite(int, int) {}
uint32_t now = 1000, lastSimProbeMs = 0;
int simRecoverySuccesses = 0, wifiAttempts = 0, probes = 0;
std::string events;
uint32_t millis() { return now; }
bool isWifiConnection() { return connectionType == ConnectionType::WIFI; }
bool isGsmConnection() { return connectionType == ConnectionType::GSM; }
struct WiFiClass { static int status() { return wifiConnected ? WL_CONNECTED : 0; } };
struct { void disconnect() { wifiConnected = false; events += 'D'; } } WiFi;
struct { bool connected() { return mqttUp; } void disconnect() { mqttUp = false; events += 'M'; } } mqtt;
struct { bool isNetworkConnected() { return networkOk; } bool isGprsConnected() { return gprsUp; } } modem;
struct { void onNetworkChanged() { events += 'B'; } bool workflowActive() { return ::workflowActive; } } backendAgent;
bool isNtripConnected() { return ntripUp; }
void stopNtrip() { ntripUp = false; events += 'N'; }
void setupMQTT() { events += 'Q'; }
void setupNTRIP() { events += 'S'; }
void connectNTRIP() { ntripUp = true; events += 'C'; }
bool connectGSM(int) { if (gsmOk) gprsUp = true; return gsmOk; }
bool probeMqttTransport(bool) { ++probes; return probeOk; }
bool setupWiFi(bool (*validate)()) { ++wifiAttempts; wifiConnected = wifiOk; return wifiOk && validate(); }
bool setupWiFi() { ++wifiAttempts; wifiConnected = wifiOk; return wifiOk; }
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

    // Geodetic probes SIM even while a workflow is active; a lost Wi-Fi route
    // can return to SIM after one successful probe.
    assert(tryWifiFallback(true));
    workflowActive = true; now += 60000;
    const int before = probes;
    checkSimRecovery(); assert(probes == before + 1 && isWifiConnection());
    wifiConnected = false; networkOk = false; now += 15000;
    checkSimRecovery(); assert(probes == before + 1 && isWifiConnection());
    networkOk = true; now += 14999;
    checkSimRecovery(); assert(probes == before + 1 && isWifiConnection());
    ++now; checkSimRecovery();
    assert(probes == before + 2 && isGsmConnection() && !wifiFallbackActive);

    // A failed Wi-Fi probe must leave existing SIM sockets running.
    workflowActive = false; mqttUp = ntripUp = true; wifiOk = false; events.clear();
    assert(!tryWifiFallback(true));
    assert(isGsmConnection() && mqttUp && ntripUp && events.empty());
    wifiOk = true;
    assert(tryWifiFallback(true));
    assert(isWifiConnection() && !mqttUp && ntripUp && events == "MNBQSC");

    // Run the production loop with failed and successful mutex acquisition.
    connectionType = ConnectionType::GSM; wifiFallbackActive = false;
    gprsUp = false; gsmOk = false; wifiOk = false; events.clear();
    lockOk = false; const int oldLocks = locks; loop();
    assert(locks == oldLocks && events.empty());
    lockOk = true; loop();
    assert(events == "N");
    gsmOk = true; events.clear(); loop();
    assert(gprsUp && events == "NSC");
    connectionType = ConnectionType::WIFI; wifiFallbackActive = false;
    wifiConnected = false; wifiOk = true; mqttUp = ntripUp = true; events.clear();
    loop();
    assert(wifiConnected && !mqttUp && !ntripUp && events == "MNB");
    tcpStreamMutex = nullptr; const int oldUnlocks = unlocks; loop();
    assert(unlocks == oldUnlocks && locks == unlocks);
}
'''
# Supply only a stub for diagnostic logging; it is covered separately.
log_start = functions.index('static void logNetworkStatus(bool force)')
log_end = functions.index('/** @brief Implements checkSimInternetFallback.', log_start)
functions = (mapped(root / 'src/main.cpp', functions[:log_start]) + 'static void logNetworkStatus(bool) {}\n\n' +
             mapped(root / 'src/main.cpp', functions[log_end:]))
with tempfile.TemporaryDirectory(prefix='network-lifecycle-') as directory:
    path = Path(directory)
    shim = (root / 'test/host/Arduino.h').read_text().replace('    void println(const char *) {}', '    void println(const char *) {}\n    void println(const String &) {}')
    (path / 'Arduino.h').write_text(shim)
    (path / 'check.cpp').write_text(harness + functions + mapped(root / 'src/main.cpp', loop) + checks)
    compile_cpp(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(path), str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    run_cpp([str(path / 'check')], check=True)
print('PASS: SIM fallback, workflow recovery probes and lost Wi-Fi route')
