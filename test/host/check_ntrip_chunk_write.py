"""Exercise the real NTRIP SOURCE chunk writer and partial socket writes."""
from pathlib import Path
import subprocess
import tempfile

root=Path(__file__).resolve().parents[2]
source=(root/'src/functions/ntrip/ntrip_base.cpp').read_text()
method=source[source.index('bool ntrip_common::sendEndpointRtcm('):source.index('\n/** @brief Implements bootstrapUM980.', source.index('bool ntrip_common::sendEndpointRtcm('))]
harness=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <string>
constexpr unsigned char HEX=16;
class String : public std::string {
public:
    using std::string::string;
    String(const std::string &s):std::string(s) {}
    String(size_t value,unsigned char base) { assert(base==HEX); char text[32]; snprintf(text,sizeof(text),"%zx",value); assign(text); }
    bool isEmpty() const { return empty(); }
};
uint32_t now=20000;
uint32_t millis() { return now; }
struct Client {
    std::string wire; int calls=0, failAt=0; bool up=true;
    size_t print(const String &s) { return output(s.data(),s.size()); }
    size_t print(const char *s) { return output(s,std::string(s).size()); }
    size_t write(const uint8_t *s,size_t size) { return output(reinterpret_cast<const char *>(s),size); }
    size_t output(const char *s,size_t size) { ++calls; size_t actual=calls==failAt && size ? size-1 : size; wire.append(s,actual); return actual; }
    void stop() { up=false; }
};
namespace ntrip_common {
struct NtripEndpoint { uint8_t version=2; uint32_t lastKeepAliveMs=0,bytesInWindow=0; bool authenticated=true; String lastError; };
void clearEndpointState(NtripEndpoint &endpoint) { endpoint.authenticated=false; endpoint.bytesInWindow=0; }
bool sendEndpointRtcm(NtripEndpoint &,Client &,const String &);
}
'''
checks=r'''
int main() {
    using namespace ntrip_common;
    NtripEndpoint endpoint; Client client;
    assert(!sendEndpointRtcm(endpoint,client,String()));
    assert(client.wire=="0\r\n\r\n" && client.up && endpoint.authenticated);
    client.wire.clear();
    assert(sendEndpointRtcm(endpoint,client,"abc"));
    assert(client.wire=="3\r\nabc\r\n" && endpoint.bytesInWindow==3);
    for (int fail=1; fail<=3; ++fail) {
        NtripEndpoint e; Client c; c.failAt=fail;
        assert(!sendEndpointRtcm(e,c,"abc"));
        assert(!c.up && !e.authenticated && c.calls==fail && !e.lastError.isEmpty());
    }
    NtripEndpoint e; e.version=1; Client c; c.failAt=1;
    assert(!sendEndpointRtcm(e,c,"abc") && !c.up && !e.authenticated);
}
'''
with tempfile.TemporaryDirectory(prefix='ntrip-chunk-') as directory:
    path=Path(directory); (path/'check.cpp').write_text(harness+method+checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-sign-compare','-fsanitize=address,undefined',str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: geodetic NTRIP keepalive and incomplete-write handling')
