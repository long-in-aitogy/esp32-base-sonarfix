"""Check Rover GGA waiting after the receiver has confirmed its mode."""
from pathlib import Path
import tempfile
from host_coverage import compile_cpp, mapped, run_cpp

root = Path(__file__).resolve().parents[2]
source_path = root / 'src/functions/backend/Backend_Agent_Workflows.cpp'
source = source_path.read_text()
method = source[source.index('bool BackendAgent::waitForRoverGga('):source.index('bool BackendAgent::configureUbloxRover(')]
harness = r'''
#include <Arduino.h>
#include <array>
#include <cassert>
uint32_t now = 1000, ggaAt = 0, cancelAt = 0;
uint32_t millis() { return now; }
unsigned pdMS_TO_TICKS(unsigned ms) { return ms; }
struct Snapshot { uint32_t lastGgaMs = 0; std::array<char, 8> lastGga = {}; };
Snapshot getGnssTelemetrySnapshot() { Snapshot s; if (ggaAt && now >= ggaAt) s.lastGgaMs = ggaAt; return s; }
struct BackendAgent { bool workflowCancelRequested_ = false; bool waitForRoverGga(uint32_t); };
BackendAgent *active;
void vTaskDelay(unsigned ms) { now += ms; if (cancelAt && now >= cancelAt) active->workflowCancelRequested_ = true; }
'''
checks = r'''
int main() {
    BackendAgent agent; active = &agent;
    ggaAt = 1200; assert(agent.waitForRoverGga(now) && now == 1200);
    now = 2000; ggaAt = 0; assert(agent.waitForRoverGga(now) && now == 12000);
    now = 2000; ggaAt = 1900; assert(agent.waitForRoverGga(now) && now == 12000);
    now = 2000; cancelAt = 2300;
    assert(!agent.waitForRoverGga(now) && now == 2300);
}
'''
with tempfile.TemporaryDirectory(prefix='ublox-rover-gga-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + mapped(source_path, method) + checks)
    compile_cpp(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                 '-I' + str(root / 'test/host'), str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    run_cpp([str(path / 'check')], check=True)
print('PASS: confirmed Rover accepts delayed GGA and respects cancellation')
