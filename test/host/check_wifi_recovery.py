"""Exercise the actual Wi-Fi recovery branch and its socket-close ordering."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/main.cpp').read_text()
start = source.index('        if (isWifiConnection() && WiFiClass::status() != WL_CONNECTED)', source.index('void loop()'))
end = source.index('\n        xSemaphoreGive(tcpStreamMutex);', start)
branch = source[start:end]
harness = r'''
#include <cassert>
#include <string>
std::string events;
constexpr int WL_CONNECTED=1, HIGH=1, LOW=0, LED_PIN=5;
bool wifi=true, connected=false, setupOk=true;
bool isWifiConnection() { return wifi; }
struct WiFiClass { static int status() { return connected ? WL_CONNECTED : 0; } };
void digitalWrite(int, int state) { events += state==HIGH ? "H" : "L"; }
struct { void disconnect() { events += "M"; } } mqtt;
void stopNtrip() { events += "N"; }
struct { void onNetworkChanged() { events += "B"; } } backendAgent;
bool setupWiFi() { events += "W"; return setupOk; }
void recover() {
'''
checks = r'''
}
int main() {
    recover(); assert(events=="HMNBWL");
    events.clear(); setupOk=false; recover(); assert(events=="HMNBW");
    events.clear(); connected=true; recover(); assert(events.empty());
    connected=false; wifi=false; recover(); assert(events.empty());
}
'''
with tempfile.TemporaryDirectory(prefix='wifi-recovery-') as directory:
    path=Path(directory); (path/'check.cpp').write_text(harness+branch+checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: Wi-Fi recovery closes old connections before retry and reports failed reconnect')
