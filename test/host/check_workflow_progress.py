"""Exercise actual workflow JSON merging under ASan, including Vietnamese values."""
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[2]
source=(root/'src/functions/backend/Backend_Agent_Workflows.cpp').read_text()
method=source[source.index('void BackendAgent::setWorkflowProgress('):source.index('bool BackendAgent::startWorkflow(')]
harness=r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
constexpr size_t AUTO_BASE_RESULT_SIZE=6144, PROGRESS_DOCUMENT_SIZE=8192;
struct Epoch { long toInt() { return 123; } };
Epoch epochString() { return {}; }
struct BackendAgent {
    String autoBaseProgress_;
    void markStatusDirty() {}
    void setWorkflowProgress(const String &,uint8_t,uint8_t,const String &);
};
'''
checks=r'''
int main() {
    BackendAgent agent;
    for(int i=0;i<100;++i) {
        agent.setWorkflowProgress("ready_for_review",4,4,R"({"sample_count":56,"fixed_samples_only":true,"province_name":"Hà Nội","conversion_report":{"projection_source":"rtcm1025","label":"Múi 6°"}})");
        DynamicJsonDocument decoded(4096);
        assert(deserializeJson(decoded,agent.autoBaseProgress_) == DeserializationError::Ok);
        assert(decoded["sample_count"] == 56 && decoded["province_name"] == "Hà Nội");
        assert(decoded["conversion_report"]["label"] == "Múi 6°");
    }
}
'''
with tempfile.TemporaryDirectory(prefix='esp-workflow-json-') as directory:
    path=Path(directory);(path/'check.cpp').write_text(harness+method+checks)
    subprocess.run(['c++','-std=c++17','-fsanitize=address,undefined','-I'+str(root/'test/host'),'-I'+str(root/'.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: workflow progress owns copied keys; Unicode and nested report survive repeated merges')
