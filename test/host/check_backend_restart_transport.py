"""Backend restart paths close transports after status and reset work."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Commands.cpp').read_text()
finish = source[source.index('void BackendAgent::finishCommand('):source.index('void BackendAgent::executeCommand(')]
start = source.index('    else if (command == "REBOOT_DEVICE")', source.index('void BackendAgent::executeCommand('))
end = source.index('\n    finishCommand(', start)
branches = source[start:end].replace('    else if (command == "REBOOT_DEVICE")', '    if (command == "REBOOT_DEVICE")', 1)
harness = r'''
#include <Arduino.h>
#include <cassert>
#include <string>
std::string events;
void delay(int) {}
void shutdownTcpTransportBeforeRestart() { events += 'T'; }
struct { void restart() { events += 'R'; throw 1; } } ESP;
struct Preferences { void begin(const char *, bool) {} void clear() { events += 'C'; } void end() {} } prefs, backend;
bool beginBackendPreferences(bool) { return true; }
Preferences &backendPreferences() { return backend; }
struct BackendAgent {
    bool workflowActive() { return false; }
    void requestWorkflowStop() { events += 'W'; }
    void setAgentState(const String &) {}
    String normalAgentState() { return "online"; }
    void recordCommandResult(const String &, const String &, const String &, const String &, const String &) { events += 'L'; }
    bool saveStatePreferences() { events += 'S'; return true; }
    void publishStatus(bool) { events += 'P'; }
    void finishCommand(const String &, const String &, const String &, bool, const String &, const String &, bool);
    void restartCommand(const String &command) { String source = "mqtt", commandId = "x";
'''
checks = r'''
    }
};
int main() {
    BackendAgent agent;
    try { agent.restartCommand("REBOOT_DEVICE"); assert(false); } catch (int) {}
    assert(events == "WLSPTR");
    events.clear();
    try { agent.restartCommand("DELETE_DEVICE"); assert(false); } catch (int) {}
    assert(events == "WLSPCCTR");
    events.clear();
    try { agent.finishCommand("mqtt", "DEPLOY_LICENSE", "x", true, "", "ok", true); assert(false); } catch (int) {}
    assert(events == "LSPTR");
}
'''
with tempfile.TemporaryDirectory(prefix='esp-backend-restart-') as directory:
    path = Path(directory)
    # Define the method after the class; its body calls the same code as production.
    parts = checks.split('int main()', 1)
    (path / 'check.cpp').write_text(harness + branches + parts[0] + finish + 'int main()' + parts[1])
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined', '-I' + str(root / 'test/host'), str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: reboot, delete and license restart close transports after final status')
