"""Run the complete backend event loop, queues and control-plane state machine."""
from pathlib import Path
import re
import tempfile
from host_coverage import compile_cpp, run_cpp, mapped

root = Path(__file__).resolve().parents[2]
path_source = root / 'src/functions/backend/Backend_Agent.cpp'
source = re.sub(r'^#include.*$', '', path_source.read_text(), flags=re.M)
header = re.sub(r'^#include.*$', '', (root/'include/functions/backend/Backend_Agent.h').read_text(), flags=re.M).replace('private:', 'public:')
shim = (root/'test/host/Arduino.h').read_text()
shim = shim.replace('    void trim() {', '''    int indexOf(const char *text) const { auto pos=find(text);return pos==npos?-1:int(pos); }
    void toLowerCase() { std::transform(begin(),end(),begin(),[](unsigned char c){return std::tolower(c);}); }
    bool equalsIgnoreCase(String other) const { String own=*this;own.toLowerCase();other.toLowerCase();return own==other; }
    void trim() {''')
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include "functions/backend/Station_Lock.h"
#include "functions/gnss/gnss_cmd_builder.h"
#include "functions/gnss/Ubx_Navigation.h"
#include "functions/gnss/Unicore_Identification.h"
#include <cassert>
#include <ctime>
#include <deque>
#include <memory>
#include <vector>
#define NATIVE_BUILD 1
#define BACKEND_WEBSOCKET_ENABLED 1
#define BACKEND_PUBLISH_RAW_RTCM 1
constexpr unsigned CONFIG_DOCUMENT_SIZE=4096,BACKEND_STATUS_INTERVAL_MS=1000,BACKEND_CONTROL_STALE_MS=30000,BACKEND_CONTROL_RECOVERY_MS=10000,MUTEX_TIMEOUT_MS=1500,pdTRUE=1;
constexpr const char *BACKEND_HOST="backend.example";constexpr unsigned BACKEND_WEBSOCKET_PORT=80;
using QueueHandle_t=void*;using TaskHandle_t=void*;using SemaphoreHandle_t=void*;
uint32_t now=1000;uint32_t millis(){return now;}void delay(unsigned ms){now+=ms;}
unsigned pdMS_TO_TICKS(unsigned n){return n;}
unsigned locks=0,unlocks=0,saves=0,polls=0,initialized=0,restarts=0,commands=0;
void *tcpStreamMutex=reinterpret_cast<void*>(1),*rtcmBufferMutex=reinterpret_cast<void*>(2),*gnssSerialMutex=reinterpret_cast<void*>(3);
bool denyLock=false;
bool xSemaphoreTake(void*,unsigned){if(denyLock)return false;++locks;return true;}
void xSemaphoreGive(void*){++unlocks;}
struct Queue{size_t capacity,size;std::deque<std::vector<uint8_t>> rows;};
std::vector<std::unique_ptr<Queue>> queues;
void *xQueueCreate(size_t capacity,size_t size){queues.push_back(std::make_unique<Queue>(Queue{capacity,size,{}}));return queues.back().get();}
unsigned xQueueSend(void *handle,const void *packet,unsigned){auto &q=*static_cast<Queue*>(handle);if(q.rows.size()==q.capacity)return 0;auto p=static_cast<const uint8_t*>(packet);q.rows.emplace_back(p,p+q.size);return pdTRUE;}
unsigned xQueueReceive(void *handle,void *packet,unsigned){auto &q=*static_cast<Queue*>(handle);if(q.rows.empty())return 0;std::memcpy(packet,q.rows.front().data(),q.size);q.rows.pop_front();return pdTRUE;}
unsigned xQueueSendToFront(void *handle,const void *packet,unsigned){auto &q=*static_cast<Queue*>(handle);auto p=static_cast<const uint8_t*>(packet);q.rows.emplace_front(p,p+q.size);return pdTRUE;}
void xQueueOverwrite(void *handle,const void *packet){auto &q=*static_cast<Queue*>(handle);q.rows.clear();xQueueSend(handle,packet,0);}
struct Stream{
    std::deque<uint8_t> input;std::string printedReply;std::vector<uint8_t> writtenReply;
    int available(){return input.size();}int read(){int v=input.front();input.pop_front();return v;}
    void print(const char*){input.insert(input.end(),printedReply.begin(),printedReply.end());}
    size_t write(const uint8_t*,size_t n){input.insert(input.end(),writtenReply.begin(),writtenReply.end());return n;}
} Serial1;
struct PubSubClient{
    bool up=true,accept=true;std::vector<String> messages;
    bool connected(){return up;}
    bool publish(const char*,const char *payload,bool){messages.emplace_back(payload);return accept;}
    bool publish(const char*,const uint8_t *payload,size_t n){messages.emplace_back(reinterpret_cast<const char*>(payload),n);return accept;}
}mqtt;
struct WiFiClient{};int modem=0;struct TinyGsmClient{TinyGsmClient(int&,int){}};
bool wifi=true;bool isWifiConnection(){return wifi;}
struct Preferences{bool begin(const char*,bool){return true;}void end(){}unsigned getUShort(const char*,unsigned fallback){return fallback;}}prefs;
struct{unsigned getSketchSize(){return 4096;}}ESP;
using std::min;
void setupNTRIP(){++restarts;}void connectNTRIP(){}
namespace BackendAgentInternal{
String readPreference(const char*,const String &fallback){return fallback;}
String urlEncode(const String&);
bool jsonBool(JsonObjectConst,const String&,bool fallback=false);
}
'''
transport = r'''
class BackendAgentWebsocket{
public:
    bool up=true,accept=true;unsigned loops=0;String endpoint;std::vector<String> messages;
    explicit BackendAgentWebsocket(BackendAgent*){}
    template<class Client>void begin(const String&,unsigned,const String&path,Client&){endpoint=path;}
    bool connected(){return up;}void disconnect(bool){up=false;}void loop(){++loops;}
    bool sendText(const String &value){messages.push_back(value);return accept;}
};
void BackendAgent::loadPreferences(){serialNumber_="esp_test";}
void BackendAgent::ensureDefaultServiceConfig(){}
bool BackendAgent::saveStatePreferences(){++saves;return true;}
String BackendAgent::buildStatusPayload(){return "{\"online\":true}";}
String BackendAgent::buildLwtPayload()const{return "{\"online\":false}";}
bool BackendAgent::initializeBaseAtBoot(GnssCmdBuilder::GnssSensorType){++initialized;baseStartupAttempted_=true;return true;}
void BackendAgent::pollGnssStatus(){++polls;}
void BackendAgent::handleCommand(const String&,const String&){++commands;}
'''
checks = r'''
int main(){
    using namespace BackendAgentInternal;
    DynamicJsonDocument values(2048);auto object=values.to<JsonObject>();
    assert(jsonBool(object,"missing",true));
    for(const char *value:{"true","1","on"}){object["x"]=value;assert(jsonBool(object,"x",false));}
    for(const char *value:{"false","0","off"}){object["x"]=value;assert(!jsonBool(object,"x",true));}
    object["x"]=2;assert(jsonBool(object,"x",false));object["x"]=false;assert(!jsonBool(object,"x",true));
    assert(jsonString(object,"missing","fallback")=="fallback");object["x"]="text";assert(jsonString(object,"x","")=="text");
    copyJsonObject(values,"bad","not json");assert(values["bad"].is<JsonObject>());
    copyJsonObject(values,"good","{\"x\":1}");assert(values["good"]["x"]==1);assert(!epochString().isEmpty());
    BackendAgent agent;agent.licenseToken_="token +";agent.begin();
    assert(agent.firmwareSize_==4096&&agent.websocket_&&agent.nmeaQueue_&&agent.rtcmQueue_&&agent.autoBaseLocationQueue_);
    assert(agent.websocket_->endpoint=="/ws/pi/esp_test?token=token%20%2B");agent.begin();
    assert(agent.statusTopic()=="pi/devices/esp_test/status"&&agent.lwtPayload()=="{\"online\":false}");
    agent.setDetectedChipIfUnknown("invalid");assert(agent.sensorType_=="UNKNOWN");
    agent.setDetectedChipIfUnknown("Ublox");assert(agent.sensorType_=="Ublox");
    Stream wire;wire.printedReply="#VERSIONA,UNICORE\r\n";assert(agent.detectGnssChip(wire));
    assert(agent.detectGnssChip(wire,true)&&agent.sensorType_=="Unicorecomm");
    wire.printedReply.clear();wire.writtenReply={0,0xb5,0xb5,0x62,0x0a,4};assert(agent.detectGnssChip(wire,true)&&agent.sensorType_=="Ublox");
    wire.writtenReply.clear();assert(!agent.detectGnssChip(wire,true));
    agent.setAgentState("ONLINE");assert(agent.agentState_=="online"&&agent.statusDirty_);
    agent.stationLock_.all=true;assert(agent.normalAgentState()=="locked");agent.stationLock_.all=false;
    assert(agent.normalAgentState()=="awaiting_license");agent.licenseValid_=true;assert(agent.normalAgentState()=="unprovisioned");
    agent.provisioned_=true;assert(agent.normalAgentState()=="online");
    agent.websocketConnected_=true;agent.onMqttConnected();assert(agent.statusSequence_==1&&agent.statusPublishConfirmed_);
    auto sequence=agent.statusSequence_;agent.publishStatus();assert(agent.statusSequence_==sequence);
    now+=1001;mqtt.accept=false;agent.publishStatus();assert(!agent.statusPublishConfirmed_);mqtt.accept=true;
    const uint8_t packet[]={0xd3,0,1};agent.enqueueRtcm(nullptr,3);agent.enqueueRtcm(packet,0);agent.enqueueNmea(nullptr,3);
    for(unsigned i=0;i<20;++i)agent.enqueueNmea(reinterpret_cast<const uint8_t*>("$GGA\r\n"),6);
    assert(static_cast<Queue*>(agent.nmeaQueue_)->rows.size()==16);
    agent.enqueueRtcm(packet,3);mqtt.up=false;agent.websocket_->up=false;agent.drainDataQueues();
    assert(static_cast<Queue*>(agent.nmeaQueue_)->rows.size()==16&&static_cast<Queue*>(agent.rtcmQueue_)->rows.size()==1);
    agent.websocket_->up=true;agent.drainDataQueues();assert(static_cast<Queue*>(agent.nmeaQueue_)->rows.empty());
    mqtt.up=true;agent.drainDataQueues();assert(static_cast<Queue*>(agent.rtcmQueue_)->rows.empty());
    for(unsigned i=0;i<6;++i)agent.enqueueRtcm(packet,3);assert(static_cast<Queue*>(agent.rtcmQueue_)->rows.size()==4);
    mqtt.accept=false;agent.drainDataQueues();assert(static_cast<Queue*>(agent.rtcmQueue_)->rows.size()==4);mqtt.accept=true;agent.drainDataQueues();
    String longNmea(1000,'x');agent.enqueueNmea(reinterpret_cast<const uint8_t*>(longNmea.data()),longNmea.size());agent.drainDataQueues();
    agent.statusBootId_="boot";agent.workflowTask_=reinterpret_cast<void*>(1);now=50000;
    String ack=R"({"type":"control_plane_ack","serial":"esp_test","status_boot_id":"boot","status_sequence":5,"auto_base_location":{"request_id":"r"}})";
    agent.handleControlAck("mqtt",ack,true);assert(agent.lastMqttAckSequence_==-1);
    agent.handleControlAck("mqtt",ack,false);assert(agent.lastMqttAckSequence_==5&&agent.lastMqttAckMs_==now);
    now+=1;agent.handleControlAck("mqtt",ack,false);assert(agent.lastMqttAckMs_==now-1);
    agent.handleControlAck("websocket",ack,false);assert(agent.lastWebsocketAckSequence_==5);
    agent.handleControlAck("mqtt","bad json",false);
    agent.onMqttMessage(nullptr,packet,3);agent.onMqttMessage("unknown",nullptr,3);
    agent.onMqttMessage(agent.controlAckTopic().c_str(),reinterpret_cast<const uint8_t*>(ack.c_str()),ack.size());
    for(const char *topic:{"pi/devices/esp_test/command","pi/devices/esp_test/commands","pi/device/esp_test/command"})agent.onMqttMessage(topic,packet,3);
    assert(commands==3);agent.handleWebsocketText("bad json");agent.handleWebsocketText(ack);agent.handleWebsocketText("{}");assert(commands==4);
    agent.statusSequence_=10;agent.controlPlaneArmedMs_=1000;agent.lastMqttAckMs_=agent.lastWebsocketAckMs_=0;
    now=60000;agent.evaluateControlPlaneFailover();assert(agent.controlPlaneFailOpen_);
    agent.lastMqttAckSequence_=11;agent.lastMqttAckMs_=now;now+=2001;agent.evaluateControlPlaneFailover();assert(agent.controlPlaneFailOpen_);
    now+=10001;agent.lastMqttAckMs_=now;agent.evaluateControlPlaneFailover();assert(!agent.controlPlaneFailOpen_);
    agent.licenseValid_=false;now+=2001;agent.evaluateControlPlaneFailover();assert(!agent.controlPlaneFailOpen_);
    agent.publishTextFallback("test");agent.onNetworkChanged();wifi=false;agent.refreshWebsocket();
    agent.sensorType_="UNKNOWN";now+=9000;agent.workflowTask_=nullptr;agent.loop();assert(polls==1&&locks==unlocks);
    agent.sensorType_="Ublox";agent.loop();assert(initialized==1);
    assert(!backendDeviceLocked()&&!backendControlPlaneFailOpen()&&!backendDeviceProvisioned()&&!backendLicenseValid()&&!backendBaseStartupConfigured());
    delete agent.websocket_;agent.websocket_=nullptr;agent.refreshWebsocket();agent.publishTextFallback("ignored");
}
'''
with tempfile.TemporaryDirectory(prefix='backend-lifecycle-') as directory:
    path=Path(directory);(path/'Arduino.h').write_text(shim)
    (path/'check.cpp').write_text(harness+header+transport+mapped(path_source,source,stripped_includes=True)+checks)
    compile_cpp(['c++','-std=c++17','-DNATIVE_BUILD','-fsanitize=address,undefined','-I'+str(path),'-I'+str(root/'test/host'),'-I'+str(root/'include'),
                 '-I'+str(root/'.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),str(path/'check.cpp'),
                 str(root/'src/functions/backend/Backend_Agent_Codec.cpp'),str(root/'src/functions/gnss/gnss_cmd_builder.cpp'),
                 str(root/'src/functions/gnss/ublox_commands.cpp'),str(root/'src/functions/gnss/unicore_commands.cpp'),'-o',str(path/'check')],check=True)
    run_cpp([str(path/'check')],check=True)
print('PASS: complete backend lifecycle, actual queues/backpressure, status delivery, chip probes, ACK correlation and fail-open recovery')
