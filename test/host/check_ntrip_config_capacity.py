"""NTRIP must read service configurations accepted by the backend."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/ntrip/ntrip_common.cpp').read_text()
load = source[source.index('    void loadEndpoints()'):source.index('/** @brief Implements stopEndpoint.')]
helpers = source[source.index('bool jsonBool('):source.index('struct LocalNtripConfig')]
endpoints = source[source.index('String endpointHost('):source.index('/** @brief Implements base64Encode.')]
loader = source[source.index('    void normalizeEndpoint('):source.index('/** @brief Implements loadEndpoints.')]
capacity = source[source.index('    constexpr size_t CONFIG_DOCUMENT_SIZE'):source.index('\n', source.index('    constexpr size_t CONFIG_DOCUMENT_SIZE'))]
internal = (root / 'include/functions/backend/Backend_Agent_Internal.h').read_text()
backend_capacity = next(line for line in internal.splitlines() if 'constexpr size_t CONFIG_DOCUMENT_SIZE' in line)
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
#include <cstdlib>
constexpr uint8_t NTRIP_SERVER_COUNT = 2;
struct NtripEndpoint { String host, mountpoint, username, password; uint16_t port = 0; uint8_t version = 0; bool enabled = true; } endpoints[2];
NtripEndpoint &endpointFor(uint8_t i) { return endpoints[i]; }
struct LocalNtripConfig { String host = "legacy", mountpoint = "/LEGACY", password = "legacy-password"; uint16_t port = 2101; };
LocalNtripConfig loadLocalNtripConfig() { return {}; }
bool locked = false, licensed = true, provisioned = true, configured = true;
struct BackendAgent {
    String config;
    String serviceConfigJson() { return config; }
    static bool effectiveStreamActive(JsonObjectConst service, int, bool) { return service["stream_active"] | false; }
} backendAgent;
bool backendDeviceLocked(int) { return locked; }
bool backendLicenseValid() { return licensed; }
bool backendDeviceProvisioned() { return provisioned; }
bool backendBaseStartupConfigured() { return configured; }
bool backendControlPlaneFailOpen() { return false; }
'''
checks = r'''
int main() {
    DynamicJsonDocument config(6144);
    config["serverhost1"] = "expected-caster";
    config["server1_enabled"] = true; config["mountpoint1"] = "/ONE";
    config["server2_enabled"] = true; config["serverhost2"] = "second";
    config["mountpoint2"] = "TWO"; config["port2"] = 2201; config["ntrip_version2"] = 2;
    config["stream_active"] = false;
    config["padding"] = String(std::string(4500, 'x'));
    assert(!config.overflowed());
    serializeJson(config, backendAgent.config);
    loadEndpoints();
    assert(endpoints[0].enabled && endpoints[0].host == "expected-caster" && endpoints[0].mountpoint == "ONE");
    assert(endpoints[1].enabled && endpoints[1].host == "second" && endpoints[1].port == 2201 && endpoints[1].version == 2);
    assert(!streamActive(0));
    backendAgent.config = String("{\"legacy\":\"") + String(std::string(7000, 'x')) + "\"}";
    loadEndpoints();
    assert(!endpoints[0].enabled && !endpoints[1].enabled && !streamActive(0));
    backendAgent.config = "bad"; loadEndpoints();
    assert(endpoints[0].enabled && endpoints[0].host == "legacy" && endpoints[0].mountpoint == "LEGACY" && !endpoints[1].enabled);
    assert(streamActive(0) && !streamActive(1));
    locked = true; assert(!streamActive(0)); locked = false;
    licensed = false; assert(!streamActive(0)); licensed = true;
    provisioned = false; assert(!streamActive(0)); provisioned = true;
    configured = false; assert(!streamActive(0)); configured = true;
    backendAgent.config = "{}"; loadEndpoints(); assert(!endpoints[0].enabled && !endpoints[1].enabled);
}
'''
with tempfile.TemporaryDirectory(prefix='ntrip-config-capacity-') as directory:
    path = Path(directory)
    shim = (root / 'test/host/Arduino.h').read_text().replace('    void trim()', '    bool startsWith(const char *s) const { return find(s) == 0; }\n    void remove(size_t p, size_t n) { erase(p, n); }\n    void trim()')
    (path / 'Arduino.h').write_text(shim)
    (path / 'check.cpp').write_text(harness + helpers + endpoints + loader + 'namespace BackendAgentInternal {\n' + backend_capacity + '\n}\n' + capacity + '\n' + load + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined', '-I' + str(path),
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: real NTRIP endpoint loading, gating and service configuration capacity')
