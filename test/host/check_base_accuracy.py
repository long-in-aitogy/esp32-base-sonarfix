"""Check persisted and incoming Base settings normalize to the configured policy."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Storage.cpp').read_text()
function = source[source.index('    bool enforceBaseAccuracy('):source.index('    Preferences &backendPreferences()')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <cassert>
#include "functions/gnss/gnss_cmd_builder.h"
'''
checks = r'''
int main() {
    DynamicJsonDocument doc(2048);
    auto base = doc.to<JsonObject>();
    base["base_setup_method"] = "SURVEY_IN";
    base["survey_in_accuracy"] = 3;
    base["accuracy"] = 0.01;
    base["mean_accuracy_m"] = 0.25; // Receiver measurement is not a setting.
    assert(enforceBaseAccuracy(base));
    assert(base["survey_in_accuracy"] == 5 && base["accuracy"] == 5);
    assert(base["mean_accuracy_m"] == 0.25 && !enforceBaseAccuracy(base));
    doc.clear(); base = doc.to<JsonObject>();
    base["base_setup_method"] = "FIXED_LLA";
    base["accuracy"] = 0.01;
    base["survey_in_accuracy"] = 3;
    base["coords"]["accuracy"] = 0.01;
    assert(enforceBaseAccuracy(base));
    assert(base["accuracy"] == 5 && base["survey_in_accuracy"] == 5 && base["coords"]["accuracy"] == 5);
    assert(!enforceBaseAccuracy(base));
    doc.clear(); base = doc.to<JsonObject>();
    assert(!enforceBaseAccuracy(base) && base.size() == 0);
    base["base_setup_method"] = "AUTO_CORS";
    assert(enforceBaseAccuracy(base) && base["accuracy"] == 5);
}
'''
with tempfile.TemporaryDirectory(prefix='base-accuracy-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + function + checks)
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'), '-I' + str(root / 'include'),
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: Survey-In/Fixed LLA settings normalize to 5 m without changing measured accuracy')
