"""NTRIP must read service configurations accepted by the backend."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/ntrip/ntrip_common.cpp').read_text()
load = source[source.index('    void loadEndpoints()'):source.index('/** @brief Implements stopEndpoint.')]
capacity = source[source.index('    constexpr size_t CONFIG_DOCUMENT_SIZE'):source.index('\n', source.index('    constexpr size_t CONFIG_DOCUMENT_SIZE'))]
internal = (root / 'include/functions/backend/Backend_Agent_Internal.h').read_text()
backend_capacity = next(line for line in internal.splitlines() if 'constexpr size_t CONFIG_DOCUMENT_SIZE' in line)
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
constexpr uint8_t NTRIP_SERVER_COUNT = 2;
struct NtripEndpoint { String host; bool configured = false; } endpoints[2];
NtripEndpoint &endpointFor(uint8_t i) { return endpoints[i]; }
struct LocalNtripConfig {};
LocalNtripConfig loadLocalNtripConfig() { return {}; }
void loadEndpoint(NtripEndpoint &endpoint, uint8_t, JsonObjectConst service, bool hasConfig, const LocalNtripConfig &) {
    endpoint.configured = hasConfig; endpoint.host = hasConfig ? service["serverhost1"].as<String>() : String("legacy");
}
struct BackendAgent {
    String config;
    String serviceConfigJson() { return config; }
    static bool effectiveStreamActive(JsonObjectConst service, int, bool) { return service["stream_active"] | false; }
} backendAgent;
bool backendDeviceLocked(int) { return false; }
bool backendLicenseValid() { return true; }
bool backendDeviceProvisioned() { return true; }
bool backendBaseStartupConfigured() { return true; }
bool backendControlPlaneFailOpen() { return false; }
'''
checks = r'''
int main() {
    DynamicJsonDocument config(6144);
    config["serverhost1"] = "expected-caster";
    config["stream_active"] = false;
    config["padding"] = String(std::string(4500, 'x'));
    assert(!config.overflowed());
    serializeJson(config, backendAgent.config);
    loadEndpoints();
    assert(endpoints[0].configured && endpoints[0].host == "expected-caster");
    assert(!streamActive(0));
}
'''
with tempfile.TemporaryDirectory(prefix='ntrip-config-capacity-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + 'namespace BackendAgentInternal {\n' + backend_capacity + '\n}\n' + capacity + '\n' + load + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined', '-I' + str(root / 'test/host'),
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: NTRIP uses accepted near-capacity service configuration')
