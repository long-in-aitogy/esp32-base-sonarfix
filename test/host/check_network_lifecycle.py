"""Exercise the complete Wi-Fi/SIM network manager with controlled routes and clock."""
from pathlib import Path
import re
import tempfile
from host_coverage import compile_cpp, run_cpp, mapped

root = Path(__file__).resolve().parents[2]
source_path = root / 'src/hardware/Network_Manager.cpp'
source = re.sub(r'^#include.*$', '', source_path.read_text(), flags=re.M)
harness = r'''
#include <Arduino.h>
#include <cassert>
#include <functional>
enum class ConnectionType{WIFI,GSM};
ConnectionType connectionType=ConnectionType::WIFI;
bool isWifiConnection(){return connectionType==ConnectionType::WIFI;}
bool isGsmConnection(){return connectionType==ConnectionType::GSM;}
using SemaphoreHandle_t=void*;
void *tcpStreamMutex=reinterpret_cast<void*>(1);
constexpr unsigned MUTEX_TIMEOUT_MS=1500,LED_PIN=1,HIGH=1,LOW=0,WL_CONNECTED=3;
#define TCP_IP 1
#define RTCM_COMMUNICATION_PROTOCOL TCP_IP
uint32_t now=1000;unsigned locks=0,unlocks=0,stopped=0,configured=0,changed=0,maintains=0,wifiAttempts=0,probes=0;
bool wifiUp=true,wifiOk=true,gsmOk=true,simOk=true,networkOk=true,gprsUp=true,probeOk=true;
uint32_t millis(){return now;}void delay(unsigned ms){now+=ms;}
unsigned pdMS_TO_TICKS(unsigned n){return n;}
bool xSemaphoreTake(void*,unsigned){++locks;return true;}void xSemaphoreGive(void*){++unlocks;}
void digitalWrite(unsigned,unsigned){}
struct WifiClass {
    static unsigned status(){return wifiUp?WL_CONNECTED:0;}
    void disconnect(){wifiUp=false;}
    String SSID(){return "test-network";}int RSSI(){return -55;}
    struct Address{String toString(){return "192.0.2.1";}};
    Address localIP(){return {};}
} WiFi;
using WiFiClass=WifiClass;
struct {bool up=true;bool connected(){return up;}void disconnect(){up=false;}}mqtt;
bool ntripUp=true;
bool isNtripConnected(){return ntripUp;}
void stopNtrip(){++stopped;ntripUp=false;}
void setupNTRIP(){++configured;}void connectNTRIP(){ntripUp=true;}void setupMQTT(){}
bool startSIM(){return simOk;}
bool connectGSM(unsigned){if(gsmOk)gprsUp=true;return gsmOk;}
bool probeMqttTransport(bool){++probes;return probeOk;}
bool setupWiFi(std::function<bool()> validate={}){++wifiAttempts;wifiUp=wifiOk;return wifiOk&&(!validate||validate());}
struct {bool isNetworkConnected(){return networkOk;}bool isGprsConnected(){return gprsUp;}void maintain(){++maintains;}}modem;
struct {void onNetworkChanged(){++changed;}}backendAgent;
'''
checks = r'''
int main(){
    NetworkManager::connect();assert(isWifiConnection()&&configured==1);
    connectionType=ConnectionType::GSM;gprsUp=false;NetworkManager::connect();
    assert(isGsmConnection()&&maintains==30&&gprsUp);
    simOk=false;NetworkManager::connect();
    assert(isWifiConnection()&&wifiFallbackActive&&changed>=1);
    unsigned before=probes;NetworkManager::maintain();assert(probes==before);
    now+=60000;probeOk=false;NetworkManager::maintain();assert(isWifiConnection()&&simRecoverySuccesses==0);
    probeOk=true;now+=60000;NetworkManager::maintain();assert(isWifiConnection()&&simRecoverySuccesses==1);
    now+=60000;NetworkManager::maintain();assert(isGsmConnection()&&!wifiFallbackActive&&!wifiUp);
    gprsUp=false;wifiOk=false;unsigned previous=configured;
    NetworkManager::maintain();assert(isGsmConnection()&&gprsUp&&configured==previous+1);
    mqtt.up=false;ntripUp=false;NetworkManager::maintain();
    now+=29000;before=wifiAttempts;NetworkManager::maintain();assert(wifiAttempts==before);
    now+=1001;wifiOk=true;NetworkManager::maintain();
    assert(isWifiConnection()&&wifiFallbackActive);
    networkOk=false;now+=60000;NetworkManager::maintain();assert(isWifiConnection());
    networkOk=true;wifiUp=false;now+=15000;NetworkManager::maintain();
    assert(isGsmConnection()&&!wifiFallbackActive);
    connectionType=ConnectionType::WIFI;wifiFallbackActive=false;wifiUp=false;before=wifiAttempts;
    NetworkManager::maintain();assert(wifiAttempts==before+1&&wifiUp);
    NetworkManager::checkInternetFallback();NetworkManager::logStatus();
    tcpStreamMutex=nullptr;before=locks;NetworkManager::maintain();assert(locks==before);
    assert(locks==unlocks);
}
'''
with tempfile.TemporaryDirectory(prefix='network-lifecycle-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + mapped(source_path, source, stripped_includes=True) + checks)
    compile_cpp(['c++','-std=c++17','-fsanitize=address,undefined','-I'+str(root/'test/host'),
                 str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    run_cpp([str(path/'check')],check=True)
print('PASS: complete network manager startup, SIM settling, fallback delay, recovery hysteresis, lost routes and lock balance')
