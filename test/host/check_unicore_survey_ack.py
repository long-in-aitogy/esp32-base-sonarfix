"""Exercise Survey-In ACK state changes and reset delay using the firmware handler."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Workflows.cpp').read_text()
handler = source[source.index('void BackendAgent::handleUnicoreAck('):source.index('bool BackendAgent::writeUnicoreCommand(')]
harness = r'''
#include <Arduino.h>
#include "functions/gnss/Unicore_Reply.h"
#include <cassert>
#include <cstring>
uint32_t now = 1000;
uint32_t millis() { return now; }
void delay(unsigned ms) { now += ms; }
struct BackendAgent {
    bool surveyInMonitoring_ = false, surveyInResultPending_ = false;
    uint32_t surveyInStartedMs_ = 0, surveyInTargetSeconds_ = 0;
    void handleUnicoreAck(const UnicoreReply &, const uint8_t *, size_t);
};
'''
checks = r'''
int main() {
    BackendAgent agent;
    const char *survey = "MODE BASE TIME 300 0\r\n";
    UnicoreReply surveyReply(reinterpret_cast<const uint8_t *>(survey), strlen(survey));
    agent.handleUnicoreAck(surveyReply, reinterpret_cast<const uint8_t *>(survey), strlen(survey));
    assert(agent.surveyInMonitoring_ && agent.surveyInResultPending_);
    assert(agent.surveyInStartedMs_ == 1000 && agent.surveyInTargetSeconds_ == 300);
    const char *rover = "mode rover\r\n";
    UnicoreReply roverReply(reinterpret_cast<const uint8_t *>(rover), strlen(rover));
    agent.handleUnicoreAck(roverReply, reinterpret_cast<const uint8_t *>(rover), strlen(rover));
    assert(!agent.surveyInMonitoring_ && agent.surveyInTargetSeconds_ == 0);
    const char *reset = "reset\r\n";
    UnicoreReply resetReply(reinterpret_cast<const uint8_t *>(reset), strlen(reset));
    agent.handleUnicoreAck(resetReply, reinterpret_cast<const uint8_t *>(reset), strlen(reset));
    assert(now == 3000);
}
'''
with tempfile.TemporaryDirectory(prefix='unicore-survey-ack-') as directory:
    path = Path(directory)
    shim = (root / 'test/host/Arduino.h').read_text().replace('    void toUpperCase()', '    void toLowerCase() { std::transform(begin(), end(), begin(), [](unsigned char c) { return std::tolower(c); }); }\n    void toUpperCase()')
    (path / 'Arduino.h').write_text(shim)
    (path / 'check.cpp').write_text(harness + handler + checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(path),'-I'+str(root/'include'),
                    str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: Unicore Survey-In ACK records duration; Rover/reset behavior remains intact')
