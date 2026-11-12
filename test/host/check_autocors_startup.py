"""An Auto CORS base without coordinates must not enable SOURCE at boot."""
from pathlib import Path
import subprocess
import tempfile
from host_coverage import compile_cpp, mapped, run_cpp
root=Path(__file__).resolve().parents[2]
source=(root/'src/functions/backend/Backend_Agent_Startup.cpp').read_text()
start=source.index('bool BackendAgent::initializeBaseAtBoot(')
method=source[start:source.index("\nvoid BackendAgent::startBootAutoBaseWhenReady(", start)]
helper=source[source.index('    double configNumber('):source.index('\n}\n\nbool BackendAgent::readStartupReceiverMode')]
prepare=source[source.index('bool BackendAgent::prepareStartupConfig('):source.index('bool BackendAgent::buildStartupCommands(')]
harness=r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
#include <cmath>
#include <cstdlib>
#include "functions/gnss/gnss_cmd_builder.h"
constexpr size_t CONFIG_DOCUMENT_SIZE=6144;
namespace {
constexpr uint32_t AUTO_SURVEY_IN_SECONDS=120;
'''+mapped(root/'src/functions/backend/Backend_Agent_Startup.cpp',helper)+r'''
}
struct BackendAgent {
    struct StartupPosition {};
    String baseConfig_, baseStartupState_, baseStartupError_, sensorType_;
    bool baseStartupAttempted_=false; struct { bool all=false; } stationLock_;
    uint32_t lastReceiverPollMs_=0;
    bool dirty=false, readOk=true, buildOk=true, writeOk=true, saveOk=true, refreshOk=true, verifyOk=true;
    int reads=0, writes=0, saves=0, refreshes=0;
    void markStatusDirty() { dirty=true; }
    bool prepareStartupConfig(DynamicJsonDocument &, JsonObject &, bool &, String &, String &);
    bool readStartupReceiverMode(GnssCmdBuilder::GnssSensorType, String &) { ++reads; return readOk; }
    bool buildStartupCommands(JsonObjectConst, GnssCmdBuilder::GnssSensorType, bool, GnssCmdBuilder::CommandList &commands, StartupPosition &, String &error) {
        if (!buildOk) { error="invalid saved config"; return false; }
        commands.push_back({1}); return true;
    }
    bool writeGnssCommands(const GnssCmdBuilder::CommandList &) { ++writes; return writeOk; }
    bool saveStatePreferences() { ++saves; return saveOk; }
    bool refreshReceiverReadback(String &error) { ++refreshes; if (!refreshOk) error="readback failed"; return refreshOk; }
    bool verifyStartupReadback(GnssCmdBuilder::GnssSensorType, bool, const StartupPosition &, String &error) {
        if (!verifyOk) error="receiver mismatch";
        return verifyOk;
    }
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
    assert(nearest.reads==0 && nearest.writes==0 && nearest.saves==0);
    BackendAgent configured;
    configured.baseConfig_=R"({"base_setup_method":"AUTO_CORS","coords":{"lat":21,"lon":105,"alt":5}})";
    assert(configured.initializeBaseAtBoot(GnssSensorType::Ublox) && configured.baseStartupState_=="preserved");
    assert(configured.reads==0 && configured.writes==0 && configured.saves==0);

    BackendAgent unknown;
    assert(!unknown.initializeBaseAtBoot(GnssSensorType::Invalid));
    assert(!unknown.baseStartupAttempted_ && unknown.baseStartupState_=="awaiting_receiver" && unknown.dirty);
    BackendAgent locked; locked.baseConfig_=R"({"base_setup_method":"FIXED_LLA"})"; locked.stationLock_.all=true;
    assert(locked.initializeBaseAtBoot(GnssSensorType::Ublox) && locked.baseStartupState_=="locked" && locked.reads==0);
    BackendAgent fresh; fresh.baseConfig_="{}";
    assert(fresh.initializeBaseAtBoot(GnssSensorType::Ublox) && fresh.baseStartupState_=="survey_started");
    DynamicJsonDocument freshConfig(1024); assert(!deserializeJson(freshConfig,fresh.baseConfig_));
    assert(freshConfig["base_setup_method"]=="SURVEY_IN" && freshConfig["survey_in_duration"]==120);
    assert(freshConfig["survey_in_accuracy"]==5 && fresh.saves==1);
    BackendAgent bad; bad.baseConfig_="{invalid";
    assert(!bad.initializeBaseAtBoot(GnssSensorType::Ublox) && bad.baseStartupState_=="error" && bad.reads==0);
    BackendAgent noMode; noMode.baseConfig_=R"({"coords":{"lat":21}})";
    assert(!noMode.initializeBaseAtBoot(GnssSensorType::Ublox) && noMode.baseStartupState_=="error" && noMode.reads==0);
    for (const char *mode : {"SURVEY_IN", "FIXED_LLA"}) {
        BackendAgent valid; valid.baseConfig_=String("{\"base_setup_method\":\"")+mode+"\"}";
        assert(valid.initializeBaseAtBoot(GnssSensorType::Ublox));
        assert(valid.baseStartupState_==(String(mode)=="FIXED_LLA"?"fixed_restored":"survey_started"));
        assert(valid.reads==1 && valid.writes==1 && valid.saves==1 && valid.refreshes==1);
        assert(valid.initializeBaseAtBoot(GnssSensorType::Ublox) && valid.writes==1);
    }
    for (int failure=0; failure<6; ++failure) {
        BackendAgent agent; agent.baseConfig_=R"({"base_setup_method":"FIXED_LLA"})";
        if (failure==0) agent.readOk=false;
        if (failure==1) agent.buildOk=false;
        if (failure==2) agent.writeOk=false;
        if (failure==3) agent.saveOk=false;
        if (failure==4) agent.refreshOk=false;
        if (failure==5) agent.verifyOk=false;
        const String before=agent.baseConfig_;
        assert(!agent.initializeBaseAtBoot(GnssSensorType::Ublox));
        assert(agent.baseStartupState_=="error" && !agent.baseStartupError_.isEmpty() && agent.dirty);
        assert(agent.baseConfig_==before);
        assert(!agent.initializeBaseAtBoot(GnssSensorType::Ublox));
    }
}
'''
with tempfile.TemporaryDirectory(prefix='autocors-startup-') as directory:
    startup_path=root/'src/functions/backend/Backend_Agent_Startup.cpp'
    path=Path(directory); (path/'check.cpp').write_text(harness+mapped(startup_path,prepare)+mapped(startup_path,method)+checks)
    compile_cpp(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(root/'test/host'),'-I'+str(root/'include'),
                    '-I'+str(root/'.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    run_cpp([str(path/'check')],check=True)
print('PASS: boot configuration, lock, receiver failures, persistence and readback')
