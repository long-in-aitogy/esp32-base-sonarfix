"""Exercise Unicore UART ACK handling, Survey-In state and lock cleanup."""
from pathlib import Path
import subprocess
import tempfile
from host_coverage import compile_cpp, mapped, run_cpp

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Workflows.cpp').read_text()
handler = source[source.index('bool BackendAgent::waitForUnicoreReply('):source.index('bool BackendAgent::writeGnssCommands(')]
harness = r'''
#include <Arduino.h>
#include "functions/gnss/Unicore_Reply.h"
#include <cassert>
#include <cstring>
#include <deque>
constexpr int MUTEX_TIMEOUT_MS = 1500, pdTRUE = 1;
int rtcmBufferMutex = 1, gnssSerialMutex = 2, denied = 0, held = 0;
int pdMS_TO_TICKS(int ms) { return ms; }
int xSemaphoreTake(int lock, int) { if (lock == denied) return 0; ++held; return 1; }
void xSemaphoreGive(int) { --held; }
struct Port {
    std::deque<uint8_t> input;
    String response;
    bool shortWrite = false;
    int available() { return input.size(); }
    int read() { int b = input.front(); input.pop_front(); return b; }
    size_t write(const uint8_t *, size_t length) {
        if (shortWrite) return 0;
        input.insert(input.end(), response.begin(), response.end());
        return length;
    }
    void flush() {}
} Serial1;
uint32_t now = 1000;
uint32_t millis() { return now; }
void delay(unsigned ms) { now += ms; }
void vTaskDelay(unsigned ms) { now += ms; }
struct BackendAgent {
    bool surveyInMonitoring_ = false, surveyInResultPending_ = false;
    uint32_t surveyInStartedMs_ = 0, surveyInTargetSeconds_ = 0;
    void handleUnicoreAck(const UnicoreReply &, const uint8_t *, size_t);
    bool waitForUnicoreReply(UnicoreReply &, bool);
    bool writeUnicoreCommand(const uint8_t *, size_t, String &);
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
    String error;
    auto send = [&](const char *command) {
        return agent.writeUnicoreCommand(reinterpret_cast<const uint8_t *>(command), strlen(command), error);
    };
    Serial1.response = "$command,mode,response: OK\r\n";
    assert(send(survey) && agent.surveyInTargetSeconds_ == 300 && held == 0);
    Serial1.response = "$command,mode,response: ERROR\r\n";
    assert(!send(rover) && error.indexOf("Unicore rejected command") >= 0 && held == 0);
    Serial1.response = "$command,other,response: OK\r\n";
    assert(!send(rover) && error.indexOf("response timeout") >= 0 && held == 0);
    Serial1.shortWrite = true;
    assert(!send(rover) && error.indexOf("UART write failed") >= 0 && held == 0);
    Serial1.shortWrite = false; denied = gnssSerialMutex;
    assert(!send(rover) && error == "GNSS reader is busy" && held == 0);
    denied = rtcmBufferMutex;
    assert(!send(rover) && error == "GNSS command port is busy" && held == 0);
    assert(!agent.writeUnicoreCommand(nullptr, 0, error) && held == 0);
}
'''
with tempfile.TemporaryDirectory(prefix='unicore-survey-ack-') as directory:
    path = Path(directory)
    shim = (root / 'test/host/Arduino.h').read_text().replace('    bool isEmpty()', '    int indexOf(const char *s) const { auto p = find(s); return p == npos ? -1 : int(p); }\n    bool isEmpty()').replace('    void toUpperCase()', '    void toLowerCase() { std::transform(begin(), end(), begin(), [](unsigned char c) { return std::tolower(c); }); }\n    void toUpperCase()')
    (path / 'Arduino.h').write_text(shim)
    (path / 'check.cpp').write_text(harness + mapped(root / 'src/functions/backend/Backend_Agent_Workflows.cpp', handler) + checks)
    compile_cpp(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(path),'-I'+str(root/'include'),
                    str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    run_cpp([str(path/'check')],check=True)
print('PASS: Unicore ACK, Survey-In state, UART failures and mutex cleanup')
