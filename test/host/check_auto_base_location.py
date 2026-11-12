"""Exercise control ACK queueing and request/coordinate correlation."""
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[2]
workflow=(root/'src/functions/backend/Backend_Agent_Workflows.cpp').read_text()
a=workflow.index('    double coordinateNumber('); b=workflow.index('} // namespace',a)
helpers=workflow[a:b]
agent=(root/'src/functions/backend/Backend_Agent.cpp').read_text()
a=agent.index('void BackendAgent::handleControlAck('); b=agent.index('\nvoid BackendAgent::onMqttMessage(',a)
handler=agent[a:b]
harness=r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
#include <cmath>
#include <cstdlib>
#include <cstring>
uint32_t millis() { return 1000; }
char queued[1536]{}; int pushes=0;
void xQueueOverwrite(int, const void *data) { memcpy(queued,data,sizeof(queued)); ++pushes; }
struct BackendAgent {
    struct AutoBaseLocationReply { char json[1536]; };
    int autoBaseLocationQueue_=1;
    String statusBootId_="boot", serialNumber_="station";
    int32_t lastMqttAckSequence_=-1,lastWebsocketAckSequence_=-1;
    uint32_t lastMqttAckMs_=0,lastWebsocketAckMs_=0;
    bool active=true;
    bool workflowActive() const { return active; }
    void handleControlAck(const String &,const String &,bool);
};
'''
checks=r'''
int main() {
    BackendAgent agent;
    String msg=R"({"type":"control_plane_ack","status_boot_id":"boot","serial":"station","status_sequence":42,"auto_base_location":{"request_id":"boot:1","location":{"input_coord":{"lat":21.08499,"lon":105.786656,"alt":-8.0624},"l0_deg":105,"k0":0.9999}}})";
    agent.handleControlAck("mqtt",msg,false);
    assert(pushes==1 && agent.lastMqttAckSequence_==42);
    DynamicJsonDocument response(2048), location(2048);
    assert(!deserializeJson(response,static_cast<const char *>(queued)));
    assert(acceptAutoBaseLocationReply(response.as<JsonObjectConst>(),"boot:1",21.08499,105.786656,-8.0624,location));
    assert(location["l0_deg"]==105);
    assert(!acceptAutoBaseLocationReply(response.as<JsonObjectConst>(),"old",21.08499,105.786656,-8.0624,location));
    assert(!acceptAutoBaseLocationReply(response.as<JsonObjectConst>(),"boot:1",22,105.786656,-8.0624,location));
    const String other=R"({"type":"control_plane_ack","status_boot_id":"boot","serial":"other","status_sequence":99})";
    const String missing=R"({"type":"control_plane_ack","status_boot_id":"boot","status_sequence":99})";
    agent.handleControlAck("mqtt",other,false);
    agent.handleControlAck("websocket",other,false);
    agent.handleControlAck("mqtt",missing,false);
    assert(agent.lastMqttAckSequence_==42 && agent.lastWebsocketAckSequence_==-1);
    agent.handleControlAck("mqtt",msg,true); assert(pushes==1);
    agent.statusBootId_="other"; agent.handleControlAck("mqtt",msg,false); assert(pushes==1);
    agent.statusBootId_="boot"; agent.serialNumber_="other"; agent.handleControlAck("mqtt",msg,false); assert(pushes==1);
    agent.serialNumber_="station"; agent.active=false; agent.handleControlAck("mqtt",msg,false); assert(pushes==1);
}
'''
with tempfile.TemporaryDirectory(prefix='autobase-location-') as directory:
    path=Path(directory); (path/'check.cpp').write_text(harness+helpers+handler+checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(root/'test/host'),'-I'+str(root/'.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: correlated location ACK, wrong session/device/coordinates and retained ACK rejection')
