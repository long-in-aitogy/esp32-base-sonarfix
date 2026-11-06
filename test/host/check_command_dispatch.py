"""Exercise legacy command routing after the upstream extraction."""
from pathlib import Path
import tempfile
from host_coverage import compile_cpp, run_cpp, mapped

root = Path(__file__).resolve().parents[2]
path = root / 'src/functions/backend/cmd_handler.cpp'
source = path.read_text()
functions = 'cmd_action_t handleGnssCommand(' + source.split('cmd_action_t handleGnssCommand(', 1)[1]
shim = r'''
#include <cassert>
#include <string>
#include <vector>
using String = std::string;
enum cmd_action_t { CMD_ACTION_NONE, CMD_ACTION_ESP_RESTART };
struct { String last; void println(const String &s) { last = s; } } Serial;
struct { bool active = false; int calls = 0; bool workflowActive() { return active; }
         bool applyRoverMode() { ++calls; return true; } } backendAgent;
struct { int writes = 0; void begin(const char *, bool) {} void end() {}
         void putBool(const char *, bool) { ++writes; } } prefs;
int base = 0, set = 0;
cmd_action_t handleGnssBaseCommand(const std::vector<String> &v) { ++base; assert(v.size() == 1 && v[0] == "X"); return CMD_ACTION_NONE; }
cmd_action_t handleGnssSetCommand(const std::vector<String> &v) { ++set; assert(v.size() == 2 && v[0] == "SET"); return CMD_ACTION_NONE; }
cmd_action_t handleEspCommand(const std::vector<String> &) { return CMD_ACTION_NONE; }
cmd_action_t handleMqttCommand(const std::vector<String> &) { return CMD_ACTION_NONE; }
cmd_action_t handleNtripCommand(const std::vector<String> &) { return CMD_ACTION_NONE; }
'''
checks = r'''
int main() {
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
    (build / 'check.cpp').write_text(shim + mapped(path, functions) + checks)
    compile_cpp(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                 str(build / 'check.cpp'), '-o', str(build / 'check')], check=True)
    run_cpp([str(build / 'check')], check=True)
print('PASS: GNSS and CONFIG command routing')
