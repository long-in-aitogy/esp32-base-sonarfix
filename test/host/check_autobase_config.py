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
#include "functions/gnss/gnss_cmd_builder.h"
#include <cassert>
#include <cmath>
constexpr size_t CONFIG_DOCUMENT_SIZE = 6144;
struct Position { double latitude = 21.25, longitude = 105.75, altitude = 10.5, northing = 1, easting = 2; };
struct BackendAgent {
    String baseConfig_, published;
    bool saveOk = true, restartOk = true, restoreOk = true, largeReport = false, precise = false;
    int saves = 0, failSave = 0;
    int publishes = 0, stops = 0, writes = 0;
    bool stopNtripRoverLocked() { ++stops; return true; }
    bool restoreWorkflowBase(JsonObjectConst config) {
        ++writes;
        assert(config["base_setup_method"] == "FIXED_LLA");
        assert(config["mode"] == "BASE" && config["coordinate_source"] == "AUTO_CORS");
        assert(config["auto_cors_source_mode"] == "nearest" && config["coords"]["altitude_reference"] == "ELLIPSOID");
        assert(config["gnss_options"]["output_mode"] == "rtcm_only");
        assert(std::abs(config["coords"]["lat"].as<double>() - (precise ? 21.0849895837 : 21.25)) < 1e-10);
        assert(config["coords"]["alt"].as<double>() == 10.5);
        assert(config["accuracy"] == 5);
        return restoreOk;
    }
    bool saveStatePreferences() { ++saves; return saveOk && saves != failSave; }
    bool restartConfiguredNtrip() { return restartOk; }
    void publishConfigState(const char *kind) { ++publishes; published = kind; }
    bool apply(String &failureReason) {
        Position result;
        if (precise) { result.latitude = 21.0849895837; result.longitude = 105.7866564469; }
        DynamicJsonDocument report(CONFIG_DOCUMENT_SIZE);
        report["output_coord"]["lat"] = precise ? "21.0849895837" : "21.2500000000";
        report["output_coord"]["lon"] = precise ? "105.7866564469" : "105.7500000000";
        report["output_coord"]["alt"] = "10.5000";
        report["input_coord"]["lat"] = "21.084989583712345";
        report["input_coord"]["lon"] = "105.78665644691234";
        report["input_coord"]["alt"] = "11";
        report["source"]["mountpoint"] = "station";
        if (largeReport) report["detail"] = String(900, 'n');
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
    agent.baseConfig_ = R"({"base_setup_method":"SURVEY_IN","survey_in_duration":300,"survey_in_accuracy":3,"accuracy":5,"gnss_options":{"msm_level":"7","output_mode":"diagnostics","constellations":{"glo":false,"qzss":true}},"coords":{"lat":1,"lon":2,"alt":3}})";
    const String previous = agent.baseConfig_;
    String error;
    agent.restoreOk = false;
    assert(!agent.apply(error) && agent.baseConfig_ == previous && agent.saves == 0 && agent.publishes == 0);
    assert(error == "receiver did not confirm automatically measured Fixed LLA");
    agent.restoreOk = true; agent.saveOk = false;
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
    assert(result["base_setup_method"] == "FIXED_LLA" && result["survey_in_duration"] == 300);
    assert(result["conversion_report"]["source"]["mountpoint"] == "station");
    assert(result["conversion_report"]["receiver_write_completed"] == true && result["conversion_report"]["auto_applied"] == true);
    assert(result["auto_cors_source_mode"] == "nearest" && result["coords"]["altitude_reference"] == "ELLIPSOID");
    assert(result["accuracy"] == 5 && result["survey_in_accuracy"] == 5 && result["coords"]["accuracy"] == 5);
    assert(result["gnss_options"]["msm_level"] == "7" && result["coords"]["lat"].as<double>() == 21.25);
    assert(result["gnss_options"]["constellations"]["qzss"] == true);
    assert(result["gnss_options"]["constellations"]["glo"] == false);
    assert(result["gnss_options"]["constellations"]["sbas"] == false);
    BackendAgent highPrecision;
    highPrecision.baseConfig_ = "{}"; highPrecision.precise = true;
    assert(highPrecision.apply(error));
    result.clear(); assert(!deserializeJson(result, highPrecision.baseConfig_));
    assert(result["coords"]["lat"] == "21.0849895837" && result["coords"]["lon"] == "105.7866564469");
    assert(std::abs(result["coords"]["lat"].as<double>() - result["conversion_report"]["output_coord"]["lat"].as<double>()) < 1e-12);
    assert(std::abs(result["coords"]["lon"].as<double>() - result["conversion_report"]["output_coord"]["lon"].as<double>()) < 1e-12);
    assert(result["auto_base_raw_itrf_llh"]["lat"] == "21.084989583712345");
    assert(result["auto_base_raw_itrf_llh"]["lon"] == "105.78665644691234");
    BackendAgent withSnapshot;
    DynamicJsonDocument pending(4096);
    pending["base_setup_method"]="AUTO_CORS";
    pending["auto_base_previous_config"]["padding"]=String(2900, 'x');
    serializeJson(pending, withSnapshot.baseConfig_);
    assert(withSnapshot.apply(error));
    result.clear(); assert(!deserializeJson(result, withSnapshot.baseConfig_));
    assert(result["base_setup_method"]=="FIXED_LLA" && result["auto_base_previous_config"].isNull());
    BackendAgent replacement;
    DynamicJsonDocument oldConfig(4096);
    oldConfig["base_setup_method"]="AUTO_CORS";
    oldConfig["conversion_report"]["detail"]=String(2300, 'o');
    serializeJson(oldConfig, replacement.baseConfig_);
    replacement.largeReport=true;
    assert(replacement.apply(error));
    result.clear(); assert(!deserializeJson(result, replacement.baseConfig_));
    assert(result["conversion_report"]["detail"].as<String>().length()==900);
    BackendAgent tooLarge;
    DynamicJsonDocument nearCapacity(CONFIG_DOCUMENT_SIZE);
    nearCapacity["base_setup_method"] = "SURVEY_IN";
    nearCapacity["extra"] = String(5000, 'x');
    serializeJson(nearCapacity, tooLarge.baseConfig_);
    tooLarge.largeReport = true;
    assert(!tooLarge.apply(error));
    assert(error == "Auto Base configuration exceeds memory capacity");
    assert(tooLarge.stops == 0 && tooLarge.writes == 0 && tooLarge.saves == 0);
    BackendAgent defaults;
    defaults.baseConfig_ = "{}";
    assert(defaults.apply(error));
    result.clear();
    assert(deserializeJson(result, defaults.baseConfig_) == DeserializationError::Ok);
    assert(result["gnss_options"]["msm_level"] == "4");
    assert(result["gnss_options"]["constellations"]["qzss"] == false);
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
                    '-I' + str(root / 'test/host'), '-I' + str(root / 'include'), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: Auto Base checks receiver before saving, preserves options and handles restore failures')
