"""Exercise SOURCE authentication and incomplete request handling on two endpoints."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source=(root/'src/functions/ntrip/ntrip_base.cpp').read_text()
method=source[source.index('bool connectEndpoint('):source.index('/** @brief Implements ntrip_common::updateBps.')]
shim=(root/'test/host/Arduino.h').read_text().replace('#pragma once','')
shim=shim.replace('    void trim()', '''    void replace(const String &from, const String &to) { size_t p=0; while ((p=find(from,p))!=npos) { std::string::replace(p,from.size(),to); p+=to.size(); } }
    void trim()''').replace('    void println(const char *) {}','    void println(const char *) {}\n    void println(const String &) {}')
harness=r'''
#include <array>
#include <cassert>
uint32_t now=10000;
uint32_t millis() { return now; }
constexpr uint8_t NTRIP_SERVER_COUNT=2;
constexpr const char *AGENT_VERSION="test";
struct NtripEndpoint { bool enabled=true, authenticated=false; String host="host",mountpoint="mount",username="user",password="secret",lastError; uint16_t port=2101; uint8_t version=1; uint32_t lastReconnectMs=0,windowStartedMs=0,bytesInWindow=0,bytesPerSecond=0,lastKeepAliveMs=0; };
struct Client {
    bool up=false, connectOk=true, shortWrite=false; String request; unsigned waits=0;
    void stop() { up=false; } void setTimeout(int) {}
    bool connect(const char *,uint16_t) { return up=connectOk; }
    size_t print(const String &value) { request=value; return shortWrite ? value.length()-1 : value.length(); }
} clients[2];
std::array<NtripEndpoint,2> endpoints;
NtripEndpoint &endpointFor(uint8_t index) { return endpoints[index]; }
Client &clientFor(uint8_t index) { return clients[index]; }
bool streamActive(uint8_t) { return true; }
void clearEndpointState(NtripEndpoint &endpoint) { endpoint.authenticated=false; }
String base64Encode(const String &) { return "encoded"; }
bool waitForNtripResponse(Client &client,String *line) { ++client.waits; *line="ICY 200 OK"; return true; }
'''
checks=r'''
int main() {
    assert(connectEndpoint(0) && endpoints[0].authenticated);
    assert(clients[0].request.find("SOURCE secret /mount")!=String::npos);
    endpoints[1].version=2; assert(connectEndpoint(1) && endpoints[1].authenticated);
    assert(clients[1].request.find("POST /mount HTTP/1.1")!=String::npos);
    assert(clients[1].request.find("Transfer-Encoding: chunked")!=String::npos);
    clients[0].shortWrite=true; clients[0].waits=0;
    assert(!connectEndpoint(0) && !clients[0].up && !endpoints[0].authenticated);
    assert(clients[0].waits==0 && endpoints[0].lastError=="incomplete NTRIP request write");
    assert(clients[1].up && endpoints[1].authenticated);
}
'''
with tempfile.TemporaryDirectory(prefix='ntrip-source-connect-') as directory:
    path=Path(directory); (path/'check.cpp').write_text(shim+harness+method+checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: dual SOURCE authentication and incomplete request isolation')
