"""Exercise real status JSON capacity with three populated configuration objects."""
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[2]
status=(root/'src/functions/backend/Backend_Agent_Status.cpp').read_text()
start=status.index('    DynamicJsonDocument doc(STATUS_DOCUMENT_SIZE',status.index('String BackendAgent::buildStatusPayload('))
end=status.index(';',start)+1
allocation=status[start:end]
action_start=status.index('    copyJsonObject(doc, "last_command_result"')
action_end=status.index('    JsonObject control =',action_start)
action=status[action_start:action_end]
agent=(root/'src/functions/backend/Backend_Agent.cpp').read_text()
copy=agent[agent.index('    bool copyJsonObject('):agent.index('\n} // namespace BackendAgentInternal')]
harness=r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
#include <cstring>
constexpr size_t STATUS_DOCUMENT_SIZE=8192,CONFIG_DOCUMENT_SIZE=6144,PROGRESS_DOCUMENT_SIZE=8192,VERIFICATION_DOCUMENT_SIZE=12288;
'''
checks=r'''
int main() {
    String baseConfig_, serviceConfig_, autoBaseProgress_, nvsInventory_, gnssVerification_, satelliteReadback_, versionReadback_, versionReadbackError_;
    unsigned receiverInfoMs_=0;
    DynamicJsonDocument input(PROGRESS_DOCUMENT_SIZE);
    auto fill=[&](const char *prefix, String &output, int count) {
        input.clear();
        for (int i=0;i<count;++i) input[String(prefix)+String(i)] = String(prefix)+String(i)+String(20,'x');
        assert(!input.overflowed());
        serializeJson(input,output);
    };
    fill("base",baseConfig_,70); fill("service",serviceConfig_,70); fill("progress",autoBaseProgress_,90);
    ALLOCATION
    copyJsonObject(doc,"base_config",baseConfig_);
    copyJsonObject(doc,"service_config",serviceConfig_);
    copyJsonObject(doc,"auto_base_progress",autoBaseProgress_);
    JsonObject telemetry=doc.createNestedObject("system_info");
    for (int i=0;i<30;++i) telemetry[String("status")+String(i)]=i;
    assert(!doc.overflowed());
    assert(doc["base_config"].size()==70 && doc["service_config"].size()==70 && doc["auto_base_progress"].size()==90 && telemetry.size()==30);
    DynamicJsonDocument invalid(512);
    assert(!copyJsonObject(invalid,"base_config","{bad"));
    assert(!copyJsonObject(invalid,"service_config","[]"));
    assert(!invalid.containsKey("base_config") && !invalid.containsKey("service_config"));
    assert(copyJsonObject(invalid,"base_config","{}") && invalid["base_config"].is<JsonObject>());
    {
        DynamicJsonDocument doc(2048);
        doc["system_info"]["nvs"]["inventory_supported"] = true;
        String lastCommandResult_ = R"({"command_id":"request-1","status":"success","detail":"saved"})";
        ACTION
        assert(doc["system_info"]["nvs"]["last_action"]["command_id"] == "request-1");
        assert(doc["system_info"]["nvs"]["last_action"]["status"] == "success");
        assert(doc["system_info"]["nvs"]["last_action"]["detail"] == "saved");
        assert(doc["last_command_result"]["command_id"] == "request-1" && !doc.overflowed());
    }
}
'''.replace('ALLOCATION',allocation).replace('ACTION',action)
with tempfile.TemporaryDirectory(prefix='status-capacity-') as directory:
    path=Path(directory); (path/'check.cpp').write_text(harness+copy+checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(root/'test/host'),'-I'+str(root/'.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: status preserves populated Base, service, progress and telemetry objects')
