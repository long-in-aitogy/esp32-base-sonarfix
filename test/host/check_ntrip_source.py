"""Exercise real endpoint loading, SOURCE authentication and publishing gates."""
from pathlib import Path
import tempfile
from host_coverage import compile_cpp, run_cpp, mapped

root = Path(__file__).resolve().parents[2]
path = root / 'src/functions/ntrip/NTRIP_Handler_IP.cpp'
source = path.read_text()
def section(start, end):
    return mapped(path, source[source.index(start):source.index(end)])
shim = (root / 'test/host/Arduino.h').read_text().replace('#pragma once', '')
shim = shim.replace('    void trim() {', '''    int indexOf(const char *s) const { auto p=find(s);return p==npos?-1:int(p); }
    int indexOf(char c, int start) const { auto p=find(c,start);return p==npos?-1:int(p); }
    bool startsWith(const char *s) const { return find(s)==0; }
    void remove(size_t start, size_t count) { erase(start,count); }
    void replace(const String &from, const String &to) { size_t p=0;while((p=find(from,p))!=npos){std::string::replace(p,from.size(),to);p+=to.size();} }
    void trim() {''')
shim = shim.replace('void println(const char *) {}', 'template<class T> void println(const T &) {}')
harness = r'''
#include <cassert>
#include <cstring>
#include <map>
#include <ArduinoJson.h>
bool roverSessionActive=true, roverSessionAuthenticated=true;
unsigned roverLastGgaMs=0;
unsigned now=10000;
uint32_t millis(){return now;}
void delay(unsigned ms){now+=ms;}
constexpr unsigned NTRIP_CASTER_PORT=2101;
constexpr const char *NTRIP_CASTER_ADDRESS="legacy", *NTRIP_MOUNTPOINT="/LEGACY", *NTRIP_AUTH_BASE_STATION="legacy-value", *AGENT_VERSION="test";
struct {
    std::map<String,String> values;
    void begin(const char*,bool){} void end(){}
    String getString(const char*k,const String&v){return values.count(k)?values[k]:v;}
    uint16_t getUShort(const char*,unsigned v){return v;}
} prefs;
bool locked=false, licensed=true, provisioned=true, configured=true, effective=true;
bool backendDeviceLocked(unsigned){return locked;}
bool backendLicenseValid(){return licensed;}
bool backendDeviceProvisioned(){return provisioned;}
bool backendBaseStartupConfigured(){return configured;}
bool backendControlPlaneFailOpen(){return false;}
struct BackendAgent {
    String config="{}";
    String serviceConfigJson(){return config;}
    static bool effectiveStreamActive(JsonObjectConst,unsigned,bool){return effective;}
} backendAgent;
bool jsonBool(JsonObjectConst o,const String&k,bool fallback){return o[k].isNull()?fallback:o[k].as<bool>();}
String jsonString(JsonObjectConst o,const String&k,const String&fallback=String()){return o[k].isNull()?fallback:o[k].as<String>();}
String encodeBase64(const String&){return "encoded";}
struct Client {
    String wire="ICY 200 OK\r\n", request;
    size_t offset=0;
    bool up=false, accept=true;
    void stop(){up=false;} void setTimeout(unsigned){}
    bool connect(const char*,unsigned){offset=0;return up=accept;}
    bool connected(){return up;} int available(){return up&&offset<wire.size();}
    int read(){return available()?uint8_t(wire[offset++]):-1;}
    void print(const String&s){request=s;}
} clients[2];
Client&clientFor(uint8_t i){return clients[i];}
bool ntripServerConnected(uint8_t);
'''
checks = r'''
int main(){
    (void)RECONNECT_INTERVAL_MS;
    backendAgent.config="bad"; loadEndpoints();
    assert(endpoints[0].enabled&&endpoints[0].host=="legacy"&&endpoints[0].mountpoint=="LEGACY");
    assert(!endpoints[1].enabled);
    assert(streamActive(0)&&!streamActive(1));
    backendAgent.config="{}"; loadEndpoints(); assert(!endpoints[0].enabled);
    backendAgent.config=R"({"server1_enabled":true,"serverhost1":"first","port1":2101,"mountpoint1":"///ONE","password1":"source-value","server2_enabled":true,"serverhost2":"second","port2":2201,"mountpoint2":"TWO","username2":"custom","password2":"other-value","ntrip_version2":2})";
    const String validConfig=backendAgent.config;
    loadEndpoints();
    assert(endpoints[0].mountpoint=="ONE"&&endpoints[1].port==2201&&endpoints[1].enabled);
    assert(!streamActive(2));
    locked=true;assert(!streamActive(0));locked=false;
    licensed=false;assert(!streamActive(0));licensed=true;
    provisioned=false;assert(!streamActive(0));provisioned=true;
    configured=false;assert(!streamActive(0));configured=true;
    effective=false;assert(!streamActive(0)&&!connectEndpoint(0));effective=true;
    assert(!connectEndpoint(2));
    assert(connectEndpoint(0));
    assert(clients[0].request.find("SOURCE source-value /ONE")!=String::npos);
    assert(endpoints[0].authenticated&&endpoints[0].lastError.isEmpty());
    assert(connectEndpoint(1));
    assert(clients[1].request.find("POST /TWO HTTP/1.1")!=String::npos);
    assert(clients[1].request.find("Transfer-Encoding: chunked")!=String::npos);
    assert(now==10000); // Successful dual SOURCE ACKs never wait 20 seconds.
    endpoints[0].bytesInWindow=250; now+=1000; updateBps(endpoints[0]);
    assert(endpoints[0].bytesPerSecond==250&&endpoints[0].bytesInWindow==0);
    stopEndpoint(0);assert(!clients[0].up&&!endpoints[0].authenticated);
    clients[0].accept=false;assert(!connectEndpoint(0));
    assert(endpoints[0].lastError=="TCP connection failed");
    clients[0].accept=true;clients[0].wire="HTTP/1.1 401 source-value\r\n\r\n";
    assert(!connectEndpoint(0)&&!clients[0].up);
    assert(endpoints[0].lastError.find("source-value")==String::npos);
    assert(endpoints[0].lastError.find("[redacted]")!=String::npos);
    backendAgent.config=R"({"server1_enabled":true,"serverhost1":"bad\r\nHost: injected","mountpoint1":"ONE"})";
    loadEndpoints();assert(!endpoints[0].enabled&&!connectEndpoint(0));
    assert(!safeNtripField("x\n")&&!safeNtripField("x\r"));
    endpoints[0].windowStartedMs=0;updateBps(endpoints[0]);
    assert(endpoints[0].windowStartedMs==now);
    backendAgent.config=validConfig; clients[0]=Client{}; clients[1]=Client{};
    assert(setupNTRIP()==0);
    assert(&activeNtripClient()==&clients[0]);
    assert(connectNTRIP()==0&&isNtripConnected());
    assert(ntripServerConnected(1)&&ntripServerConnected(2));
    assert(!ntripServerConnected(0)&&!ntripServerConnected(3));
    endpoints[0].bytesInWindow=120;now+=1000;
    assert(ntripServerBps(1)==120&&ntripServerBps(0)==0);
    endpoints[1].lastError="diagnostic";
    assert(ntripServerError(2)=="diagnostic"&&ntripServerError(3).isEmpty());
    stopNtrip();
    assert(!isNtripConnected()&&!roverSessionActive&&!roverSessionAuthenticated);
    clients[0].accept=clients[1].accept=false;
    assert(connectNTRIP()==-1);
}
'''
production = section('bool safeNtripField(', 'NtripEndpoint endpoints[')
production += 'NtripEndpoint endpoints[NTRIP_SERVER_COUNT];\n'
production += section('void clearEndpointState(', 'bool waitForNtripResponse(')
production += section('bool waitForNtripResponse(', 'void sendRoverGgaIfAvailable(')
production += section('bool connectEndpoint(', '} // namespace')
production += section('Client &activeNtripClient()', 'static bool sendEndpointRtcm(')
production += section('void stopNtrip()', 'bool startNtripRover(')
with tempfile.TemporaryDirectory(prefix='ntrip-source-') as directory:
    build = Path(directory)
    (build / 'check.cpp').write_text(shim+harness+production+checks)
    compile_cpp(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                 '-I'+str(root/'.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                 str(build/'check.cpp'),'-o',str(build/'check')],check=True)
    run_cpp([str(build/'check')],check=True)
print('PASS: legacy/configured endpoints, two SOURCE protocols, publish gates, ACK timing, TCP/auth failure, secret redaction, injection and bitrate')
