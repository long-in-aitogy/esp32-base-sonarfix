"""Exercise the actual obsolete Wi-Fi cleanup with an in-memory NVS."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Storage_Status.cpp').read_text()
method = source[source.index('bool clearUnusedWifi('):source.index('\nbool saveMigratedWifi(')]
harness = r'''
#include <Arduino.h>
#include <cassert>
#include <map>
#include <string>
using esp_err_t = int;
using nvs_handle_t = int;
constexpr int ESP_OK=0, ESP_ERR_NVS_NOT_FOUND=1, NVS_READONLY=0, NVS_READWRITE=1;
std::map<std::string, std::string> wifi;
int openError=0, eraseError=0, commitError=0, commits=0;
esp_err_t nvs_open(const char *name, int, nvs_handle_t *handle) {
    assert(std::string(name)=="wifi_config"); *handle=1; return openError;
}
void nvs_close(nvs_handle_t) {}
esp_err_t nvs_erase_key(nvs_handle_t, const char *key) {
    if (eraseError) return eraseError;
    return wifi.erase(key) ? ESP_OK : ESP_ERR_NVS_NOT_FOUND;
}
esp_err_t nvs_commit(nvs_handle_t) { ++commits; return commitError; }
'''
checks = r'''
int main() {
    String error;
    wifi={{"profiles","old"},{"ap_pass","old"},{"other","keep"}};
    assert(clearUnusedWifi(error));
    assert(!wifi.count("profiles") && !wifi.count("ap_pass") && wifi.at("other")=="keep" && commits==1);
    assert(clearUnusedWifi(error));
    openError=ESP_ERR_NVS_NOT_FOUND; assert(clearUnusedWifi(error));
    openError=2; assert(!clearUnusedWifi(error) && !error.isEmpty());
    openError=0; eraseError=2; error.clear(); assert(!clearUnusedWifi(error) && !error.isEmpty());
    eraseError=0; commitError=2; error.clear(); assert(!clearUnusedWifi(error) && !error.isEmpty());
}
'''
with tempfile.TemporaryDirectory(prefix='nvs-cleanup-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + method + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'), str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: obsolete Wi-Fi cleanup preserves unrelated keys and reports NVS errors')
