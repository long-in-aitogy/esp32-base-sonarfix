"""Reject invalid saved configuration before stopping a workflow or sending GNSS commands."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Commands.cpp').read_text()
method = source[source.index('bool BackendAgent::executeRawCommand('):source.index('bool BackendAgent::executeAutoBaseCommand(')]
validator = source[source.index('static bool validateRawCommands('):source.index('bool BackendAgent::executeRawCommands(')]
codec = (root / 'src/functions/backend/Backend_Agent_Codec.cpp').read_text()
codec = codec[codec.index('    int base64Value('):codec.index('    bool delayMarker(')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <array>
#include <cassert>
#include <vector>
constexpr size_t CONFIG_DOCUMENT_SIZE = 4096;
namespace GnssCmdBuilder {
    enum class GnssSensorType { Invalid, Ublox, Unicore };
    using CommandList = std::vector<int>;
    GnssSensorType sensorTypeFromString(const String &s) { return s == "Ublox" ? GnssSensorType::Ublox : s == "Unicorecomm" ? GnssSensorType::Unicore : GnssSensorType::Invalid; }
}
uint32_t millis() { return 0; }
int pdMS_TO_TICKS(int n) { return n; }
void vTaskDelay(int) {}
void enforceBaseAccuracy(JsonObject config) { if (config["base_setup_method"] == "SURVEY_IN") config["survey_in_accuracy"] = 5; }
struct BackendAgent {
    struct StartupPosition { double latitude = 0; };
    String sensorType_ = "Ublox", baseStartupState_, baseStartupError_, autoBaseProgress_, baseConfig_ = "old";
    bool baseStartupAttempted_ = false, active = false, failWrite = false, readOk = true, confirmOk = true, saveOk = true;
    uint32_t lastReceiverPollMs_ = 0;
    int sent = 0, stopped = 0, published = 0;
    bool workflowActive() { return active; }
    void requestWorkflowStop() { ++stopped; active = false; }
    bool executeRawCommands(JsonArray, String &error, const String &) { ++sent; if (failWrite) error = "write failed"; return !failWrite; }
    String normalAgentState() { return "online"; }
    void setAgentState(const String &) {}
    void markStatusDirty() {}
    bool saveStatePreferences() { return saveOk; }
    bool buildStartupCommands(JsonObjectConst base, GnssCmdBuilder::GnssSensorType, bool, GnssCmdBuilder::CommandList &, StartupPosition &p, String &error) {
        if (base["coords"]["lat"].isNull()) { error = "invalid coordinates"; return false; }
        p.latitude = base["coords"]["lat"].as<double>(); return true;
    }
    bool refreshReceiverReadback(String &error) { if (!readOk) error = "read failed"; return readOk; }
    bool verifyStartupReadback(GnssCmdBuilder::GnssSensorType, bool fixed, const StartupPosition &p, String &error) {
        assert(fixed && p.latitude == 21); if (!confirmOk) error = "BESTPOS mismatch"; return confirmOk;
    }
    void publishConfigState(const char *) { ++published; }
    bool executeRawCommand(JsonDocument &, JsonObject, String &, String &);
};
'''
checks = r'''
int main() {
    BackendAgent agent;
    DynamicJsonDocument doc(16000);
    auto config = doc.createNestedObject("original_config");
    config["mode"] = "BASE";
    config["params"]["base_setup_method"] = "SURVEY_IN";
    config["params"]["survey_in_accuracy"] = 3;
    auto payload = doc.createNestedObject("payload");
    payload.createNestedArray("commands_b64").add("AQ==");
    String error, detail;
    config["params"]["extra"] = String(std::string(6000, 'x'));
    agent.active = true;
    assert(!agent.executeRawCommand(doc, payload, error, detail));
    assert(error == "Base configuration exceeds memory capacity");
    assert(agent.active && agent.stopped == 0 && agent.sent == 0 && agent.baseConfig_ == "old");
    config["params"].as<JsonObject>().remove("extra");
    payload["commands_b64"][0] = "bad!";
    assert(!agent.executeRawCommand(doc, payload, error, detail));
    assert(agent.active && agent.stopped == 0 && agent.sent == 0 && error == "raw command is not valid base64");
    payload["commands_b64"][0] = "AQ==";
    agent.failWrite = true;
    assert(!agent.executeRawCommand(doc, payload, error, detail));
    assert(agent.sent == 1 && agent.baseConfig_ == "old" && agent.published == 0);
    agent.failWrite = false;
    assert(agent.executeRawCommand(doc, payload, error, detail));
    DynamicJsonDocument result(4096);
    assert(!deserializeJson(result, agent.baseConfig_));
    assert(result["survey_in_accuracy"] == 5 && result["mode"] == "BASE" && agent.published == 1);
    config["params"] = "bad";
    assert(!agent.executeRawCommand(doc, payload, error, detail));
    assert(error == "Base configuration must be an object" && agent.sent == 2);
    config["params"].to<JsonObject>()["base_setup_method"] = "FIXED_LLA";
    error.clear();
    assert(!agent.executeRawCommand(doc, payload, error, detail));
    assert(error == "invalid coordinates" && agent.sent == 2);
    config["params"]["coords"]["lat"] = 21;
    const String previous = agent.baseConfig_;
    agent.confirmOk = false; error.clear();
    assert(!agent.executeRawCommand(doc, payload, error, detail));
    assert(error == "BESTPOS mismatch" && agent.baseStartupState_ == "error" && agent.baseConfig_ == previous);
    agent.confirmOk = true; error.clear();
    agent.saveOk = false;
    assert(!agent.executeRawCommand(doc, payload, error, detail));
    assert(agent.baseConfig_ == previous && agent.baseStartupState_ == "error" && agent.published == 1);
    agent.saveOk = true; error.clear();
    assert(agent.executeRawCommand(doc, payload, error, detail));
    assert(agent.baseStartupState_ == "configured" && agent.published == 2);
}
'''
with tempfile.TemporaryDirectory(prefix='esp-raw-preflight-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + codec + validator + method + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined', '-I' + str(root / 'test/host'), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'), str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: raw config validated before GNSS writes, and 5 m preserved on success')
