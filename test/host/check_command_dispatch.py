"""Exercise legacy command routing after the upstream extraction."""
from pathlib import Path
import tempfile
from host_coverage import compile_cpp, run_cpp, mapped

root = Path(__file__).resolve().parents[2]
path = root / 'src/functions/system/cmd_handler.cpp'
source = path.read_text()
esp_functions = 'static cmd_action_t handleEspConnectionSet(' + source.split('static cmd_action_t handleEspConnectionSet(', 1)[1].split('cmd_action_t handleMqttCommand(', 1)[0]
functions = 'cmd_action_t handleGnssCommand(' + source.split('cmd_action_t handleGnssCommand(', 1)[1]
shim = r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <string>
#include <vector>
struct String : std::string {
    using std::string::string;
    String(const std::string &s) : std::string(s) {}
    long toInt() const { return strtol(c_str(), nullptr, 10); }
};
enum cmd_action_t { CMD_ACTION_NONE, CMD_ACTION_ESP_RESTART };
struct { String last; void println(const String &s) { last = s; } } Serial;
struct { bool active = false; int calls = 0; bool workflowActive() { return active; }
         bool applyRoverMode() { ++calls; return true; } } backendAgent;
struct { int writes = 0; void begin(const char *, bool) {} void end() {}
         void putBool(const char *, bool) { ++writes; } } prefs;
int base = 0, set = 0;
cmd_action_t handleGnssBaseCommand(const std::vector<String> &v) { ++base; assert(v.size() == 1 && v[0] == "X"); return CMD_ACTION_NONE; }
cmd_action_t handleGnssSetCommand(const std::vector<String> &v) { ++set; assert(v.size() == 2 && v[0] == "SET"); return CMD_ACTION_NONE; }
namespace cmd_helper {
    int wifiWrites = 0, stringWrites = 0; bool lastSsid = false;
    bool hasExactArgumentCount(const std::vector<String> &v, size_t n, const char *) { return v.size() == n; }
    cmd_action_t saveWifiSetting(bool ssid, const String &) { ++wifiWrites; lastSsid = ssid; return CMD_ACTION_NONE; }
    cmd_action_t saveStringPreference(const char *, const String &) { ++stringWrites; return CMD_ACTION_NONE; }
    cmd_action_t saveUShortPreference(const char *, unsigned short) { return CMD_ACTION_NONE; }
}
cmd_action_t handleMqttCommand(const std::vector<String> &) { return CMD_ACTION_NONE; }
cmd_action_t handleNtripCommand(const std::vector<String> &) { return CMD_ACTION_NONE; }
'''
checks = r'''
int main() {
    assert(handleEspCommand({"SET", "CONNECTION", "4G"}) == CMD_ACTION_ESP_RESTART);
    assert(handleEspCommand({"SET", "CONNECTION", "WIFI"}) == CMD_ACTION_ESP_RESTART);
    handleEspCommand({"SET", "WIFI", "SSID", "test"});
    assert(cmd_helper::wifiWrites == 1 && cmd_helper::lastSsid);
    handleEspCommand({"SET", "WIFI", "PASS", "test"});
    assert(cmd_helper::wifiWrites == 2 && !cmd_helper::lastSsid);
    handleEspCommand({"SET", "WIFI"}); assert(cmd_helper::wifiWrites == 2);

    std::vector<String> incomplete = {"ATG", "GNSS"};
    assert(handleCommand(incomplete) == CMD_ACTION_NONE && Serial.last.find("Incomplete") != String::npos);
    std::vector<String> rover = {"ATG", "GNSS", "ROVER"};
    backendAgent.active = true; handleCommand(rover); assert(backendAgent.calls == 0);
    backendAgent.active = false; handleCommand(rover); assert(backendAgent.calls == 1);
    std::vector<String> b = {"ATG", "GNSS", "BASE", "X"}; handleCommand(b); assert(base == 1);
    std::vector<String> s = {"ATG", "GNSS", "SET", "X"}; handleCommand(s); assert(set == 1);
    std::vector<String> unknown = {"ATG", "CONFIG", "BAD"}; handleCommand(unknown);
    assert(Serial.last.find("Unknown command") != String::npos && prefs.writes == 0);
    std::vector<String> reset = {"ATG", "CONFIG", "RESET"};
    assert(handleCommand(reset) == CMD_ACTION_ESP_RESTART && prefs.writes == 1);
}
'''
with tempfile.TemporaryDirectory(prefix='command-dispatch-') as directory:
    build = Path(directory)
    (build / 'check.cpp').write_text(shim + mapped(path, esp_functions) + mapped(path, functions) + checks)
    compile_cpp(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                 str(build / 'check.cpp'), '-o', str(build / 'check')], check=True)
    run_cpp([str(build / 'check')], check=True)
print('PASS: GNSS and CONFIG command routing')
