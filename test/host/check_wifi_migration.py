"""Exercise Wi-Fi profile selection and verified migration using actual firmware functions."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
wifi = (root / 'src/hardware/Wifi_handler.cpp').read_text()
setup = wifi[wifi.index('bool setupWiFi('):]
storage = (root / 'src/functions/backend/Storage_Status.cpp').read_text()
save = storage[storage.index('bool saveMigratedWifi('):storage.index('\nnamespace {\nbool readableNvsValue')]
shim = (root / 'test/host/Arduino.h').read_text().replace('#pragma once', '')
shim = shim.replace('    bool isEmpty()', '    int indexOf(const char *text) const { const auto pos = find(text); return pos == npos ? -1 : int(pos); }\n    bool isEmpty()')
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
#include <cstring>
#include <map>
#include <memory>
constexpr int WIFI_STA=1, ESP_OK=0, NVS_READONLY=1;
constexpr const char *WIFI_SSID="fallback", *WIFI_PASSWORD="";
using nvs_handle_t=int;
String profiles, tried, triedPassword;
std::map<String, String> saved;
bool writeOk=true, connected=true, cleanupOk=true, failPasswordOnce=false; unsigned cleaned=0;
struct { void persistent(bool) {} void mode(int) {} } WiFi;
struct Preferences {
    bool begin(const char *, bool) { return true; }
    void end() {}
    bool isKey(const char *key) { return saved.count(key); }
    String getString(const char *key, const char *fallback) { return saved.count(key) ? saved[key] : String(fallback); }
    bool remove(const char *key) { return saved.erase(key); }
    size_t putString(const char *key, const String &value) { if (!writeOk) return 0; if (failPasswordOnce && !strcmp(key, "WIFI_PASS")) { failPasswordOnce=false; return 0; } saved[key]=value; return value.size(); }
};
int nvs_open(const char *, int, nvs_handle_t *handle) { *handle=1; return profiles.isEmpty() ? -1 : ESP_OK; }
int nvs_get_str(nvs_handle_t, const char *, char *out, size_t *length) {
    if (!out) { *length=profiles.size()+1; return ESP_OK; }
    memcpy(out, profiles.c_str(), *length); return ESP_OK;
}
void nvs_close(nvs_handle_t) {}
bool validWifiSsid(const String &ssid) { return !ssid.isEmpty() && ssid.size()<=32; }
bool validWifiPassword(const String &password) { return password.isEmpty() || (password.size()>=8 && password.size()<=63); }
bool clearUnusedWifi(String &) { ++cleaned; if (cleanupOk) profiles.clear(); return cleanupOk; }
bool connectWifi(const String &ssid, const String &password, bool (*validate)()) {
    tried=ssid; triedPassword=password; return connected && ssid!="bad" && (!validate || validate());
}
'''
checks = r'''
int main() {
    profiles=R"([{"ssid":"bad","password":"12345678"},{"ssid":"good","password":"abcdefgh"}])";
    assert(setupWiFi(nullptr)); assert(tried=="good" && saved["WIFI_SSID"]=="good" && profiles.isEmpty() && cleaned==1);
    profiles=R"([{"ssid":"new","password":"new-password"}])"; writeOk=false;
    assert(setupWiFi(nullptr)); assert(!profiles.isEmpty() && saved["WIFI_SSID"]=="good" && cleaned==1);
    writeOk=true; failPasswordOnce=true; assert(setupWiFi(nullptr));
    assert(saved["WIFI_SSID"]=="good" && saved["WIFI_PASS"]=="abcdefgh" && !profiles.isEmpty() && cleaned==1);
    connected=false; assert(!setupWiFi(nullptr)); assert(!profiles.isEmpty() && cleaned==1);
    connected=true; auto reject=[] { return false; }; assert(!setupWiFi(reject)); assert(!profiles.isEmpty() && cleaned==1);
    profiles.clear(); assert(setupWiFi(nullptr)); assert(tried=="good" && triedPassword=="abcdefgh" && cleaned==1);
    saved.clear(); assert(setupWiFi(nullptr)); assert(tried=="fallback" && triedPassword=="" && saved.count("WIFI_SSID") && cleaned==2);
    assert(!saveMigratedWifi("", "abcdefgh"));
    assert(!saveMigratedWifi("network", "short"));
}
'''
with tempfile.TemporaryDirectory(prefix='wifi-migration-') as directory:
    path=Path(directory); (path/'Arduino.h').write_text('#pragma once\n'+shim)
    (path/'check.cpp').write_text(harness+save+setup+checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(path),'-I'+str(root/'.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: legacy profiles migrate only after connection, validation and saved credentials')
