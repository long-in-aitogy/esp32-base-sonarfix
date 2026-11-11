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
struct BackendAgent {
    struct ProjectedPosition { double latitude, longitude, altitude; double northing = 0, easting = 0; };
    bool reachedWrite = false, transformOk = false; int conversions = 0;
    bool resolveAutoBaseProjection(JsonObject, double, double &meridian, double &scale, String &, String &, String &) { meridian=105; scale=0.9999; return true; }
    template <class... T> String buildAutoBaseResult(T&&...) { return "measured"; }
    bool transformToVn2000(double, double, double, double, double, ProjectedPosition &);
    bool transformItrfToVn2000(double, double, double, double, double, ProjectedPosition &) { ++conversions; return transformOk; }
    bool completeAutoBaseSetup(JsonObject, const std::vector<double> &, const std::vector<double> &, const std::vector<double> &, String &, String &);
};
'''
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
    payload["auto_apply"] = true;
    assert(agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error));
    assert(agent.reachedWrite);
}
'''
with tempfile.TemporaryDirectory(prefix='auto-base-transform-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + validation + method + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: invalid projection and conversion failure never apply candidate coordinates')
