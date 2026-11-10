"""Every power cycle requests fresh AutoNearest, including after saved Fixed LLA."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Startup.cpp').read_text()
startup = source[source.index('bool BackendAgent::initializeBaseAtBoot('):source.index('bool BackendAgent::readStartupReceiverMode(')]
local_start = source[source.index('void BackendAgent::startBootAutoBaseWhenReady('):]
shim = (root / 'test/host/Arduino.h').read_text().replace('#pragma once', '')
harness = r'''
#include <cassert>
#include <ArduinoJson.h>
namespace GnssCmdBuilder { enum class GnssSensorType { Invalid, Ublox, Unicore }; }
constexpr size_t CONFIG_DOCUMENT_SIZE = 4096;
constexpr int WL_CONNECTED = 3;
bool gsm = false;
bool isGsmConnection() { return gsm; }
struct { int state = 0; int status() { return state; } } WiFi;
struct { bool up = false; bool isGprsConnected() { return up; } } modem;
struct BackendAgent {
    bool baseStartupAttempted_ = false, saved = true, dirty = false;
    struct { bool all = false; } stationLock_;
    bool licenseValid_ = true, active = false, queueOk = true;
    unsigned queued = 0;
    String statusBootId_ = "boot-local";
    String baseConfig_ = "{}", sensorType_, baseStartupState_, baseStartupError_;
    unsigned saves = 0;
    bool saveStatePreferences() { ++saves; return saved; }
    void markStatusDirty() { dirty = true; }
    bool initializeBaseAtBoot(GnssCmdBuilder::GnssSensorType);
    void startBootAutoBaseWhenReady();
    bool workflowActive() const { return active; }
    bool executeAutoBaseCommand(JsonObject request, String &error, String &) {
        ++queued;
        assert(request["source_mode"] == "nearest" && request["auto_apply"] == true);
        assert(request["startup_auto"] == true && request["startup_boot_id"] == "boot-local");
        if (!queueOk) { error = "queue failed"; return false; }
        active = true; baseStartupState_ = "auto_base_running"; return true;
    }
};
'''
checks = r'''
int main() {
    using GnssCmdBuilder::GnssSensorType;
    for (auto chip : {GnssSensorType::Ublox, GnssSensorType::Unicore}) {
        for (const char *method : {"FIXED_LLA", "SURVEY_IN", "AUTO_CORS", ""}) {
            BackendAgent agent;
            DynamicJsonDocument config(4096);
            config["base_setup_method"] = method;
            config["auto_cors_source_mode"] = "manual";
            config["coords"]["lat"] = 21;
            config["gnss_options"]["msm_level"] = "7";
            agent.baseConfig_.clear();
            serializeJson(config, agent.baseConfig_);
            assert(agent.initializeBaseAtBoot(chip));
            assert(agent.baseStartupState_ == "awaiting_auto_base");
            deserializeJson(config, agent.baseConfig_);
            assert(config["base_setup_method"] == "AUTO_CORS");
            assert(config["auto_cors_source_mode"] == "nearest");
            assert(!config.containsKey("coords"));
            assert(config["gnss_options"]["msm_level"] == "7");
            assert(agent.initializeBaseAtBoot(chip) && agent.saves == 1);
        }
    }
    BackendAgent fresh;
    assert(fresh.initializeBaseAtBoot(GnssSensorType::Ublox));
    DynamicJsonDocument defaults(4096); deserializeJson(defaults, fresh.baseConfig_);
    assert(defaults["gnss_options"]["output_mode"] == "rtcm_only");
    BackendAgent locked; locked.stationLock_.all = true;
    assert(locked.initializeBaseAtBoot(GnssSensorType::Ublox));
    assert(locked.baseStartupState_ == "locked" && locked.saves == 0);
    BackendAgent failed; failed.saved = false;
    assert(!failed.initializeBaseAtBoot(GnssSensorType::Ublox));
    assert(failed.baseStartupState_ == "error");
    // No MQTT client, backend or user assignment exists in this harness.
    fresh.startBootAutoBaseWhenReady(); assert(fresh.queued == 0);
    WiFi.state = WL_CONNECTED;
    fresh.startBootAutoBaseWhenReady(); assert(fresh.queued == 1);
    fresh.startBootAutoBaseWhenReady(); assert(fresh.queued == 1);
    fresh.active = false; fresh.startBootAutoBaseWhenReady(); assert(fresh.queued == 1);
    BackendAgent sim; sim.baseStartupState_ = "awaiting_auto_base";
    gsm = true; sim.startBootAutoBaseWhenReady(); assert(sim.queued == 0);
    modem.up = true; sim.startBootAutoBaseWhenReady(); assert(sim.queued == 1);
    BackendAgent unlicensed; unlicensed.baseStartupState_ = "awaiting_auto_base";
    unlicensed.licenseValid_ = false; unlicensed.startBootAutoBaseWhenReady(); assert(unlicensed.queued == 0);
    BackendAgent queueFailure; queueFailure.baseStartupState_ = "awaiting_auto_base";
    queueFailure.queueOk = false; queueFailure.startBootAutoBaseWhenReady();
    assert(queueFailure.baseStartupState_ == "error");
    queueFailure.startBootAutoBaseWhenReady(); assert(queueFailure.queued == 1);
    BackendAgent unknown;
    assert(!unknown.initializeBaseAtBoot(GnssSensorType::Invalid));
    assert(!unknown.baseStartupAttempted_ && unknown.saves == 0);
    assert(unknown.initializeBaseAtBoot(GnssSensorType::Ublox));
}
'''
with tempfile.TemporaryDirectory(prefix='auto-base-boot-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(shim + harness + startup + local_start + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: fresh AutoNearest at boot for both chips and saved modes; options, lock, persistence failure and detection retry')
