"""Exercise SOURCE targeting using the firmware's actual stream configuration code."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
commands = (root / 'src/functions/backend/Backend_Agent_Commands.cpp').read_text()
agent = (root / 'src/functions/backend/Backend_Agent.cpp').read_text()
helpers = commands[commands.index('    String normalizedStreamValue('):commands.index('\n}\n\nvoid BackendAgent::recordCommandResult(')]
stream = commands[commands.index('bool BackendAgent::applyServiceStreamCommand('):commands.index('bool BackendAgent::applyLockCommand(')]
json_helpers = agent[agent.index('    bool jsonBool('):agent.index('    bool copyJsonObject(')]
json_helpers = json_helpers.replace('const String &fallback)\n', 'const String &fallback = String())\n')
active = agent[agent.index('bool BackendAgent::effectiveStreamActive('):agent.index('bool BackendAgent::mqttConnected(')]
shim = (root / 'test/host/Arduino.h').read_text().replace('    void trim()', '''    bool startsWith(const char *s) const { return find(s) == 0; }
    void remove(size_t p, size_t n) { erase(p, n); }
    int indexOf(const String &s) const { auto p = find(s); return p == npos ? -1 : int(p); }
    void toLowerCase() { std::transform(begin(), end(), begin(), [](unsigned char c) { return std::tolower(c); }); }
    void trim()''')
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
#include <array>
constexpr size_t CONFIG_DOCUMENT_SIZE = 6144;
struct BackendAgent {
    String serviceConfig_; int saves = 0;
    bool saveStatePreferences() { ++saves; return true; }
    static bool effectiveStreamActive(const JsonObjectConst &, uint8_t, bool);
    bool applyServiceStreamCommand(JsonObject, String &);
};
'''
checks = r'''
int main() {
    const char *targets[] = {R"({"server_id":1})", R"({"server_idx":2})", R"({"server":1})",
        R"({"address":" CASTERA "})", R"({"caster_host":"casterb"})", R"({"ip":"castera"})",
        R"({"host":"casterb"})", R"({"mountpoint":"/alpha"})", R"({"mountpoint":"beta"})",
        R"({"mountpoint":"unknown"})", R"({})"};
    const int selected[] = {1, 2, 1, 1, 2, 1, 2, 1, 2, 0, 0};
    for (int demand = 0; demand < 2; ++demand) for (int choice = 0; choice < 11; ++choice) for (int active = 0; active < 2; ++active) {
        BackendAgent agent;
        DynamicJsonDocument service(4096), payload(1024), result(6144);
        assert(!deserializeJson(service, R"({"server1_enabled":true,"server2_enabled":true,"mountpoint1":"/Alpha","mountpoint2":"Beta","serverhost1":"CasterA","server2_host":"CasterB"})"));
        service["stream_on_demand"] = bool(demand);
        serializeJson(service, agent.serviceConfig_);
        assert(!deserializeJson(payload, targets[choice])); payload["active"] = bool(active);
        String error;
        assert(agent.applyServiceStreamCommand(payload.as<JsonObject>(), error) && agent.saves == 1);
        assert(!deserializeJson(result, agent.serviceConfig_));
        assert(result["stream_active"] == bool(active || !demand));
        for (int server = 1; server <= 2; ++server) {
            const String key = String("server") + String(server) + "_stream_active";
            const bool targeted = selected[choice] == server || (choice == 10 && !active);
            if (targeted && (demand || active)) {
                if (result[key] != bool(active)) std::fprintf(stderr, "demand=%d choice=%d active=%d server=%d config=%s\n", demand, choice, active, server, agent.serviceConfig_.c_str());
                assert(result[key] == bool(active));
            }
            else assert(result[key].isNull());
        }
    }
}
'''
with tempfile.TemporaryDirectory(prefix='stream-targeting-') as directory:
    path = Path(directory)
    (path / 'Arduino.h').write_text(shim)
    (path / 'check.cpp').write_text(harness + json_helpers + helpers + active + stream + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(path), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: 44 stream-targeting cases from CORS against firmware code')
