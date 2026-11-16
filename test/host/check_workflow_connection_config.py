"""Validate CORS connection fields before workflows touch the receiver."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Workflows.cpp').read_text()
methods = []
for name in ('prepareAutoBaseConfig', 'prepareReferenceCheckConfig'):
    start = source.index('bool BackendAgent::' + name + '(')
    end = source.index('\nbool BackendAgent::', start + 5)
    methods.append(source[start:end])
start = source.index('String BackendAgent::buildReferenceCheckResult(')
end = source.index('\nbool BackendAgent::runReferenceCheckWorkflow(', start)
methods.append(source[start:end])
number = source[source.index('    double coordinateNumber('):source.index('    void appendAutoBaseDatumReport(')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cmath>
#include <cassert>
constexpr size_t CONFIG_DOCUMENT_SIZE = 6144;
#define constrain(value, low, high) ((value) < (low) ? (low) : (value) > (high) ? (high) : (value))
struct BackendAgent {
    String baseConfig_ = R"({"base_setup_method":"SURVEY_IN"})", sensorType_ = "Unicorecomm";
    uint32_t surveyInTargetSeconds_ = 0;
    bool prepareAutoBaseConfig(JsonObject, String &, uint16_t &, String &, String &, String &, uint8_t &, uint32_t &, uint8_t &);
    bool prepareReferenceCheckConfig(JsonObject, JsonObject &, double &, double &, double &, double &, double &, double &, String &, uint16_t &, String &, String &, String &, uint32_t &, uint16_t &);
    String buildReferenceCheckResult(JsonObject, double, double, double, size_t);
};
'''
checks = r'''
int main() {
    BackendAgent agent;
    DynamicJsonDocument doc(1024);
    JsonObject payload = doc.to<JsonObject>();
    payload["ip"] = "  caster.example  "; payload["user"] = "user";
    payload["password"] = "password"; payload["mountpoint"] = "station";
    payload["reference_coords"]["lat"] = 21.0;
    payload["reference_coords"]["lon"] = 105.0;
    payload["reference_coords"]["alt"] = 5.0;
    String host, user, password, mountpoint;
    uint16_t port, samples; uint8_t version, streak; uint32_t timeout;
    JsonObject reference; double lat, lon, alt, oldLat, oldLon, oldAlt;
    for (int input : {-1, 0, 1, 2101, 65535, 65536, 67637}) {
        payload["port"] = input;
        bool valid = input > 0 && input <= 65535;
        assert(agent.prepareAutoBaseConfig(payload, host, port, user, password, mountpoint, version, timeout, streak) == valid);
        assert(host == "caster.example" && port == (valid ? input : 0));
        assert(agent.prepareReferenceCheckConfig(payload, reference, lat, lon, alt, oldLat, oldLon, oldAlt, host, port, user, password, mountpoint, timeout, samples) == valid);
        assert(host == "caster.example" && port == (valid ? input : 0));
    }
    payload["port"] = 2101;
    for (const char *invalid : {
        R"({"base_setup_method":"SURVEY_IN","survey_in_duration":0})",
        R"({"base_setup_method":"SURVEY_IN","survey_in_duration":1.5})",
        R"({"base_setup_method":"SURVEY_IN","survey_in_duration":3601})"}) {
        agent.baseConfig_ = invalid;
        assert(!agent.prepareReferenceCheckConfig(payload, reference, lat, lon, alt, oldLat, oldLon, oldAlt, host, port, user, password, mountpoint, timeout, samples));
    }
    agent.baseConfig_ = R"({"base_setup_method":"SURVEY_IN","survey_in_duration":3601})";
    agent.surveyInTargetSeconds_ = 300;
    assert(agent.prepareReferenceCheckConfig(payload, reference, lat, lon, alt, oldLat, oldLon, oldAlt, host, port, user, password, mountpoint, timeout, samples));
    agent.surveyInTargetSeconds_ = 0; agent.sensorType_ = "Ublox";
    assert(agent.prepareReferenceCheckConfig(payload, reference, lat, lon, alt, oldLat, oldLon, oldAlt, host, port, user, password, mountpoint, timeout, samples));
    agent.baseConfig_ = R"({"base_setup_method":"FIXED_LLA","coords":{"lat":"21.25","lon":"105.75","alt":"10.5"}})";
    agent.sensorType_ = "Unicorecomm";
    payload["reference_coords"]["lat"] = "21.25";
    payload["reference_coords"]["lon"] = "105.75";
    payload["reference_coords"]["alt"] = "10.5";
    assert(agent.prepareReferenceCheckConfig(payload, reference, lat, lon, alt, oldLat, oldLon, oldAlt, host, port, user, password, mountpoint, timeout, samples));
    assert(lat == 21.25 && lon == 105.75 && alt == 10.5 && oldLat == lat && oldLon == lon && oldAlt == alt);
    agent.baseConfig_ = R"({"base_setup_method":"FIXED_LLA","altitude_reference":"MSL","coords":{"lat":21.25,"lon":105.75,"alt":10.5}})";
    assert(!agent.prepareReferenceCheckConfig(payload, reference, lat, lon, alt, oldLat, oldLon, oldAlt, host, port, user, password, mountpoint, timeout, samples));
    agent.baseConfig_ = R"({"base_setup_method":"FIXED_LLA","altitude_reference":"ELLIPSOID","coords":{"lat":21.25,"lon":105.75,"alt":10.5}})";
    assert(agent.prepareReferenceCheckConfig(payload, reference, lat, lon, alt, oldLat, oldLon, oldAlt, host, port, user, password, mountpoint, timeout, samples));
    DynamicJsonDocument result(2048);
    assert(!deserializeJson(result, agent.buildReferenceCheckResult(reference, 21.25, 105.75, 11.5, 60)));
    assert(result["delta_n_m"] == 0 && result["delta_e_m"] == 0 && result["delta_u_m"] == 1);
    for (const char *invalid : {
        R"({"base_setup_method":"FIXED_LLA","coords":{"lat":91,"lon":105,"alt":10}})",
        R"({"base_setup_method":"FIXED_LLA","coords":{"lat":21,"lon":181,"alt":10}})",
        R"({"base_setup_method":"FIXED_LLA","coords":{"lat":21,"lon":105,"alt":100001}})"}) {
        agent.baseConfig_ = invalid;
        assert(!agent.prepareReferenceCheckConfig(payload, reference, lat, lon, alt, oldLat, oldLon, oldAlt, host, port, user, password, mountpoint, timeout, samples));
    }
    agent.baseConfig_ = R"({"base_setup_method":"FIXED_LLA","coords":{"lat":"21.25","lon":"105.75","alt":"10.5"}})";
    payload["reference_coords"]["lat"] = "21bad";
    assert(!agent.prepareReferenceCheckConfig(payload, reference, lat, lon, alt, oldLat, oldLon, oldAlt, host, port, user, password, mountpoint, timeout, samples));
    payload["ip"] = "   "; payload["port"] = 2101;
    assert(!agent.prepareAutoBaseConfig(payload, host, port, user, password, mountpoint, version, timeout, streak));
    assert(!agent.prepareReferenceCheckConfig(payload, reference, lat, lon, alt, oldLat, oldLon, oldAlt, host, port, user, password, mountpoint, timeout, samples));
}
'''
with tempfile.TemporaryDirectory(prefix='workflow-connection-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + number + '\n'.join(methods) + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'),
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: Auto Base and reference check validate CORS host and port')
