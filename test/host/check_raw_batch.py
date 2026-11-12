"""Reject malformed command batches before UART writes and detect partial writes."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Commands.cpp').read_text()
method = source[source.index('static bool validateRawCommands('):source.index('void BackendAgent::handleCommand(')]
codec = (root / 'src/functions/backend/Backend_Agent_Codec.cpp').read_text()
codec = codec[codec.index('    int base64Value('):codec.index('    String licenseCodeFromBase(')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <array>
#include <cassert>
#include <cstring>
constexpr int GNSS_UNICORE_PORT = 0, MUTEX_TIMEOUT_MS = 100, pdTRUE = 1;
int rtcmBufferMutex = 1, releases = 0, writes = 0;
bool shortWrite = false, busy = false, unicoreOk = true;
int pdMS_TO_TICKS(int n) { return n; }
int xSemaphoreTake(int, int) { return !busy; }
void xSemaphoreGive(int) { ++releases; }
void delay(unsigned long) {}
struct Port { size_t write(const uint8_t *, size_t n) { ++writes; return shortWrite ? n - 1 : n; } void flush() {} } Serial1;
size_t routeUnicoreOutput(uint8_t *, size_t n, int) { return n; }
namespace GnssCmdBuilder { void routeUbloxOutput(uint8_t *, size_t) {} }
struct BackendAgent {
    String sensorType_ = "Ublox";
    bool writeUnicoreCommand(const uint8_t *, size_t, String &error) { ++writes; if (!unicoreOk) error = "no ACK"; return unicoreOk; }
    bool executeRawCommands(JsonArray, String &, const String &);
};
'''
checks = r'''
int main() {
    BackendAgent agent; String error;
    DynamicJsonDocument doc(8192); JsonArray commands = doc.to<JsonArray>();
    commands.add("AQ=="); commands.add("bad!");
    assert(!validateRawCommands(commands, error));
    assert(writes == 0 && error == "raw command is not valid base64");
    commands[1] = "Ag=="; shortWrite = true;
    assert(!agent.executeRawCommands(commands, error, "Ublox"));
    assert(writes == 1 && releases == 1 && error == "GNSS serial write incomplete");
    shortWrite = false; busy = true;
    assert(!agent.executeRawCommands(commands, error, "Ublox"));
    assert(writes == 1 && releases == 1 && error == "GNSS serial is busy");
    busy = false; assert(agent.executeRawCommands(commands, error, "Ublox"));
    assert(writes == 3 && releases == 3);
    unicoreOk = false;
    assert(!agent.executeRawCommands(commands, error, "Unicorecomm"));
    assert(writes == 4 && error == "no ACK");
}
'''
with tempfile.TemporaryDirectory(prefix='esp-raw-batch-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + codec + method + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined', '-I' + str(root / 'test/host'), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'), str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: invalid batch is not sent; partial UART writes and missing ACK fail')
