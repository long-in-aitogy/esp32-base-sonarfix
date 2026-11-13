"""Exercise workflow progress restoration after a reboot."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "src/functions/backend/Backend_Agent_Storage.cpp").read_text()
method = source[source.index("    String restoreWorkflowProgress("):source.index("    bool enforceBaseAccuracy(")]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
constexpr size_t PROGRESS_DOCUMENT_SIZE = 8192;
'''
checks = r'''
int main() {
    String large = String(R"({"phase":"completed","details":")") + String(std::string(6500, 'x')) + R"("})";
    assert(restoreWorkflowProgress(large) == large);
    for (const char *phase : {"ready_for_review", "completed", "failed", "stopped", "reference_check_completed", "reference_check_failed", "reprojected"}) {
        String saved = String("{\"phase\":\"") + phase + "\",\"result\":42}";
        assert(restoreWorkflowProgress(saved) == saved);
    }
    for (const char *saved : {"{}", "{", "[]", "{\"phase\":\"wait_fix\"}", "{\"phase\":\"awaiting_source\"}", "{\"phase\":\"reference_check_averaging\"}"})
        assert(restoreWorkflowProgress(saved) == "{}");
}
'''
with tempfile.TemporaryDirectory(prefix="esp-workflow-restore-") as directory:
    path = Path(directory)
    (path / "check.cpp").write_text(harness + method + checks)
    subprocess.run(["c++", "-std=c++17", "-I" + str(root / "test/host"), "-I" + str(root / ".pio/libdeps/tdm240x_dev_general/ArduinoJson/src"), str(path / "check.cpp"), "-o", str(path / "check")], check=True)
    subprocess.run([str(path / "check")], check=True)
print("PASS: only finished workflow reports survive reboot")
