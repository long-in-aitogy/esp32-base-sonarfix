"""Verify advertised GNSS and Auto Base capabilities."""
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[2]
source=(root/'src/functions/backend/Backend_Agent_Status.cpp').read_text()
a=source.index('void BackendAgent::appendSystemInfo('); b=source.index('\nvoid BackendAgent::appendStartupInfo(',a)
method=source[a:b]
harness=r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
constexpr size_t VERIFICATION_DOCUMENT_SIZE=12288;
void appendStorageStatus(JsonObject system) { system.createNestedObject("nvs"); }
struct BackendAgent {
    String sensorType_="Ublox", gnssVerification_, nvsInventory_;
    uint32_t gnssVerificationMs_=0;
    struct { bool all=false; } stationLock_;
    void appendStartupInfo(JsonObject) const {}
    JsonObject appendSurveyInfo(JsonObject object,uint32_t) const { return object.createNestedObject("survey"); }
    void appendReceiverReadback(JsonObject,JsonObject) const {}
    void appendResourceInfo(JsonObject,const String &) const {}
    bool isServerLocked(uint8_t) const { return false; }
    void appendSystemInfo(JsonDocument &,uint32_t,const String &) const;
};
'''
checks=r'''
int main() {
    BackendAgent agent; DynamicJsonDocument doc(2048);
    agent.appendSystemInfo(doc,100,"now");
    assert(doc["system_info"]["auto_base_review_supported"]==true);
    assert(doc["system_info"]["auto_base_nearest_supported"]==true);
    assert(doc["system_info"]["auto_base_firmware_profile"]==true);
    assert(doc["system_info"]["gnss_verification_supported"]==true);
    assert(doc["system_info"]["gnss_verification_uart1"]==true);
    assert(doc["system_info"]["gnss_rf_supported"]==false);
    doc.clear(); agent.sensorType_="Unicorecomm"; agent.appendSystemInfo(doc,100,"now");
    assert(doc["system_info"]["gnss_verification_supported"]==true && doc["system_info"]["gnss_verification_uart1"]==true);
    doc.clear(); agent.sensorType_="UNKNOWN"; agent.appendSystemInfo(doc,100,"now");
    assert(doc["system_info"]["gnss_verification_supported"]==false && doc["system_info"]["gnss_verification_uart1"]==false);
}
'''
with tempfile.TemporaryDirectory(prefix='autobase-capability-') as directory:
    path=Path(directory); (path/'check.cpp').write_text(harness+method+checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(root/'test/host'),'-I'+str(root/'.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: GNSS verification port, unsupported RF and Auto Base capabilities')
