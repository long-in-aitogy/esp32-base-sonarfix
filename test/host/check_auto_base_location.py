"""Exercise actual server ACK -> ESP32 ACK handler -> location matcher, plus NTRIP handshake."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root.parents[1] / 'cors_dashboard/backend'))
from app.control_plane_ack import build_control_plane_ack
probe = {'status_boot_id': 'boot-1', 'status_sequence': 42, 'auto_base_progress': {
    'phase': 'resolving_location', 'location_request': {
        'request_id': 'boot-1:1000', 'lat': '21.08499', 'lon': '105.786656', 'alt': '-8.0624'}}}
ack = build_control_plane_ack(probe, channel='mqtt', serial='station-1', server_timestamp=123)
source = (root / 'src/functions/backend/Backend_Agent_Workflows.cpp').read_text()
functions = source.split('namespace {', 1)[1].split('\n}\n\nvoid BackendAgent::setWorkflowProgress', 1)[0]
agent = (root / 'src/functions/backend/Backend_Agent.cpp').read_text()
handler = 'void BackendAgent::handleControlAck(' + agent.split('void BackendAgent::handleControlAck(', 1)[1].split('\nvoid BackendAgent::onMqttMessage', 1)[0]
ntrip = (root / 'src/functions/ntrip/ntrip_common.cpp').read_text()
handshake = 'bool waitForNtripResponse(' + ntrip.split('bool waitForNtripResponse(', 1)[1].split('} // namespace ntrip_common', 1)[0]
shim = (root / 'test/host/Arduino.h').read_text().replace('#pragma once', '')
shim = shim.replace('    void trim() {', '''    int indexOf(const char *value) const { const auto p = find(value); return p == npos ? -1 : int(p); }
    void trim() {''')
harness = r'''
#include <cassert>
#include <cmath>
#include <limits>
#include <cstdlib>
#include <fstream>
#include <iterator>
#include <ArduinoJson.h>
uint32_t now = 1000;
uint32_t millis() { return now; }
void delay(uint32_t duration) { now += duration; }
char queued[1536] = {};
int pushes = 0;
void xQueueOverwrite(void *, const void *data) { memcpy(queued, data, sizeof(queued)); ++pushes; }
struct BackendAgent {
    struct AutoBaseLocationReply { char json[1536]; };
    void *autoBaseLocationQueue_ = (void*)1;
    String statusBootId_ = "boot-1", serialNumber_ = "station-1";
    int32_t lastMqttAckSequence_ = -1, lastWebsocketAckSequence_ = -1;
    uint32_t lastMqttAckMs_ = 0, lastWebsocketAckMs_ = 0;
    bool active = true;
    bool workflowActive() const { return active; }
    void handleControlAck(const String &, const String &, bool);
};
struct Client {
    String wire;
    size_t index = 0;
    int available() { return index < wire.size() ? 1 : 0; }
    int read() { return index < wire.size() ? uint8_t(wire[index++]) : -1; }
    bool connected() { return index < wire.size(); }
};
'''
checks = r'''
int main(int argc, char **argv) {
    assert(argc == 2);
    DynamicJsonDocument audit(1024);
    audit["kT"] = datumParameterText(1.00000008613);
    audit["north"] = datumParameterText(2331863.611694837);
    for (int cycle = 0; cycle < 4; ++cycle) {
        String json;
        serializeJson(audit, json);
        audit.clear();
        assert(deserializeJson(audit, json) == DeserializationError::Ok);
    }
    assert(coordinateNumber(audit["kT"]) == 1.00000008613);
    assert(coordinateNumber(audit["north"]) == 2331863.611694837);
    assert(receiverCoordinateText(21.084990039, 9) == "21.084990039");
    assert(receiverCoordinateText(21.084990131093591, 10) == "21.0849901310");
    assert(receiverCoordinateText(-105.78665745895107, 10) == "-105.7866574589");
    assert(receiverCoordinateText(21.0849901310, 10) == "21.0849901310");
    assert(receiverCoordinateText(-8.0624567, 4) == "-8.0624");

    std::ifstream file(argv[1]);
    String message = std::string((std::istreambuf_iterator<char>(file)), {});
    BackendAgent agent;
    agent.handleControlAck("mqtt", message, false);
    assert(pushes == 1 && agent.lastMqttAckSequence_ == 42);
    DynamicJsonDocument received(2048), location(2048);
    assert(deserializeJson(received, queued) == DeserializationError::Ok);
    const String id = "boot-1:1000";
    assert(acceptAutoBaseLocationReply(received.as<JsonObjectConst>(), id, 21.08499, 105.786656, -8.0624, location));
    assert(location["province_code"] == "01" && location["l0_deg"] == 105);
    assert(!acceptAutoBaseLocationReply(received.as<JsonObjectConst>(), "old-session", 21.08499, 105.786656, -8.0624, location));
    assert(!acceptAutoBaseLocationReply(received.as<JsonObjectConst>(), id, 22.08499, 105.786656, -8.0624, location));
    received["location"]["input_coord"]["alt"] = nullptr;
    assert(!acceptAutoBaseLocationReply(received.as<JsonObjectConst>(), id, 21.08499, 105.786656, -8.0624, location));
    agent.handleControlAck("mqtt", message, true);
    assert(pushes == 1); // Retained ACKs never supply a location.
    agent.statusBootId_ = "new-boot";
    agent.handleControlAck("mqtt", message, false);
    assert(pushes == 1);
    agent.statusBootId_ = "boot-1"; agent.serialNumber_ = "different-device";
    agent.handleControlAck("mqtt", message, false);
    assert(pushes == 1);
    agent.serialNumber_ = "station-1";
    agent.handleControlAck("websocket", message, false);
    assert(pushes == 2 && agent.lastWebsocketAckSequence_ == 42);
    Client ntrip;
    ntrip.wire = "ICY 200 OK\r\n";
    ntrip.wire += char(0xD3); ntrip.wire += "datum-frame";
    assert(waitForNtripResponse(ntrip, nullptr, true));
    assert(ntrip.available() && ntrip.read() == 0xD3);
    Client httpNtrip;
    httpNtrip.wire = "HTTP/1.1 200 OK\r\nServer: caster\r\n\r\n";
    httpNtrip.wire += char(0xD3);
    assert(waitForNtripResponse(httpNtrip, nullptr, true));
    assert(httpNtrip.read() == 0xD3);
}
'''
with tempfile.TemporaryDirectory(prefix='esp-location-') as directory:
    path = Path(directory)
    (path / 'ack.json').write_text(json.dumps(ack))
    (path / 'check.cpp').write_text(shim + harness + functions + handler + handshake + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check'), str(path / 'ack.json')], check=True)
print('PASS: real server location ACK through ESP32 MQTT/WebSocket handler; rejects stale/wrong-device/wrong-LLH replies; preserves first NTRIP datum bytes')
