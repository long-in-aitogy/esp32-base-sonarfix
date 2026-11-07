"""Exercise Fixed LLA confirmation and Auto Base progress recovery at boot."""
from pathlib import Path
import subprocess
import tempfile
from host_coverage import compile_cpp, run_cpp, cpp_output, mapped

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Startup.cpp').read_text()
helpers = source[source.index('double configNumber('):source.index('\n}\n\nbool BackendAgent::initializeBaseAtBoot')]
storage = (root / 'src/functions/backend/Backend_Agent_Storage.cpp').read_text()
restore_progress = storage[storage.index('String restoreWorkflowProgress('):storage.index('} // namespace')]
reconcile = source[source.index('void BackendAgent::reconcileBaseStartupReadback('):]
verification = (root / 'src/functions/backend/Backend_Agent_Gnss.cpp').read_text()
verification = verification[verification.index('bool BackendAgent::verifyUnicoreConfig('):verification.index('bool BackendAgent::verifyGnssConfig(')]
shim = (root / 'test/host/Arduino.h').read_text().replace('#pragma once', '')
shim = shim.replace('    bool isEmpty() const', """    using std::string::operator=;
    String &operator=(const char *value) { assign(value ? value : ""); return *this; }
    bool startsWith(const char *prefix) const { return find(prefix) == 0; }
    bool isEmpty() const""")
harness = r'''
#include <cassert>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <ArduinoJson.h>
#include "functions/gnss/Unicore_Config_Verification.h"
String operator+(const String &text, uint8_t value) { return String(std::string(text) + std::to_string(value)); }
constexpr size_t CONFIG_DOCUMENT_SIZE = 4096, VERIFICATION_DOCUMENT_SIZE = 12288;
constexpr uint8_t GNSS_UNICORE_PORT = 0;
uint32_t millis() { return 1000; }
namespace UnicoreReadback {
String modeReply = "MODE BASE 21.08498988770 105.78665639630 -7.993300";
bool readMode(String &mode, String &) { mode = modeReply; return true; }
const char *modeKind(const String &mode) { return mode.find("MODE BASE TIME") == 0 ? "survey_in" : "base"; }
bool readLogList(String &logs, String &) {
    logs = "#UNILOGLIST,header;< 2\r\n< RTCM1006 COM1 1\r\n< RTCM1006 COM2 2\r\n\r\n"; return true;
}
}

struct BackendAgent {
    String baseConfig_, sensorType_ = "Unicorecomm";
    String baseStartupState_ = "error";
    String baseStartupError_ = "Receiver has not confirmed the saved fixed position";
    bool dirty = false;
    String gnssVerification_, nvsInventory_;
    uint32_t gnssVerificationMs_ = 0;
    bool verifyUnicoreConfig(JsonObjectConst, const String &, String &);
    void markStatusDirty() { dirty = true; }
    void reconcileBaseStartupReadback(JsonObjectConst);
};
'''
checks = r'''
int main() {
    for (const char *saved : {"{}", "{broken", R"({"phase":"queued"})",
            R"({"phase":"wait_fix","last_raw_gga":"old"})", R"({"phase":"averaging"})",
            R"({"phase":"resolving_location"})", R"({"phase":"stopping"})",
            R"({"phase":"reference_check_wait_fix"})"}) {
        assert(restoreWorkflowProgress(saved) == "{}");
    }
    for (const char *saved : {
            R"({"phase":"ready_for_review","fixed_samples_only":true,"averaged_coord":{"lat":"21.0849898877"}})",
            R"({"phase":"completed"})", R"({"phase":"stopped"})", R"({"phase":"failed"})",
            R"({"phase":"reference_check_completed"})", R"({"phase":"reference_check_failed"})"}) {
        assert(restoreWorkflowProgress(saved) == saved);
    }

    BackendAgent agent;
    agent.baseConfig_ = R"({"base_setup_method":"FIXED_LLA","altitude_reference":"ELLIPSOID","coords":{"lat":21.0849898877,"lon":105.7866563964,"alt":-7.9933}})";
    DynamicJsonDocument doc(2048);
    deserializeJson(doc, R"({"state":"ok","mode_kind":"base","bestpos":{"state":"unavailable"}})");
    auto checkPending = [&]() {
        agent.reconcileBaseStartupReadback(doc.as<JsonObjectConst>());
        assert(agent.baseStartupState_ == "error" && !agent.dirty);
    };
    checkPending(); // MODE BASE alone does not confirm the position.
    doc["mode_raw"] = "MODE BASE 21.08498988770 105.78665639630 -7.993300";
    doc["mode_kind"] = "rover"; checkPending();
    doc["mode_kind"] = "base";
    agent.baseStartupError_ = "Receiver rejected startup configuration";
    checkPending(); // Position confirmation must not hide command failures.
    agent.baseStartupError_ = "Receiver has not confirmed the saved fixed position";
    auto confirm = [&]() {
        agent.reconcileBaseStartupReadback(doc.as<JsonObjectConst>());
        assert(agent.baseStartupState_ == "fixed_restored");
        assert(agent.baseStartupError_.isEmpty() && agent.dirty);
        agent.baseStartupState_ = "error";
        agent.baseStartupError_ = "Receiver has not confirmed the saved fixed position";
        agent.dirty = false;
    };
    confirm(); // The actual MODE reply confirms Fixed LLA even without BESTNAV.
    for (const char *bad : {"MODE BASE", "MODE BASE TIME 120", "MODE BASE 21 105 nan",
            "MODE BASE 91 105 0", "MODE BASE 21 181 0", "MODE BASE 21 105 0 extra",
            "MODE BASE 21.09 105.78665639630 -7.993300",
            "MODE BASE 21.08498988770 105.78665639630 -7.9"}) {
        doc["mode_raw"] = bad;
        checkPending();
    }
    agent.baseConfig_ = R"({"base_setup_method":"FIXED_LLA","coords":{"lat":21.0849898877,"lon":105.7866563964,"alt":-9.9933}})";
    doc["mode_raw"] = "MODE BASE 21.08498988770 105.78665639640 -9.993300";
    confirm(); // MODE contains the configured altitude for legacy configurations too.
    doc["bestpos"]["state"] = "ok";
    doc["bestpos"]["position_type"] = "FIXEDPOS";
    agent.sensorType_ = "Ublox";
    doc["bestpos"]["lat"] = "21.0849898877";
    doc["bestpos"]["lon"] = "105.7866563964";
    doc["bestpos"]["alt"] = "-9.9933";
    confirm();
    doc["bestpos"]["alt"] = "-9.9"; checkPending();
    doc["bestpos"]["alt"] = "-9.9933";
    doc["bestpos"]["lat"] = "21.09"; checkPending();
    doc["bestpos"]["lat"] = "21.0849898877";
    doc["state"] = "error"; checkPending();
    doc["state"] = "ok";
    agent.baseConfig_ = "{}"; checkPending();
    agent.baseConfig_ = "invalid"; checkPending();
    DynamicJsonDocument payload(1024), result(12288);
    deserializeJson(payload, R"({"coords":{"lat":21.084989887741354,"lon":105.78665639636496,"alt":-7.9932645633816719},"altitude_reference":"ELLIPSOID","logs":["RTCM1006"]})");
    String error;
    payload["port"] = "COM1";
    assert(agent.verifyUnicoreConfig(payload.as<JsonObjectConst>(), "check", error));
    deserializeJson(result, agent.gnssVerification_);
    assert(result["state"] == "match");
    assert(result["details"]["fixed"]["actual"]["self_position"]["lat"].is<double>());
    assert(result["details"]["fixed"]["actual"]["coordinate_source"] == "MODE");
    assert(result["details"]["compare_ports"][0] == "COM1");
    assert(result["details"]["port_source"] == "user_selection");
    payload["port"] = "COM2";
    assert(agent.verifyUnicoreConfig(payload.as<JsonObjectConst>(), "check", error));
    result.clear(); deserializeJson(result, agent.gnssVerification_);
    assert(result["state"] == "mismatch" && result["groups"]["rtcm"]["unread"] == 0);
    assert(result["details"]["compare_ports"][0] == "COM2");
    payload["port"] = "COM9";
    assert(!agent.verifyUnicoreConfig(payload.as<JsonObjectConst>(), "check", error));
    payload["port"] = "COM1";
    UnicoreReadback::modeReply = "MODE BASE 21 105 -7";
    assert(agent.verifyUnicoreConfig(payload.as<JsonObjectConst>(), "check", error));
    result.clear(); deserializeJson(result, agent.gnssVerification_);
    assert(result["state"] == "mismatch");
    UnicoreReadback::modeReply = "MODE BASE";
    assert(agent.verifyUnicoreConfig(payload.as<JsonObjectConst>(), "check", error));
    result.clear(); deserializeJson(result, agent.gnssVerification_);
    assert(result["state"] == "unread");
}
'''
helpers = mapped(root / 'src/functions/backend/Backend_Agent_Startup.cpp', helpers)
reconcile = mapped(root / 'src/functions/backend/Backend_Agent_Startup.cpp', reconcile)
verification = mapped(root / 'src/functions/backend/Backend_Agent_Gnss.cpp', verification)
with tempfile.TemporaryDirectory(prefix='base-confirmation-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(shim + harness + helpers + restore_progress + reconcile + verification + checks)
    compile_cpp(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    '-I' + str(root / 'include'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    run_cpp([str(path / 'check')], check=True)
print('PASS: delayed Fixed LLA confirmation clears startup error; MODE coordinates confirm Unicore without BESTNAV; malformed modes, wrong coordinates and unrelated errors remain blocked')
print('PASS: reboot drops interrupted Auto Base progress and preserves saved results')
