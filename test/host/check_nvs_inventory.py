"""Exercise actual NVS field expansion and paging with real ArduinoJson."""
from pathlib import Path
import subprocess
import tempfile
from host_coverage import compile_cpp, mapped, run_cpp

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Storage_Status.cpp').read_text()
functions = source[source.index('bool configurationNamespace('):source.index('void describeNvsEntry(')]
saved = source[source.index('bool appendSavedConfiguration('):source.index('void appendPartitionEntries(', source.index('bool appendSavedConfiguration('))]
shim = (root / 'test/host/Arduino.h').read_text().replace('#pragma once', '')
shim = shim.replace('    bool isEmpty()', '    String substring(size_t from, size_t to) const { return String(substr(from, to - from)); }\n    bool isEmpty()')
shim = shim.replace('    bool isEmpty()', '    void toLowerCase() { std::transform(begin(), end(), begin(), [](unsigned char c) { return std::tolower(c); }); }\n    int indexOf(const char *text) const { const auto pos = find(text); return pos == npos ? -1 : int(pos); }\n    bool isEmpty()')
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
#include <cstring>
#include <memory>
struct nvs_entry_info_t { const char *namespace_name; const char *key; int type; };
constexpr int NVS_TYPE_STR = 1, NVS_READONLY = 0, ESP_OK = 0;
using nvs_handle_t = int;
String stored = R"({"gps":true,"password":"secret"})";
bool openOk = true, readOk = true; int closes = 0;
int nvs_open_from_partition(const char *, const char *, int, nvs_handle_t *handle) {
    if (!openOk) return -1;
    *handle = 1; return ESP_OK;
}
int nvs_get_str(nvs_handle_t, const char *, char *out, size_t *length) {
    if (!readOk) return -1;
    *length = stored.size() + 1;
    if (out) std::memcpy(out, stored.c_str(), *length);
    return ESP_OK;
}
void nvs_close(nvs_handle_t) { ++closes; }

'''
checks = r'''
int main() {
    nvs_entry_info_t entry{"backend", "SERVICE_JSON", NVS_TYPE_STR};
    assert(configurationJson(entry));
    nvs_entry_info_t unknown{"system", "SERVICE_JSON", NVS_TYPE_STR};
    assert(!configurationJson(unknown));
    DynamicJsonDocument config(4096), page(3072);
    deserializeJson(config, R"({"serverhost1":"caster.example","port1":2101,"password1":"never-export","nested":{"auth":{"value":"also-secret"},"gps":true},"coords":{"lat":21.125,"lon":105.75},"array":[1,2],"empty":{}})");
    uint32_t total = 0;
    auto rows = page.createNestedArray("entries");
    appendConfigurationFields(rows, 0, total, "agent_state", entry, config.as<JsonVariantConst>(), String());
    assert(total == 10 && rows.size() == 6 && !page.overflowed());
    assert(rows[0]["value"] == "caster.example" && rows[1]["value"] == "2101");
    assert(rows[2]["redacted"] == true && !rows[2].containsKey("value"));
    assert(rows[3]["redacted"] == true && !rows[3].containsKey("value"));
    assert(rows[4]["value"] == "true" && rows[5]["field"] == "coords.lat");
    String output; serializeJson(page, output);
    assert(output.indexOf("never-export") < 0 && output.indexOf("also-secret") < 0);
    page.clear(); rows = page.createNestedArray("entries"); total = 0;
    appendConfigurationFields(rows, 6, total, "agent_state", entry, config.as<JsonVariantConst>(), String());
    assert(total == 10 && rows.size() == 4 && rows[0]["field"] == "coords.lon");
    config.clear(); config["private_key"]="private-secret"; config["apiKey"]="key-secret"; config["credentials"]["user"]="credential-secret";
    page.clear(); rows = page.createNestedArray("entries"); total = 0;
    appendConfigurationFields(rows, 0, total, "agent_state", entry, config.as<JsonVariantConst>(), String());
    assert(rows.size() == 3 && rows[0]["redacted"] == true && rows[1]["redacted"] == true && rows[2]["redacted"] == true);
    output.clear(); serializeJson(page, output);
    assert(output.indexOf("private-secret") < 0 && output.indexOf("key-secret") < 0 && output.indexOf("credential-secret") < 0);
    config.clear(); config["description"] = String(200, 'x');
    page.clear(); rows = page.createNestedArray("entries"); total = 0;
    appendConfigurationFields(rows, 0, total, "agent_state", entry, config.as<JsonVariantConst>(), String());
    assert(rows[0]["truncated"] == true && rows[0]["value"].as<String>().length() == 96);
    page.clear(); rows = page.createNestedArray("entries"); total = 0;
    assert(appendSavedConfiguration(rows, 0, total, "agent_state", entry));
    assert(closes == 1 && total == 2 && rows[0]["value"] == "true" && rows[1]["redacted"] == true);
    stored = "{bad"; assert(!appendSavedConfiguration(rows, 0, total, "agent_state", entry) && closes == 2);
    stored = String(8192, 'x'); assert(!appendSavedConfiguration(rows, 0, total, "agent_state", entry) && closes == 3);
    readOk = false; assert(!appendSavedConfiguration(rows, 0, total, "agent_state", entry) && closes == 4);
    openOk = false; assert(!appendSavedConfiguration(rows, 0, total, "agent_state", entry) && closes == 4);
    assert(!appendSavedConfiguration(rows, 0, total, "agent_state", unknown) && closes == 4);
}
'''
with tempfile.TemporaryDirectory(prefix='esp-nvs-inventory-') as directory:
    path = Path(directory)
    (path / 'Arduino.h').write_text('#pragma once\n' + shim)
    (path / 'check.cpp').write_text(harness + mapped(root / 'src/functions/backend/Storage_Status.cpp', functions) + mapped(root / 'src/functions/backend/Storage_Status.cpp', saved) + checks)
    compile_cpp(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(path), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    run_cpp([str(path / 'check')], check=True)
print('PASS: saved config values, nested fields/arrays, pagination, secret redaction and truncation')
