"""Repeated service config must preserve connections; real changes must reconnect."""
from pathlib import Path
import subprocess
import tempfile
from host_coverage import compile_cpp, mapped, run_cpp
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Commands.cpp').read_text()
method = source[source.index('bool BackendAgent::executeServiceConfigCommand('):source.index('bool BackendAgent::executeRawCommand(')]
stream = source[source.index('bool BackendAgent::executeStreamCommand('):source.index('bool BackendAgent::executeBaseStatusCommand(')]
basic = source[source.index('bool BackendAgent::executeBasicCommand('):source.index('bool BackendAgent::executeStreamCommand(')]
agent = (root / 'src/functions/backend/Backend_Agent.cpp').read_text()
boolean = agent[agent.index('    bool jsonBool('):agent.index('    String jsonString(')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <array>
#include <cassert>
constexpr size_t CONFIG_DOCUMENT_SIZE = 6144;
int setups = 0, connections = 0;
void setupNTRIP() { ++setups; }
void connectNTRIP() { ++connections; }
struct BackendAgent {
    String serviceConfig_ = "{}";
    String deviceName_, baseStartupState_;
    int published = 0, saves = 0, streamChanges = 0;
    bool saveOk = true, active = false, provisioned_ = false, baseStartupAttempted_ = false;
    struct { void restore(bool, int) {} } stationLock_;
    bool workflowActive() { return active; }
    bool applyLockCommand(JsonObjectConst, String &) { return true; }
    String normalAgentState() { return "online"; }
    void setAgentState(const String &) {}
    bool saveStatePreferences() { ++saves; return saveOk; }
    void publishConfigState(const String &) { ++published; }
    bool applyServiceStreamCommand(JsonObject, String &) { ++streamChanges; return saveOk; }
    bool executeServiceConfigCommand(JsonObject, String &, String &);
    bool executeStreamCommand(JsonObject, String &, String &);
    bool executeBasicCommand(const String &, JsonObject, String &, String &);
};
'''
checks = r'''
int main() {
    BackendAgent agent;
    DynamicJsonDocument request(2048);
    request["serverhost1"] = "caster.example";
    request["port1"] = 2101;
    String error, detail;
    assert(agent.executeServiceConfigCommand(request.as<JsonObject>(), error, detail));
    assert(setups == 1 && connections == 1 && agent.published == 1 && agent.saves == 1);
    assert(agent.executeServiceConfigCommand(request.as<JsonObject>(), error, detail));
    assert(setups == 1 && connections == 1 && agent.published == 2 && agent.saves == 1);
    request["port1"] = 2102;
    const String beforeFailure = agent.serviceConfig_;
    agent.saveOk = false;
    assert(!agent.executeServiceConfigCommand(request.as<JsonObject>(), error, detail));
    assert(error == "cannot save service configuration" && agent.serviceConfig_ == beforeFailure);
    assert(setups == 1 && connections == 1 && agent.published == 2);
    agent.saveOk = true;
    assert(agent.executeServiceConfigCommand(request.as<JsonObject>(), error, detail));
    assert(setups == 2 && connections == 2);
    DynamicJsonDocument reordered(2048);
    reordered["port1"] = 2102; reordered["serverhost1"] = "caster.example";
    for (int retry = 0; retry < 10; ++retry)
        assert(agent.executeServiceConfigCommand(reordered.as<JsonObject>(), error, detail));
    assert(setups == 2 && connections == 2 && detail == "service config unchanged; connections preserved");
    agent.active = true;
    assert(agent.executeServiceConfigCommand(request.as<JsonObject>(), error, detail));
    request["port1"] = 2103;
    const String beforeBusy = agent.serviceConfig_;
    assert(!agent.executeServiceConfigCommand(request.as<JsonObject>(), error, detail));
    assert(error == "cannot change service config during an active base workflow");
    assert(agent.serviceConfig_ == beforeBusy && setups == 2 && connections == 2);
    DynamicJsonDocument streamRequest(128); streamRequest["active"] = false;
    assert(!agent.executeStreamCommand(streamRequest.as<JsonObject>(), error, detail));
    assert(error == "cannot change streams during an active base workflow");
    assert(agent.streamChanges == 0 && setups == 2 && connections == 2);
    agent.active = false;
    assert(agent.executeStreamCommand(streamRequest.as<JsonObject>(), error, detail));
    assert(agent.streamChanges == 1 && setups == 3 && connections == 3);
    const String previous = agent.serviceConfig_;
    DynamicJsonDocument large(12000);
    large["serverhost1"] = String(std::string(9000, 'x'));
    assert(!agent.executeServiceConfigCommand(large.as<JsonObject>(), error, detail));
    assert(error == "service configuration exceeds memory capacity");
    assert(agent.serviceConfig_ == previous && setups == 3 && connections == 3 && agent.published == 14);
    request.clear(); request.to<JsonObject>();
    assert(!agent.executeServiceConfigCommand(request.as<JsonObject>(), error, detail));
    assert(setups == 3 && connections == 3 && agent.published == 14);
    DynamicJsonDocument provision(128); provision["name"] = "station";
    agent.active = true;
    assert(agent.executeBasicCommand("PROVISION_DEVICE", provision.as<JsonObject>(), error, detail));
    assert(agent.provisioned_ && agent.deviceName_ == "station" && setups == 3 && connections == 3);
    agent.active = false;
    assert(agent.executeBasicCommand("PROVISION_DEVICE", provision.as<JsonObject>(), error, detail));
    assert(setups == 4 && connections == 4);
    agent.serviceConfig_ = String("{\"legacy\":\"") + String(std::string(7000, 'x')) + "\"}";
    const String legacy = agent.serviceConfig_;
    request["port1"] = 2101;
    assert(!agent.executeServiceConfigCommand(request.as<JsonObject>(), error, detail));
    assert(error == "service configuration exceeds memory capacity" && agent.serviceConfig_ == legacy);
    assert(setups == 4 && connections == 4);
    BackendAgent removed;
    removed.serviceConfig_ = R"({"server1_enabled":true,"server3_enabled":true,"password3":"secret","port3":2103})";
    DynamicJsonDocument deletion(256), after(2048);
    deletion["removed_servers"].add(3); deletion["removed_servers"].add(1);
    assert(removed.executeServiceConfigCommand(deletion.as<JsonObject>(), error, detail));
    assert(!deserializeJson(after, removed.serviceConfig_));
    assert(after["server1_enabled"] == true && after["server3_enabled"].isNull());
    assert(after["password3"].isNull() && after["port3"].isNull() && after["removed_servers"].isNull());
    assert(removed.saves == 1);
}
'''
with tempfile.TemporaryDirectory(prefix='service-config-') as directory:
    path = Path(directory)
    commands_path = root / 'src/functions/backend/Backend_Agent_Commands.cpp'
    agent_path = root / 'src/functions/backend/Backend_Agent.cpp'
    (path / 'check.cpp').write_text(harness + mapped(agent_path, boolean) + mapped(commands_path, method) +
                                    mapped(commands_path, basic) + mapped(commands_path, stream) + checks)
    compile_cpp(['c++', '-std=c++17', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'),
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    run_cpp([str(path / 'check')], check=True)
print('PASS: service configuration and provisioning preserve active workflows')
