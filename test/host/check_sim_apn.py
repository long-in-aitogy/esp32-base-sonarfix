"""Exercise actual SIM connection APN selection with in-memory preferences."""
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[2]
source=(root/'src/hardware/Sim_handler.cpp').read_text()
method=source[source.index('bool connectGSM('):]
shim=(root/'test/host/Arduino.h').read_text().replace('#pragma once','')
shim=shim.replace('    bool isEmpty()', '    int indexOf(const char *s) const { auto p=find(s); return p==npos?-1:int(p); }\n    bool isEmpty()').replace('    void println(const char *) {}','    void println(const char *) {}\n    void println(const String &) {}')
harness=r'''
#include <cassert>
#include <map>
constexpr const char *APN="default-apn", *GPRS_USER="default-user", *GPRS_PASS="default-pass";
#define SerialMon Serial
void delay(unsigned) {}
struct {
    std::map<String,String> data;
    void begin(const char *,bool) {} void end() {}
    String getString(const char *key,const String &fallback) { return data.count(key) ? data[key] : fallback; }
} prefs;
struct {
    String provider="VIETTEL", usedApn, usedUser, usedPass;
    bool network=true, connectOk=true, gprs=false;
    String getProvider() { return provider; }
    bool isNetworkConnected() { return network; }
    bool waitForNetwork(int) { return network; }
    bool gprsConnect(const char *apn,const char *user,const char *pass) { usedApn=apn;usedUser=user;usedPass=pass;return gprs=connectOk; }
    bool isGprsConnected() { return gprs; }
} modem;
'''
checks=r'''
int main() {
    prefs.data["APN"]="custom.apn"; prefs.data["GPRS_USER"]="user"; prefs.data["GPRS_PASS"]="password";
    assert(connectGSM(1) && modem.usedApn=="custom.apn" && modem.usedUser=="user" && modem.usedPass=="password");
    prefs.data["APN"]="auto"; assert(connectGSM(1) && modem.usedApn=="v-internet");
    prefs.data["APN"]=""; modem.provider="MOBIFONE"; assert(connectGSM(1) && modem.usedApn=="m-wap");
    prefs.data.erase("APN"); modem.provider="VINAPHONE"; assert(connectGSM(1) && modem.usedApn=="m3-world");
    modem.provider="unknown"; assert(connectGSM(1) && modem.usedApn==APN);
    modem.network=false; assert(!connectGSM(1));
}
'''
with tempfile.TemporaryDirectory(prefix='sim-apn-') as directory:
    path=Path(directory); (path/'check.cpp').write_text(shim+harness+method+checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: saved APN, automatic operator APN and credentials are respected')
