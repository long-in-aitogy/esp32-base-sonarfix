"""Verify fresh AutoNearest startup follows geodetic for every saved mode."""
from pathlib import Path
import tempfile
from host_coverage import compile_cpp, mapped, run_cpp

root = Path(__file__).resolve().parents[2]
source_path = root / 'src/functions/backend/Backend_Agent_Startup.cpp'
source = source_path.read_text()
method = source[source.index('bool BackendAgent::initializeBaseAtBoot('):source.index('void BackendAgent::startBootAutoBaseWhenReady(')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
#include "functions/gnss/gnss_cmd_builder.h"
constexpr size_t CONFIG_DOCUMENT_SIZE = 6144;
struct BackendAgent {
    String baseConfig_, baseStartupState_, baseStartupError_, sensorType_;
    bool baseStartupAttempted_ = false, dirty = false, saveOk = true;
    struct { bool all = false; } stationLock_;
    int saves = 0;
    void markStatusDirty() { dirty = true; }
    bool saveStatePreferences() { ++saves; return saveOk; }
    bool initializeBaseAtBoot(GnssCmdBuilder::GnssSensorType);
};
'''
checks = r'''
int main() {
    using GnssCmdBuilder::GnssSensorType;
    for (const char *config : {"{}", R"({"base_setup_method":"SURVEY_IN","survey_in_accuracy":5})",
        R"({"base_setup_method":"FIXED_LLA","coords":{"lat":21,"lon":105,"alt":10},"auto_base_previous_config":{"base_setup_method":"FIXED_LLA"},"gnss_options":{"msm_level":"7"}})",
        R"({"base_setup_method":"AUTO_CORS","auto_cors_source_mode":"manual"})"}) {
        BackendAgent agent; agent.baseConfig_ = config;
        assert(agent.initializeBaseAtBoot(GnssSensorType::Ublox));
        assert(agent.baseStartupState_ == "awaiting_auto_base" && agent.saves == 1 && agent.dirty);
        DynamicJsonDocument saved(2048); assert(!deserializeJson(saved, agent.baseConfig_));
        assert(saved["base_setup_method"] == "AUTO_CORS" && saved["auto_cors_source_mode"] == "nearest");
        assert(saved["mode"] == "BASE" && saved["coords"].isNull());
        assert(saved["auto_base_previous_config"].isNull());
        assert(saved["gnss_options"].is<JsonObject>());
        if (String(config).indexOf("FIXED_LLA") >= 0) assert(saved["gnss_options"]["msm_level"] == "7");
        assert(agent.initializeBaseAtBoot(GnssSensorType::Ublox) && agent.saves == 1);
    }
    BackendAgent unknown; assert(!unknown.initializeBaseAtBoot(GnssSensorType::Invalid));
    assert(!unknown.baseStartupAttempted_ && unknown.baseStartupState_ == "awaiting_receiver");
    BackendAgent locked; locked.baseConfig_ = "{}"; locked.stationLock_.all = true;
    assert(locked.initializeBaseAtBoot(GnssSensorType::Ublox) && locked.baseStartupState_ == "locked" && locked.saves == 0);
    BackendAgent invalid; invalid.baseConfig_ = "{invalid";
    assert(!invalid.initializeBaseAtBoot(GnssSensorType::Ublox) && invalid.baseStartupState_ == "error");
    BackendAgent failed; failed.baseConfig_ = "{}"; failed.saveOk = false;
    assert(!failed.initializeBaseAtBoot(GnssSensorType::Ublox) && failed.baseStartupState_ == "error");
}
'''
# The host shim uses std::string; add the Arduino indexOf method used by this check.
shim = (root / 'test/host/Arduino.h').read_text().replace('    bool isEmpty()', '    int indexOf(const char *s) const { auto p = find(s); return p == npos ? -1 : int(p); }\n    bool isEmpty()')
with tempfile.TemporaryDirectory(prefix='autocors-startup-') as directory:
    path = Path(directory)
    (path / 'Arduino.h').write_text(shim)
    (path / 'check.cpp').write_text(harness + mapped(source_path, method) + checks)
    compile_cpp(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                 '-I' + str(path), '-I' + str(root / 'include'),
                 '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                 str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    run_cpp([str(path / 'check')], check=True)
print('PASS: fresh AutoNearest at boot, saved mode replacement, lock and persistence failures')
