"""Verify Auto Base source and automatic-apply request validation."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Commands.cpp').read_text()
begin = source.index('bool BackendAgent::executeAutoBaseCommand(')
end = source.index('\nbool BackendAgent::', begin + 5)
method = source[begin:end]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
constexpr size_t CONFIG_DOCUMENT_SIZE = 4096;
struct BackendAgent {
    String sensorType_ = "Ublox";
    bool running = false; int started = 0; String progress;
    bool workflowActive() { return running; }
    bool startWorkflow(const char *, const String &) { ++started; return true; }
    void setAgentState(const char *) {}
    void setWorkflowProgress(const char *, int, int, const String &value) { progress = value; }
    bool executeAutoBaseCommand(JsonObject, String &, String &);
};
'''
checks = r'''
int main() {
    DynamicJsonDocument doc(1024); JsonObject request = doc.to<JsonObject>();
    request["ip"]="host"; request["port"]=2101; request["user"]="user";
    request["password"]="secret"; request["mountpoint"]="station";
    request["source_name"]="Station A"; request["source_serial"]="serial-a"; request["source_distance_m"]=12.5;
    BackendAgent agent; String error, detail;
    assert(agent.executeAutoBaseCommand(request, error, detail) && agent.started == 1);
    DynamicJsonDocument progress(4096); assert(!deserializeJson(progress, agent.progress));
    assert(progress["source_name"] == "Station A" && progress["source_serial"] == "serial-a");
    assert(progress["source_distance_m"] == 12.5 && progress["note"] == "Collect RTK Fixed LLH; results wait for review.");
    request["auto_apply"] = true;
    assert(!agent.executeAutoBaseCommand(request, error, detail) && agent.started == 1);
    assert(error == "automatic apply is only supported for nearest CORS mode");
    request["source_mode"] = "nearest";
    assert(agent.executeAutoBaseCommand(request, error, detail) && agent.started == 2);
    progress.clear(); assert(!deserializeJson(progress, agent.progress));
    assert(progress["note"] == "Collect RTK Fixed LLH and apply Base coordinates after quality checks.");
    request["source_mode"] = "unknown";
    assert(!agent.executeAutoBaseCommand(request, error, detail) && agent.started == 2);
    assert(error == "unsupported CORS source mode");
}
'''
with tempfile.TemporaryDirectory(prefix='autobase-command-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + method + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: source mode and automatic apply validated before starting workflow')
