"""Check legacy Survey-In results survive backend preference migration."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Storage.cpp').read_text()
method = source[source.index('    bool migrateBackendPreferences()'):source.index('    String readPreference(')]
harness = r'''
#include <Arduino.h>
#include <cassert>
#include <map>
#include <string>
struct Preferences {
    std::map<std::string, String> values;
    bool failSurvey = false;
    bool begin(const char *, bool, const char * = nullptr) { return true; }
    void end() {}
    bool isKey(const char *key) { return values.count(key); }
    String getString(const char *key) { return values[key]; }
    bool getBool(const char *key) { return values[key] == "1"; }
    unsigned char getUChar(const char *key) { return (unsigned char)std::stoi(values[key].c_str()); }
    size_t putString(const char *key, const String &value) {
        if (failSurvey && std::string(key) == "SURVEY_RESULT") return 0;
        values[key] = value; return value.length();
    }
    size_t putBool(const char *key, bool value) { values[key] = value ? "1" : "0"; return 1; }
    size_t putUChar(const char *key, unsigned char value) { values[key] = String(value); return 1; }
};
Preferences prefs, backendPrefs;
constexpr char BACKEND_PREFS_NAMESPACE[] = "backend";
constexpr char BACKEND_PREFS_PARTITION[] = "agent_state";
'''
checks = r'''
int main() {
    prefs.values["SURVEY_RESULT"] = R"({"lat":21.1})";
    prefs.values["BASE_JSON"] = R"({"accuracy":5})";
    backendPrefs.failSurvey = true;
    assert(!migrateBackendPreferences());
    assert(!backendPrefs.isKey("MIGRATED"));
    assert(prefs.isKey("SURVEY_RESULT"));
    backendPrefs.failSurvey = false;
    assert(migrateBackendPreferences());
    assert(backendPrefs.getString("SURVEY_RESULT") == prefs.getString("SURVEY_RESULT"));
    assert(backendPrefs.getString("BASE_JSON") == prefs.getString("BASE_JSON"));
    assert(backendPrefs.isKey("MIGRATED"));
    prefs.values["SURVEY_RESULT"] = "old";
    assert(migrateBackendPreferences());
    assert(backendPrefs.getString("SURVEY_RESULT") != "old");
}
'''
with tempfile.TemporaryDirectory(prefix='esp-backend-migration-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + method + checks)
    subprocess.run(['c++', '-std=c++17', '-I' + str(root / 'test/host'), str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: Survey-In result migrates; failed writes retry and existing migration is preserved')
