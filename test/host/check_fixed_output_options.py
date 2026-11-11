"""Exercise Fixed LLA command options used by the province override."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Workflows.cpp').read_text()
method = source[source.index('bool BackendAgent::applyBaseCoordinates('):source.index('bool BackendAgent::restoreWorkflowBase(')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
#include <cmath>
#include "functions/gnss/gnss_cmd_builder.h"
GnssCmdBuilder::GnssOptions sent;
float sentAccuracy = 0;
GnssCmdBuilder::CommandList GnssCmdBuilder::buildBaseFixedLlaCommand(double, double, double, float accuracy, GnssSensorType, const GnssOptions &options) {
    sent = options; sentAccuracy = accuracy; return {};
}
struct BackendAgent {
    String sensorType_ = "Unicorecomm";
    int writes = 0;
    bool writeGnssCommands(const GnssCmdBuilder::CommandList &) { ++writes; return true; }
    bool applyBaseCoordinates(double, double, double, JsonObjectConst);
};
'''
checks = r'''
int main() {
    DynamicJsonDocument base(1024);
    deserializeJson(base, R"({"gnss_options":{"msm_level":"both","constellations":{"qzss":true,"glo":false}}})");
    BackendAgent agent;
    assert(agent.applyBaseCoordinates(21, 105, 12, base.as<JsonObjectConst>()));
    assert(sent.ports.size() == 1 && sent.ports[0] == "UART1");
    assert(sent.outputMode == GnssCmdBuilder::OutputMode::RtcmOnly);
    assert(sent.msmLevel == GnssCmdBuilder::MsmLevel::Both && sent.qzss && !sent.glo);
    assert(sent.gps && sent.gal && sent.bds && !sent.sbas && sentAccuracy == 5);
    base.clear();
    assert(agent.applyBaseCoordinates(21, 105, 12, base.as<JsonObjectConst>()));
    assert(sent.msmLevel == GnssCmdBuilder::MsmLevel::Msm4 && !sent.qzss && !sent.sbas);
    const int writes = agent.writes;
    assert(!agent.applyBaseCoordinates(91, 105, 12, base.as<JsonObjectConst>()));
    agent.sensorType_ = "UNKNOWN";
    assert(!agent.applyBaseCoordinates(21, 105, 12, base.as<JsonObjectConst>()));
    assert(agent.writes == writes);
}
'''
with tempfile.TemporaryDirectory(prefix='fixed-output-options-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + method + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'), '-I' + str(root / 'include'),
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: Fixed LLA respects MSM/constellations, RTCM-only, 5 m and input validation')
