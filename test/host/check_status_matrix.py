"""Exercise the production status builder across the 144 CORS status cases."""
from pathlib import Path
import json
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
shim = (root / 'test/host/Arduino.h').read_text().replace('#pragma once', '')
shim = shim.replace('    bool isEmpty() const', '''    String(const char *text) : std::string(text ? text : "") {}
    String &operator=(const char *text) { assign(text ? text : ""); return *this; }
    long toInt() const { return std::strtol(c_str(), nullptr, 10); }
    bool startsWith(const String &prefix) const { return compare(0, prefix.size(), prefix) == 0; }
    int indexOf(const String &value) const { auto p = find(value); return p == npos ? -1 : int(p); }
    void remove(size_t start, size_t count) { erase(start, count); }
    void toLowerCase() { std::transform(begin(), end(), begin(), [](unsigned char c) { return std::tolower(c); }); }
    bool isEmpty() const''')
snapshot = 'struct GnssTrafficCounters' + (root / 'include/functions/ntrip/RTCM_Receiver.h').read_text().split('struct GnssTrafficCounters', 1)[1].split('String receiveRtcmFromGnss()', 1)[0]
common = r'''
#include <cstdlib>
#include <cmath>
#include <iostream>
#include <vector>
#include <array>
#include <memory>
#include <ArduinoJson.h>
#include "functions/gnss/Unicore_Reply.h"
#include "functions/gnss/Ubx_Base_Status.h"
#include "functions/backend/Station_Lock.h"
#include "functions/gnss/Ubx_Navigation.h"
class Stream;
class BackendAgentWebsocket {};
using QueueHandle_t = void *;
using SemaphoreHandle_t = void *;
using TaskHandle_t = void *;
namespace GnssCmdBuilder { enum class GnssSensorType { Invalid, Ublox, Unicore }; using Command = std::vector<uint8_t>; using CommandList = std::vector<Command>; }
constexpr size_t CONFIG_DOCUMENT_SIZE = 6144, STATUS_DOCUMENT_SIZE = 8192, VERIFICATION_DOCUMENT_SIZE = 12288, PROGRESS_DOCUMENT_SIZE = 8192;
constexpr unsigned BACKEND_CONTROL_STALE_MS = 30000, BACKEND_CONTROL_RECOVERY_MS = 10000;
constexpr const char *AGENT_VERSION = "test", *MQTT_SERVER = "broker", *BACKEND_HOST = "backend";
unsigned now = 10000, saves = 0;
uint32_t millis() { return now; }
struct { unsigned baudRate() { return 115200; } } Serial1;
struct { int RSSI() { return -50; } } WiFi;
struct { int getSignalQuality() { return 20; } } modem;
struct {
    unsigned getHeapSize() { return 300000; }
    unsigned getFreeHeap() { return 150000; }
    unsigned getCpuFreqMHz() { return 240; }
    unsigned getFlashChipSize() { return 4194304; }
} ESP;
bool isWifiConnection() { return true; }
bool isGsmConnection() { return false; }
unsigned getRtcmInputBps() { return 100; }
unsigned ntripServerBps(unsigned id) { return id * 50; }
bool ntripServerConnected(unsigned id) { return id == 1; }
String ntripServerError(unsigned) { return ""; }
unsigned ntripRoverBytesReceived() { return 500; }
unsigned ntripRoverPacketsReceived() { return 10; }
void appendStorageStatus(JsonObject system) { system["nvs"]["cleanup_supported"] = true; }
namespace BackendAgentInternal {
String epochString() { return "1700000000"; }
String tokenFingerprint(const String &) { return "fingerprint"; }
String readPreference(const char *, const String &fallback) { return fallback; }

}
'''
checks = r'''
BackendAgent::BackendAgent() = default;
BackendAgent::~BackendAgent() = default;
bool BackendAgent::mqttConnected() const { return true; }
bool BackendAgent::websocketConnected() const { return false; }
bool BackendAgent::saveStatePreferences() { ++saves; return true; }
int main() {
    for (const char *state : {"online", "configuring", "rebooting", "rebooting_for_reset", "auto_setup_base", "reference_check_queued"})
        for (unsigned flags = 0; flags < 8; ++flags)
            for (const char *chip : {"UNKNOWN", "Ublox", "Unicorecomm"}) {
                BackendAgent agent;
                agent.serialNumber_ = "test"; agent.agentState_ = state;
                agent.licenseValid_ = flags & 1; agent.provisioned_ = flags & 2;
                agent.stationLock_.all = flags & 4; agent.sensorType_ = chip;
                agent.serviceConfig_ = R"({"stream_on_demand":true,"server1_enabled":true,"server2_enabled":true,"server1_stream_active":true})";
                agent.navigationMs_ = agent.dopMs_ = agent.unicoreQualityMs_ = 9000;
                agent.unicoreHorizontalSigma_ = 0.015;
                agent.navigation_.valid = true; agent.navigation_.haccMm = 12;
                agent.satelliteReadback_ = "satellites"; agent.satelliteReadbackMs_ = 9000;
                agent.versionReadback_ = "version"; agent.receiverInfoMs_ = 9000;
                agent.gnssVerification_ = R"({"state":"match"})"; agent.gnssVerificationMs_ = 9000;
                agent.nvsInventory_ = R"({"entries":[]})"; agent.nvsInventoryMs_ = 9000;
                agent.lastCommandResult_ = R"({"command_id":"check","status":"success","detail":"ok"})";
                agent.autoBaseProgress_ = R"({"phase":"ready_for_review","fixed_samples_only":true,"conversion_report":{"k0":0.9999}})";
                std::cout << agent.buildStatusPayload() << '\n';
            }
}

'''

header = (root / 'include/functions/backend/Backend_Agent.h').read_text()
header = re.sub(r'^#include.*$', '', header, flags=re.M).replace('private:', 'public:')
status = (root / 'src/functions/backend/Backend_Agent_Status.cpp').read_text()
status = re.sub(r'^#include.*$', '', status, flags=re.M)
agent = (root / 'src/functions/backend/Backend_Agent.cpp').read_text()
helpers = agent[agent.index('    bool jsonBool('):agent.index('\n} // namespace BackendAgentInternal')]
active = agent[agent.index('bool BackendAgent::effectiveStreamActive('):agent.index('bool BackendAgent::mqttConnected(')]
telemetry = snapshot + '\nGnssTelemetrySnapshot getGnssTelemetrySnapshot() { GnssTelemetrySnapshot s; s.hasData = true; s.lastDataMs = s.lastGgaMs = 9000; s.satellites = 20; return s; }\n'
with tempfile.TemporaryDirectory(prefix='status-matrix-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(shim + common + 'namespace BackendAgentInternal {\nString jsonString(JsonObjectConst, const String &, const String & = String());\n' + helpers + '\n}\n' + telemetry + header + status + active + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'include'), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    actual = [json.loads(line) for line in subprocess.check_output([str(path / 'check')], text=True).splitlines()]

assert len(actual) == 144
states = ('online', 'configuring', 'rebooting', 'rebooting_for_reset', 'auto_setup_base', 'reference_check_queued')
for index, row in enumerate(actual):
    state, flags = states[index // 24], (index // 3) % 8
    expected = ('locked' if flags & 4 else state if state != 'online' else
                'awaiting_license' if not flags & 1 else 'unprovisioned' if not flags & 2 else 'online')
    assert row['status'] == expected
    assert row['is_provisioned'] is bool(flags & 2) and row['is_locked'] is bool(flags & 4)
    assert row['serial'] == 'test' and row['version'] == 'test'
    assert row['system_info']['gnss_verification']['state'] == 'match'
    assert row['system_info']['nvs']['last_action']['command_id'] == 'check'
    assert row['auto_base_progress']['conversion_report']['k0'] == 0.9999
    if row['detected_chip_type'] == 'UNKNOWN':
        assert row['hacc'] is None
    elif row['detected_chip_type'] == 'Ublox':
        assert row['hacc'] == 12
    else:
        assert abs(row['hacc'] - 15) < 0.001
print('PASS: 144 status combinations preserve state, verification and GNSS quality')
