"""Exercise legacy Wi-Fi setting validation before any persistent write."""
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[2]
source=(root/'src/functions/backend/cmd_handler.cpp').read_text()
method=source[source.index('cmd_action_t handleEspValueSet('):source.index('/** @brief Implements handleEspCommand.')]
handler=source[source.index('cmd_action_t handleEspCommand('):source.index('/** @brief Implements handleMqttCommand.')]
shim=(root/'test/host/Arduino.h').read_text().replace('#pragma once','')
shim=shim.replace('    bool isEmpty()', '    long toInt() const { return std::strtol(c_str(), nullptr, 10); }\n    bool isEmpty()').replace('struct HostSerial', 'inline String serialOutput;\nstruct HostSerial').replace('    void println(const char *) {}','    void println(const char *value) { serialOutput += value; }\n    void println(const String &value) { serialOutput += value; }')
harness=r'''
#include <array>
#include <cassert>
#include <cstdlib>
#include <vector>
#include "hardware/Wifi_Credentials.h"
enum class cmd_action_t { CMD_ACTION_NONE, CMD_ACTION_HANDLED, CMD_ACTION_ESP_RESTART };
String savedKey, savedValue; unsigned writes=0;
namespace cmd_helper {
struct PreferenceMapping { const char *command,*preferenceKey; };
bool hasExactArgumentCount(const std::vector<String> &v,size_t size,const char *) { return v.size()==size; }
const char *findPreferenceKey(const String &key,const PreferenceMapping *map,size_t size) {
    for (size_t i=0;i<size;++i) { if (key==map[i].command) return map[i].preferenceKey; } return nullptr;
}
cmd_action_t saveStringPreference(const char *key,const String &value) { ++writes; savedKey=key; savedValue=value; return cmd_action_t::CMD_ACTION_HANDLED; }
cmd_action_t saveUShortPreference(const char *,uint16_t) { ++writes; return cmd_action_t::CMD_ACTION_HANDLED; }
}
cmd_action_t handleEspConnectionSet(const std::vector<String> &) { return cmd_action_t::CMD_ACTION_ESP_RESTART; }
'''
checks=r'''
int main() {
    handleEspValueSet({"SET","WIFI","SSID",String(33,'x')}); assert(writes==0);
    handleEspValueSet({"SET","WIFI","SSID","bad\nname"}); assert(writes==0);
    handleEspValueSet({"SET","WIFI","PASS","short"}); assert(writes==0);
    handleEspValueSet({"SET","WIFI","PASS",String(64,'x')}); assert(writes==0);
    handleEspValueSet({"SET","WIFI","SSID","valid-network"}); assert(writes==1 && savedKey=="WIFI_SSID");
    handleEspValueSet({"SET","WIFI","PASS","password"}); assert(writes==2 && savedKey=="WIFI_PASS");
    handleEspValueSet({"SET","WIFI","PASS",""}); assert(writes==3 && savedValue.isEmpty());
    handleEspValueSet({"SET","4G","APN","example"}); assert(writes==4 && savedKey=="APN");
    serialOutput.clear();
    handleEspCommand({"SET","WIFI","SSID","tun"});
    assert(writes==5 && savedKey=="WIFI_SSID" && savedValue=="tun");
    assert(serialOutput.find("not yet implemented") == String::npos);
    serialOutput.clear();
    handleEspCommand({"SET","WIFI","PASS","password"});
    assert(writes==6 && savedKey=="WIFI_PASS" && serialOutput.find("not yet implemented") == String::npos);
    serialOutput.clear();
    handleEspCommand({"SET","WIFI","UNKNOWN","value"});
    assert(writes==6 && serialOutput.find("not yet implemented") != String::npos);
}
'''
with tempfile.TemporaryDirectory(prefix='wifi-command-') as directory:
    path=Path(directory); (path/'Arduino.h').write_text('#pragma once\n'+shim)
    (path/'check.cpp').write_text(harness+method+handler+checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(path),'-I'+str(root/'include'),str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: Wi-Fi commands validate credentials before persistence')
