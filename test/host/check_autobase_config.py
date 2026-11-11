"""Exercise the real Auto Base config update and its persistence failure path."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Workflows.cpp').read_text()
start = source.index('    DynamicJsonDocument baseConfig(CONFIG_DOCUMENT_SIZE);', source.index('bool BackendAgent::completeAutoBaseSetup('))
end = source.index('    setAgentState(normalAgentState());', start)
update = source[start:end]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
constexpr size_t CONFIG_DOCUMENT_SIZE = 4096;
struct Position { double latitude = 21.25, longitude = 105.75, altitude = 10.5, northing = 1, easting = 2; };
struct BackendAgent {
    String baseConfig_, published;
    bool saveOk = true, restartOk = true;
    int saves = 0, failSave = 0;
    int publishes = 0, stops = 0, writes = 0;
    bool stopNtripRoverLocked() { ++stops; return true; }
    bool applyBaseCoordinates(double, double, double) { ++writes; return true; }
    bool saveStatePreferences() { ++saves; return saveOk && saves != failSave; }
    bool restartConfiguredNtrip() { return restartOk; }
    void publishConfigState(const char *kind) { ++publishes; published = kind; }
    bool apply(String &failureReason) {
        Position result;
        const double rawLatitude = 21, rawLongitude = 105, rawAltitude = 11;
        const bool transformed = true;
        const double centralMeridianDeg = 105, scale = 0.9999;
        const char *projectionSource = "province";
        const String provinceCode = "01", provinceName = "Ha Noi";
'''
checks = r'''
        return true;
    }
};
int main() {
    BackendAgent agent;
    agent.baseConfig_ = R"({"base_setup_method":"SURVEY_IN","survey_in_duration":300,"gnss_options":{"msm_level":"7"},"coords":{"lat":1,"lon":2,"alt":3}})";
    const String previous = agent.baseConfig_;
    String error;
    agent.saveOk = false;
    assert(!agent.apply(error) && agent.baseConfig_ == previous && agent.publishes == 0);
    assert(error == "could not save automatically applied Fixed LLA");
    agent.saveOk = true; agent.restartOk = false;
    const int saves = agent.saves;
    assert(!agent.apply(error) && agent.baseConfig_ == previous && agent.publishes == 0);
    assert(agent.saves == saves + 2 && error == "could not restore configured NTRIP after applying Fixed LLA");
    BackendAgent rollbackFailure;
    rollbackFailure.baseConfig_ = previous;
    rollbackFailure.restartOk = false;
    rollbackFailure.failSave = 2;
    assert(!rollbackFailure.apply(error) && rollbackFailure.baseConfig_ == previous && rollbackFailure.publishes == 0);
    assert(error == "could not save previous Base configuration after NTRIP restore failed");
    agent.restartOk = true;
    assert(agent.apply(error) && agent.publishes == 1 && agent.published == "base_config_state");
    DynamicJsonDocument result(4096);
    assert(deserializeJson(result, agent.baseConfig_) == DeserializationError::Ok);
    assert(result["base_setup_method"] == "AUTO_CORS" && result["survey_in_duration"] == 300);
    assert(result["gnss_options"]["msm_level"] == "7" && result["coords"]["lat"] == 21.25);
    agent.baseConfig_ = "{bad"; error.clear();
    const int writes = agent.writes, stops = agent.stops;
    assert(!agent.apply(error) && agent.publishes == 1 && agent.baseConfig_ == "{bad");
    assert(agent.writes == writes && agent.stops == stops);
}
'''
with tempfile.TemporaryDirectory(prefix='autobase-config-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + update + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: Auto Base preserves saved options, publishes after save, and handles persistence errors')
