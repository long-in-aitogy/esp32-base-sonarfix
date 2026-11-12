"""Exercise firmware telemetry queues and delivery with simulated transports."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent.cpp').read_text()
packets = source[source.index('    constexpr size_t MAX_NMEA_PACKET'):source.index('    String epochString()')]
methods = source[source.index('void BackendAgent::enqueueNmea('):source.index('void BackendAgent::setupWebsocket(')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <algorithm>
#include <array>
#include <cassert>
#include <cstring>
#include <deque>
#include <vector>
#define BACKEND_PUBLISH_RAW_RTCM 1
constexpr int pdTRUE = 1;
using std::min;
struct Queue { size_t capacity, size; std::deque<std::vector<uint8_t>> items; };
int xQueueSend(Queue *q, const void *data, int) {
    if (q->items.size() == q->capacity) return 0;
    const auto *p = static_cast<const uint8_t *>(data); q->items.emplace_back(p, p + q->size); return pdTRUE;
}
int xQueueSendToFront(Queue *q, const void *data, int) {
    if (q->items.size() == q->capacity) return 0;
    const auto *p = static_cast<const uint8_t *>(data); q->items.emplace_front(p, p + q->size); return pdTRUE;
}
int xQueueReceive(Queue *q, void *data, int) {
    if (q->items.empty()) return 0;
    std::memcpy(data, q->items.front().data(), q->size); q->items.pop_front(); return pdTRUE;
}
struct Mqtt {
    bool up = false, accept = true; std::vector<std::vector<uint8_t>> delivered;
    bool publish(const char *, const uint8_t *data, size_t n) {
        if (!accept) return false;
        delivered.emplace_back(data, data+n);
        return true;
    }
} mqtt;
struct Socket {
    bool up = false, accept = true; std::vector<String> delivered;
    bool sendText(const String &s) { if (!accept) return false; delivered.push_back(s); return true; }
} socket;
'''
agent = r'''
struct BackendAgent {
    Queue *nmeaQueue_, *rtcmQueue_; Socket *websocket_ = &socket;
    bool mqttConnected() const { return mqtt.up; }
    bool websocketConnected() const { return websocket_->up; }
    String rawDataTopic() const { return "raw"; }
    void enqueueNmea(const uint8_t *, size_t);
    void enqueueRtcm(const uint8_t *, size_t);
    void drainDataQueues();
};
'''
checks = r'''
int main() {
    Queue nmea{NMEA_QUEUE_LENGTH, sizeof(NmeaPacket), {}}, rtcm{RTCM_QUEUE_LENGTH, sizeof(DataPacket), {}};
    BackendAgent agent{&nmea, &rtcm};
    for (unsigned i = 0; i < NMEA_QUEUE_LENGTH + 1; ++i) {
        const uint8_t value[] = {static_cast<uint8_t>('A' + i)}; agent.enqueueNmea(value, sizeof(value));
    }
    assert(nmea.items.size() == NMEA_QUEUE_LENGTH);
    const uint8_t frame[] = {0xd3, 0, 1};
    for (unsigned i = 0; i < RTCM_QUEUE_LENGTH + 1; ++i) agent.enqueueRtcm(frame, sizeof(frame));
    assert(rtcm.items.size() == RTCM_QUEUE_LENGTH);
    agent.drainDataQueues();
    assert(nmea.items.size() == NMEA_QUEUE_LENGTH && rtcm.items.size() == RTCM_QUEUE_LENGTH);
    socket.up = true; agent.drainDataQueues();
    assert(nmea.items.empty() && socket.delivered.size() == NMEA_QUEUE_LENGTH && rtcm.items.size() == RTCM_QUEUE_LENGTH);
    DynamicJsonDocument first(256); assert(!deserializeJson(first, socket.delivered.front()));
    assert(first["type"] == "nmea_update" && first["payload"] == "B");
    mqtt.up = true; mqtt.accept = false; agent.drainDataQueues(); assert(rtcm.items.size() == RTCM_QUEUE_LENGTH);
    mqtt.accept = true; agent.drainDataQueues();
    assert(rtcm.items.empty() && mqtt.delivered.size() == RTCM_QUEUE_LENGTH);
    std::vector<uint8_t> large(MAX_NMEA_PACKET + 100, 'x');
    agent.enqueueNmea(large.data(), large.size()); agent.drainDataQueues();
    assert(mqtt.delivered.back().size() == MAX_NMEA_PACKET - 1);
    std::vector<uint8_t> oversized(MAX_RTCM_PACKET + 1, 1);
    agent.enqueueRtcm(oversized.data(), oversized.size()); assert(rtcm.items.empty());
}
'''
with tempfile.TemporaryDirectory(prefix='backend-queues-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + 'namespace BackendAgentInternal {\n' + packets + '\n}\nusing namespace BackendAgentInternal;\n' + agent + methods + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: bounded telemetry queues, outage preservation and MQTT/WebSocket delivery')
