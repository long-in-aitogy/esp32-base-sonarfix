"""Check that failed coordinate conversion cannot reach receiver configuration."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
workflow = (root / 'src/functions/backend/Backend_Agent_Workflows.cpp').read_text()
begin = workflow.index('bool BackendAgent::completeAutoBaseSetup(')
end = workflow.index('    setAgentState("auto_setup_base");', begin)
method = workflow[begin:end] + '    reachedWrite = true;\n    (void)resultJson;\n    return true;\n}\n'
projection = (root / 'src/functions/backend/Backend_Agent_Projection.cpp').read_text()
begin = projection.index('bool BackendAgent::transformToVn2000(')
validation = projection[begin:]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
#include <cmath>
#include <vector>
#include <strings.h>
#include "functions/backend/Vn2000_Datum.h"
int tcpStreamMutex = 1; constexpr int MUTEX_TIMEOUT_MS = 1500, pdTRUE = 1;
uint32_t now = 1000;
uint32_t millis() { return now; }
int pdMS_TO_TICKS(int n) { return n; }
uint32_t requestStarted = 0; bool provideLocation = false;
int xQueueReset(int) { requestStarted = now; return 1; }
int xQueueReceive(int, void *out, int timeout) {
    now += timeout;
    if (!provideLocation) return 0;
    std::snprintf(static_cast<char *>(out), 1536, R"({"request_id":"boot:%u","location":{"input_coord":{"lat":21,"lon":105,"alt":10},"l0_deg":105,"k0":0.9999}})", requestStarted);
    provideLocation = false; return 1;
}
int xSemaphoreTake(int, int) { return 1; }
void xSemaphoreGive(int) {}
Vn2000Datum sessionDatum;
Vn2000Datum ntripRoverDatum() { return sessionDatum; }
double coordinateNumber(JsonVariantConst v) {
    if (v.isNull()) return NAN;
    if (v.is<const char *>()) { const char *p = v.as<const char *>(); char *end = nullptr; double value = std::strtod(p, &end); return end != p && *end == 0 ? value : NAN; }
    return v.as<double>();
}
bool transformVn2000(double lat, double lon, double alt, const Vn2000Datum &, Vn2000Result &out) {
    out.latitude = lat; out.longitude = lon; out.altitude = alt; return true;
}
MATCHER_PLACEHOLDER
struct BackendAgent {
    struct AutoBaseLocationReply { char json[1536]; };
    int autoBaseLocationQueue_ = 0;
    String statusBootId_ = "boot";
    bool workflowCancelRequested_ = false;
    bool stopNtripRoverLocked() { return true; }
    void setWorkflowProgress(const char *, int, int, const String &) {}
    struct ProjectedPosition { double latitude, longitude, altitude; double northing = 0, easting = 0; };
    bool reachedWrite = false, transformOk = false; int conversions = 0;
    bool resolveAutoBaseProjection(JsonObject, double, double &meridian, double &scale, String &, String &, String &) { meridian=105; scale=0.9999; return true; }
    template <class... T> String buildAutoBaseResult(T&&...) { return "measured"; }
    bool transformToVn2000(double, double, double, double, double, ProjectedPosition &);
    bool transformItrfToVn2000(double, double, double, double, double, ProjectedPosition &) { ++conversions; return transformOk; }
    bool completeAutoBaseSetup(JsonObject, const std::vector<double> &, const std::vector<double> &, const std::vector<double> &, String &, String &);
};
'''
matcher = workflow[workflow.index('    bool acceptAutoBaseLocationReply('):workflow.index('} // namespace')]
harness = harness.replace('MATCHER_PLACEHOLDER', matcher)
checks = r'''
int main() {
    BackendAgent agent; BackendAgent::ProjectedPosition result{21, 105, 10};
    assert(!agent.transformToVn2000(21, 105, 10, NAN, 0.9999, result));
    assert(!agent.transformToVn2000(21, 105, 10, 105, NAN, result));
    assert(agent.conversions == 0);
    DynamicJsonDocument doc(256); JsonObject payload = doc.to<JsonObject>();
    std::vector<double> lat{21}, lon{105}, alt{10}; String resultJson, error;
    payload["enable_itrf_vn2000_transform"] = true;
    assert(!agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error));
    assert(!agent.reachedWrite && error == "VN2000 conversion failed; no candidate coordinates were installed");
    payload["enable_itrf_vn2000_transform"] = false;
    assert(agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error));
    assert(!agent.reachedWrite && resultJson == "measured" && agent.conversions == 1);
    payload["ip"] = "VNGEONET.VN";
    payload["enable_itrf_vn2000_transform"] = true;
    assert(!agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error));
    assert(error == "missing RTCM 1021 from this CORS session");
    sessionDatum.has1021 = true;
    assert(!agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error));
    assert(error == "location reply queue could not be allocated");
    agent.autoBaseLocationQueue_ = 1;
    assert(!agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error));
    assert(error == "backend location ACK timed out or did not match sampled LLH");
    agent.workflowCancelRequested_ = true;
    assert(!agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error));
    assert(error == "cancelled by user");
    agent.workflowCancelRequested_ = false;
    provideLocation = true;
    assert(agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error));
    sessionDatum.has1025 = true; sessionDatum.centralMeridianDeg = 105; sessionDatum.scale = 0.9999;
    assert(agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error));
    payload["resN"] = "invalid";
    assert(!agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error));
    assert(error == "invalid CORS shift");
    payload.remove("resN");
    sessionDatum.has1025 = false;
    payload["l0_deg"] = 105; payload["k0"] = 0.9999;
    assert(agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error));
    payload["auto_apply"] = true;
    assert(agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error));
    assert(agent.reachedWrite);
}
'''
with tempfile.TemporaryDirectory(prefix='auto-base-transform-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + validation + method + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'), '-I' + str(root / 'include'), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: invalid projection and conversion failure never apply candidate coordinates')
