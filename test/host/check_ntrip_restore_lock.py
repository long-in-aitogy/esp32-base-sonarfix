"""Exercise NTRIP restore with a non-recursive transport mutex."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
source = (root/'src/functions/backend/Backend_Agent_Workflows.cpp').read_text()
method = source[source.index('bool BackendAgent::restartConfiguredNtrip('):source.index('\nint BackendAgent::loopNtripRoverLocked(')]
harness = r'''
#include <cassert>
constexpr int pdTRUE=1, MUTEX_TIMEOUT_MS=1500;
int tcpStreamMutex=1; bool held=false; int takes=0, gives=0, stops=0, setups=0, connects=0;
int pdMS_TO_TICKS(int value) { return value; }
int xSemaphoreTake(int, int) { ++takes; if (held) return 0; held=true; return pdTRUE; }
void xSemaphoreGive(int) { assert(held); held=false; ++gives; }
void stopNtripRover() { assert(held); ++stops; }
void setupNTRIP() { assert(held); ++setups; }
void connectNTRIP() { assert(held); ++connects; }
struct BackendAgent { bool restartConfiguredNtrip(bool transportLocked=false); };
'''
checks = r'''
int main() {
    BackendAgent agent; held=true;
    assert(agent.restartConfiguredNtrip(true));
    assert(held && takes==0 && gives==0 && stops==1 && setups==1 && connects==1);
    assert(!agent.restartConfiguredNtrip());
    assert(held && takes==1 && gives==0 && stops==1);
    held=false; assert(agent.restartConfiguredNtrip());
    assert(!held && takes==2 && gives==1 && stops==2 && setups==2 && connects==2);
}
'''
with tempfile.TemporaryDirectory(prefix='ntrip-restore-lock-') as directory:
    path=Path(directory); (path/'check.cpp').write_text(harness+method+checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: NTRIP restore handles already-held and contended mutexes')
