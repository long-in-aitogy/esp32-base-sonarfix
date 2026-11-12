"""Check network diagnostics run on schedule and after a transport switch."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/main.cpp').read_text()
start = source.index('static void logNetworkStatus(bool force)\n{')
end = source.index('/** @brief Implements checkSimInternetFallback.', start)
method = source[start:end]
harness = r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <string>
uint32_t now = 0; uint32_t millis() { return now; }
bool wifi = false, wifiFallbackActive = false;
bool isWifiConnection() { return wifi; }
bool isNtripConnected() { return true; }
struct { bool connected() { return true; } } mqtt;
constexpr int WL_CONNECTED = 3;
struct Address { std::string toString() { return "192.0.2.1"; } };
struct Wifi { int status() { return WL_CONNECTED; } std::string SSID() { return "test"; } Address localIP() { return {}; } int RSSI() { return -50; } } WiFi;
struct Logger {
    int active = 0, wifi = 0;
    template<class... T> void printf(const char *format, T...) {
        if (std::strstr(format, "[NETWORK][ACTIVE]")) ++active;
        if (std::strstr(format, "[NETWORK][WIFI]")) ++wifi;
    }
} Serial;
'''
checks = r'''
int main() {
    logNetworkStatus(false); assert(Serial.active == 0);
    logNetworkStatus(true); assert(Serial.active == 1 && Serial.wifi == 0);
    now = 29999; logNetworkStatus(false); assert(Serial.active == 1);
    now = 30000; logNetworkStatus(false); assert(Serial.active == 2);
    wifi = true; wifiFallbackActive = true;
    logNetworkStatus(true); assert(Serial.active == 3 && Serial.wifi == 1);
    now = 59999; logNetworkStatus(false); assert(Serial.active == 3);
    now = 60000; logNetworkStatus(false); assert(Serial.active == 4 && Serial.wifi == 2);
}
'''
with tempfile.TemporaryDirectory(prefix='network-status-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + method + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: network status logging is rate-limited and reports transport changes')
