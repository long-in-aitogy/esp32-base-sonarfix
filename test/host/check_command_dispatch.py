"""Exercise legacy command routing using the production dispatch functions."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/cmd_handler.cpp').read_text()
functions = source[source.index('cmd_action_t handleEspConnectionSet('):]
shim = (root / 'test/host/Arduino.h').read_text().replace('#pragma once', '')
shim = shim.replace('    bool isEmpty()', '    long toInt() const { return std::strtol(c_str(), nullptr, 10); }\n    bool isEmpty()')
shim = shim.replace('    void println(const char *) {}', '    void println(const char *) {}\n    void println(const String &) {}')
harness = r'''
#include <array>
#include <cassert>
#include <cstdlib>
#include <vector>
#include "hardware/Wifi_Credentials.h"
enum class cmd_action_t { CMD_ACTION_NONE, CMD_ACTION_ESP_RESTART };
struct { bool active = false; int calls = 0; bool workflowActive() { return active; }
         bool applyRoverMode() { ++calls; return true; } } backendAgent;
struct { int writes = 0; void begin(const char *, bool) {} void end() {}
         void putBool(const char *, bool) { ++writes; } } prefs;
int baseCalls = 0, setCalls = 0; String savedKey, savedValue;
cmd_action_t handleGnssBaseCommand(const std::vector<String> &v) { ++baseCalls; assert(v.size() == 1 && v[0] == "X"); return cmd_action_t::CMD_ACTION_NONE; }
cmd_action_t handleGnssSetCommand(const std::vector<String> &v) { ++setCalls; assert(v.size() == 2 && v[0] == "SET"); return cmd_action_t::CMD_ACTION_NONE; }
namespace cmd_helper {
struct PreferenceMapping { const char *command, *preferenceKey; };
bool hasExactArgumentCount(const std::vector<String> &v, size_t n, const char *) { return v.size() == n; }
const char *findPreferenceKey(const String &key, const PreferenceMapping *map, size_t size) {
    for (size_t i = 0; i < size; ++i) if (key == map[i].command) return map[i].preferenceKey;
    return nullptr;
}
cmd_action_t saveStringPreference(const char *key, const String &value) { savedKey = key; savedValue = value; return cmd_action_t::CMD_ACTION_NONE; }
cmd_action_t saveUShortPreference(const char *key, uint16_t value) { savedKey = key; savedValue = String(value); return cmd_action_t::CMD_ACTION_NONE; }
}
'''
checks = r'''
int main() {
    using A = cmd_action_t;
    assert(handleEspCommand({"SET", "CONNECTION", "4G"}) == A::CMD_ACTION_ESP_RESTART && savedValue == "4G");
    assert(handleEspCommand({"SET", "CONNECTION", "WIFI"}) == A::CMD_ACTION_ESP_RESTART && savedValue == "WIFI");
    assert(handleEspCommand({"SET", "CONNECTION"}) == A::CMD_ACTION_NONE);
    std::vector<String> wifi = {"ATG", "ESP", "SET", "WIFI", "SSID", "station"};
    assert(handleCommand(wifi) == A::CMD_ACTION_NONE && savedKey == "WIFI_SSID" && savedValue == "station");
    std::vector<String> mqtt = {"ATG", "MQTT", "SET", "SERVER", "broker"};
    assert(handleCommand(mqtt) == A::CMD_ACTION_NONE && savedKey == "MQTT_SERVER" && savedValue == "broker");
    std::vector<String> ntrip = {"ATG", "NTRIP", "SET", "MNTPNT", "mount"};
    assert(handleCommand(ntrip) == A::CMD_ACTION_NONE && savedKey == "NTRIP_MPT" && savedValue == "mount");
    std::vector<String> incomplete = {"ATG", "GNSS"};
    assert(handleCommand(incomplete) == A::CMD_ACTION_NONE);
    std::vector<String> rover = {"ATG", "GNSS", "ROVER"};
    backendAgent.active = true; handleCommand(rover); assert(backendAgent.calls == 0);
    backendAgent.active = false; handleCommand(rover); assert(backendAgent.calls == 1);
    std::vector<String> base = {"ATG", "GNSS", "BASE", "X"}; handleCommand(base); assert(baseCalls == 1);
    std::vector<String> set = {"ATG", "GNSS", "SET", "X"}; handleCommand(set); assert(setCalls == 1);
    std::vector<String> unknown = {"ATG", "CONFIG", "BAD"};
    assert(handleCommand(unknown) == A::CMD_ACTION_NONE && prefs.writes == 0);
    std::vector<String> reset = {"ATG", "CONFIG", "RESET"};
    assert(handleCommand(reset) == A::CMD_ACTION_ESP_RESTART && prefs.writes == 1);
}
'''
with tempfile.TemporaryDirectory(prefix='command-dispatch-') as directory:
    path = Path(directory)
    (path / 'Arduino.h').write_text('#pragma once\n' + shim)
    (path / 'check.cpp').write_text(harness + functions + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(path), '-I' + str(root / 'include'), str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: ESP, MQTT, NTRIP, GNSS and CONFIG command routing')
