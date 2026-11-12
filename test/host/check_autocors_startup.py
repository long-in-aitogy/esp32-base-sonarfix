"""An Auto CORS base without coordinates must not enable SOURCE at boot."""
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[2]
source=(root/'src/functions/backend/Backend_Agent_Startup.cpp').read_text()
start=source.index('bool BackendAgent::initializeBaseAtBoot(')
method=source[start:source.index("\nvoid BackendAgent::startBootAutoBaseWhenReady(", start)]
helper=source[source.index('    double configNumber('):source.index('\n}\n\nbool BackendAgent::readStartupReceiverMode')]
harness=r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
#include <cmath>
#include <cstdlib>
#include "functions/gnss/gnss_cmd_builder.h"
constexpr size_t CONFIG_DOCUMENT_SIZE=4096;
namespace {
'''+helper+r'''
}
struct BackendAgent {
    struct StartupPosition {};
    String baseConfig_, baseStartupState_, baseStartupError_, sensorType_;
    bool baseStartupAttempted_=false; struct { bool all=false; } stationLock_;
    uint32_t lastReceiverPollMs_=0;
    bool dirty=false;
    void markStatusDirty() { dirty=true; }
    bool prepareStartupConfig(DynamicJsonDocument &d, JsonObject &b, bool &saved, String &method, String &) {
        if (deserializeJson(d,baseConfig_)) return false;
        b=d.as<JsonObject>(); saved=true; method=b["base_setup_method"] | String(); return true;
    }
    bool readStartupReceiverMode(GnssCmdBuilder::GnssSensorType, String &) { assert(false); return false; }
    bool buildStartupCommands(JsonObjectConst, GnssCmdBuilder::GnssSensorType, bool, GnssCmdBuilder::CommandList &, StartupPosition &, String &) { return false; }
    bool writeGnssCommands(const GnssCmdBuilder::CommandList &) { return false; }
    bool saveStatePreferences() { return true; }
    bool refreshReceiverReadback(String &) { return false; }
    bool verifyStartupReadback(GnssCmdBuilder::GnssSensorType, bool, const StartupPosition &, String &) { return false; }
    bool initializeBaseAtBoot(GnssCmdBuilder::GnssSensorType);
};
'''
checks=r'''
int main() {
    using GnssCmdBuilder::GnssSensorType;
    for (const char *config : {R"({"base_setup_method":"AUTO_CORS"})", R"({"base_setup_method":"AUTO_CORS","coords":{"lat":21}})"}) {
        BackendAgent agent; agent.baseConfig_=config;
        assert(agent.initializeBaseAtBoot(GnssSensorType::Ublox));
        assert(agent.baseStartupState_=="awaiting_configuration" && agent.dirty);
    }
    BackendAgent nearest;
    nearest.baseConfig_=R"({"base_setup_method":"AUTO_CORS","auto_cors_source_mode":"nearest","coords":{"lat":21,"lon":105,"alt":5}})";
    assert(nearest.initializeBaseAtBoot(GnssSensorType::Ublox) && nearest.baseStartupState_=="awaiting_auto_base");
    BackendAgent configured;
    configured.baseConfig_=R"({"base_setup_method":"AUTO_CORS","coords":{"lat":21,"lon":105,"alt":5}})";
    assert(configured.initializeBaseAtBoot(GnssSensorType::Ublox) && configured.baseStartupState_=="preserved");
}
'''
with tempfile.TemporaryDirectory(prefix='autocors-startup-') as directory:
    path=Path(directory); (path/'check.cpp').write_text(harness+method+checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(root/'test/host'),'-I'+str(root/'include'),
                    '-I'+str(root/'.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: unconfigured Auto CORS stays gated; saved coordinates remain preserved')
