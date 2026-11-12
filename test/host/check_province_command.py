"""Keep province override while requiring original coordinates and receiver confirmation."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Commands.cpp').read_text()
method = source[source.index('bool BackendAgent::executeProvinceCommand('):source.index('bool BackendAgent::executeBasicCommand(')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
#include <cmath>
constexpr size_t CONFIG_DOCUMENT_SIZE = 4096;
namespace GnssCmdBuilder {
    constexpr float BASE_ACCURACY_METERS = 5.0f;
    enum class GnssSensorType { Ublox, Unicore };
    GnssSensorType sensorTypeFromString(const String &s) { return s == "Ublox" ? GnssSensorType::Ublox : GnssSensorType::Unicore; }
}
void enforceBaseAccuracy(JsonObject base) {
    base["accuracy"] = 5;
    if (!base["coords"]["accuracy"].isNull()) base["coords"]["accuracy"] = 5;
}
struct BackendAgent {
    struct ProjectedPosition { double latitude, longitude, altitude, northing = 0, easting = 0; };
    struct StartupPosition { double latitude, longitude, altitude; bool ellipsoid = false; };
    String baseConfig_ = R"({"base_setup_method":"FIXED_LLA","coords":{"lat":21,"lon":105,"alt":10,"accuracy":3}})";
    String sensorType_ = "Ublox";
    String baseStartupState_, baseStartupError_;
    bool active = false, readOk = true, confirmOk = true, saveOk = true;
    int writes = 0, saves = 0, publishes = 0;
    double transformedInput = 0, sentLatitude = 0;
    bool workflowActive() { return active; }
    bool getProvinceProjection(const String &p, double &meridian, double &scale, String &name) {
        if (p != "HN") return false; meridian = 105; scale = 0.9999; name = "Ha Noi"; return true;
    }
    bool transformToVn2000(double lat, double lon, double alt, double, double, ProjectedPosition &r) {
        transformedInput = lat; r = {lat + 0.01, lon, alt, 10, 20}; return true;
    }
    bool applyBaseCoordinates(double lat, double, double, JsonObjectConst) { ++writes; sentLatitude = lat; return true; }
    bool refreshReceiverReadback(String &error) { if (!readOk) error = "read failed"; return readOk; }
    bool verifyStartupReadback(GnssCmdBuilder::GnssSensorType, bool fixed, const StartupPosition &p, String &error) {
        assert(fixed && p.ellipsoid && p.latitude == sentLatitude);
        if (!confirmOk) error = "BESTPOS mismatch"; return confirmOk;
    }
    bool saveStatePreferences() { ++saves; return saveOk; }
    void publishConfigState(const char *) { ++publishes; }
    void markStatusDirty() {}
    void setWorkflowProgress(const char *, int, int) {}
    bool executeProvinceCommand(JsonObject, String &, String &);
};
'''
checks = r'''
int main() {
    BackendAgent agent; DynamicJsonDocument request(256); request["province_code"] = "hn";
    String error, detail; const String original = agent.baseConfig_;
    agent.active = true;
    assert(!agent.executeProvinceCommand(request.as<JsonObject>(), error, detail) && agent.writes == 0);
    agent.active = false; agent.confirmOk = false;
    assert(!agent.executeProvinceCommand(request.as<JsonObject>(), error, detail));
    assert(error == "BESTPOS mismatch" && agent.baseConfig_ == original && agent.saves == 0);
    assert(agent.baseStartupState_ == "error" && agent.baseStartupError_ == error);
    agent.confirmOk = true; agent.saveOk = false;
    assert(!agent.executeProvinceCommand(request.as<JsonObject>(), error, detail));
    assert(agent.baseConfig_ == original && agent.publishes == 0 && agent.baseStartupError_ == error);
    agent.saveOk = true;
    assert(agent.executeProvinceCommand(request.as<JsonObject>(), error, detail));
    DynamicJsonDocument saved(4096); assert(!deserializeJson(saved, agent.baseConfig_));
    assert(saved["coords"]["lat"] == 21.01 && saved["coords"]["accuracy"] == 5);
    assert(saved["auto_base_raw_itrf_llh"]["lat"] == 21 && saved["base_setup_method"] == "FIXED_LLA");
    assert(agent.executeProvinceCommand(request.as<JsonObject>(), error, detail));
    assert(agent.transformedInput == 21 && agent.sentLatitude == 21.01);
    saved.remove("auto_base_raw_itrf_llh"); agent.baseConfig_.clear(); serializeJson(saved, agent.baseConfig_);
    int writes = agent.writes;
    assert(!agent.executeProvinceCommand(request.as<JsonObject>(), error, detail));
    assert(agent.writes == writes && error == "original coordinates are missing; cannot transform again");
}
'''
with tempfile.TemporaryDirectory(prefix='esp-province-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + method + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined', '-I' + str(root / 'test/host'), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'), str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: province change preserves original coordinates, requires readback and handles save failure')
