"""Stopping pending AutoNearest must prevent the scheduler from starting it."""
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[2]
source=(root/'src/functions/backend/Backend_Agent_Commands.cpp').read_text()
a=source.index('bool BackendAgent::executeStopWorkflowCommand('); b=source.index('\nvoid BackendAgent::finishCommand(',a)
method=source[a:b]
harness=r'''
#include <Arduino.h>
#include <cassert>
struct BackendAgent {
    String baseStartupState_="awaiting_auto_base", phase, state;
    bool active=false, cancelled=false, dirty=false;
    bool workflowActive() { return active; }
    void requestWorkflowStop() { cancelled=true; }
    void setWorkflowProgress(const char *value,int,int) { phase=value; }
    void setAgentState(const String &value) { state=value; }
    String normalAgentState() { return "ready"; }
    void markStatusDirty() { dirty=true; }
    bool executeStopWorkflowCommand(String &);
};
'''
checks=r'''
int main() {
    String detail; BackendAgent pending;
    assert(pending.executeStopWorkflowCommand(detail));
    assert(pending.baseStartupState_=="awaiting_configuration" && pending.phase=="stopped" && pending.dirty);
    BackendAgent active; active.active=true;
    assert(active.executeStopWorkflowCommand(detail));
    assert(active.cancelled && active.phase=="stopping");
}
'''
with tempfile.TemporaryDirectory(prefix='autocors-stop-') as directory:
    path=Path(directory); (path/'check.cpp').write_text(harness+method+checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(root/'test/host'),str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: pending and active AutoNearest stop handling')
