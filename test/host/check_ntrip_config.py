"""Check endpoint aliases/validation and handshake preservation after NTRIP cleanup.

An optional previous firmware root compares all endpoint fields before/after.
"""
from pathlib import Path
import re
import sys
import tempfile
from host_coverage import compile_cpp, cpp_output, mapped

root = Path(__file__).resolve().parents[2]


def function(source, name):
    start = re.search(r'^\w[^\n]*\b' + name + r'\(', source, re.M).start()
    end = source.index('\n}', start) + 2
    return source[start:end] + '\n'


shim = (root / "test/host/Arduino.h").read_text().replace("#pragma once", "")
shim = "#define HOST_READBACK_TEST\n" + shim.replace("    void trim() {", "    void remove(size_t start, size_t count) { erase(start, count); }\n    int indexOf(const char *value) const { const auto p = find(value); return p == npos ? -1 : int(p); }\n    void trim() {") + r'''
#include <ArduinoJson.h>
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
constexpr unsigned NTRIP_CASTER_PORT = 2101;
constexpr const char *NTRIP_CASTER_ADDRESS = "default-host";
constexpr const char *NTRIP_MOUNTPOINT = "default-mount";
constexpr const char *NTRIP_AUTH_BASE_STATION = "default-password";
uint32_t now = 1000;
uint32_t millis() { return now; }
void delay(uint32_t ms) { now += ms; }
struct {
    std::map<String, String> strings;
    unsigned port = 2101;
    void begin(const char *, bool) {} void end() {}
    String getString(const char *key, String fallback) { return strings.count(key) ? strings[key] : fallback; }
    uint16_t getUShort(const char *, unsigned) { return port; }
} prefs;
struct { String service; String serviceConfigJson() { return service; } } backendAgent;
struct Client {
    String wire;
    size_t index = 0;
    bool idle = false;
    bool connected() { return idle || index < wire.size(); }
    int available() { return index < wire.size(); }
    int read() { return available() ? uint8_t(wire[index++]) : -1; }
};
'''
checks = r'''
void checkHandshake() {
    Client icy; icy.wire = "ICY 200 OK\r\n"; icy.wire += char(0xd3); icy.wire += "payload";
    assert(waitForNtripResponse(icy, nullptr, true));
    assert(icy.read() == 0xd3 && icy.index == 13);
    for (const char *protocol : {"HTTP/1.0", "HTTP/1.1"}) {
        Client http; http.wire = String(protocol) + " 200 OK\r\nServer: caster\r\n\r\n";
        http.wire += char(0xd3); String status;
        assert(waitForNtripResponse(http, &status, false));
        assert(status == String(protocol) + " 200 OK" && http.read() == 0xd3);
    }
    Client rejected; rejected.wire = "HTTP/1.1 401 Unauthorized\r\n\r\n"; String status;
    assert(!waitForNtripResponse(rejected, &status, false));
    assert(status == "HTTP/1.1 401 Unauthorized");
    now = UINT32_MAX - 5000;
    Client timeout; timeout.idle = true;
    const uint32_t started = now;
    assert(!waitForNtripResponse(timeout, &status, false));
    assert(uint32_t(now - started) == 10000 && now < started);
    assert(status == "No response from caster (timeout or closed connection)");
}
void emit() {
    loadEndpoints();
    for (const auto &endpoint : endpoints) {
        DynamicJsonDocument out(2048);
        out["enabled"] = endpoint.enabled; out["host"] = endpoint.host;
        out["port"] = endpoint.port; out["mountpoint"] = endpoint.mountpoint;
        out["username"] = endpoint.username; out["password"] = endpoint.password;
        out["version"] = endpoint.version;
        String text; serializeJson(out, text); std::cout << text << '\n';
    }
}
int main() {
    checkHandshake();
    prefs.strings = {{"NTRIP_SERVER", "legacy"}, {"NTRIP_MPT", "///mount"}, {"NT_AUTH_BS", "secret"}};
    prefs.port = 2201;
    for (const char *service : {"", "broken", "[]", "{}"}) { backendAgent.service = service; emit(); }
    backendAgent.service = ""; loadEndpoints();
    assert(endpoints[0].enabled && endpoints[0].host == "legacy" && endpoints[0].mountpoint == "mount");
    assert(endpoints[0].port == 2201 && endpoints[0].password == "secret");
    assert(!endpoints[1].enabled && endpoints[1].port == 2101);
    const std::array<const char *, 6> booleans = {"true", "1", "on", "false", "0", "off"};
    for (unsigned id = 1; id <= 2; ++id) {
        const String suffix(id);
        for (unsigned alias = 0; alias < 5; ++alias) {
            for (const auto boolean : booleans) {
                DynamicJsonDocument service(4096);
                service["server" + suffix + "_enabled"] = boolean;
                const String hostKeys[] = {"serverhost" + suffix, "server" + suffix + "_host", "host" + suffix, id == 1 ? "ip" : "ip2", "host"};
                const String mountKeys[] = {"mountpoint" + suffix, "mp" + suffix, id == 1 ? "mountpoint" : "mountpoint2"};
                const String userKeys[] = {"username" + suffix, "user" + suffix, id == 1 ? "user" : "user2"};
                const String passKeys[] = {"password" + suffix, "pass" + suffix, id == 1 ? "password" : "password2"};
                const String portKeys[] = {"port" + suffix, "serverport" + suffix, id == 1 ? "port" : "port2"};
                for (int k = 4; k >= int(alias); --k) service[hostKeys[k]] = String("host-") + String(k);
                const unsigned configAlias = alias % (id == 1 ? 3 : 2);
                for (int k = id == 1 ? 2 : 1; k >= int(configAlias); --k) {
                    service[mountKeys[k]] = String("///mount-") + String(k);
                    service[userKeys[k]] = String("user-") + String(k);
                    service[passKeys[k]] = String("password-") + String(k);
                    service[portKeys[k]] = 2300 + k;
                }
                service["ntrip_version" + suffix] = 2;
                backendAgent.service.clear(); serializeJson(service, backendAgent.service); emit();
                const auto &endpoint = endpoints[id - 1];
                assert(endpoint.version == 2 && endpoint.port == 2300 + configAlias);
                assert(endpoint.mountpoint == String("mount-") + String(configAlias));
                assert(endpoint.username == String("user-") + String(configAlias));
                assert(endpoint.password == String("password-") + String(configAlias));
                assert(endpoint.host == (id == 2 && alias == 4 ? String() : String("host-") + String(alias)));
                assert(endpoint.enabled == ((alias < 4 || id == 1) && (String(boolean) == "true" || String(boolean) == "1" || String(boolean) == "on")));

            }
        }
    }
    for (const char *json : {
        R"({"server1_enabled":true,"serverhost1":"bad\r\nhost","mountpoint1":"m"})",
        R"({"server1_enabled":true,"serverhost1":"host","mountpoint1":"///"})",
        R"({"server1_enabled":true,"serverhost1":"host","mountpoint1":"m","port1":0})",
        R"({"server1_enabled":true,"serverhost1":"host","mountpoint1":"m","password1":"bad\npass"})"}) {
        backendAgent.service = json; emit(); assert(!endpoints[0].enabled);
    }
}
'''


def execute(firmware, directory, previous=False):
    base_path = firmware / 'src/functions/ntrip/ntrip_base.cpp'
    common_path = firmware / 'src/functions/ntrip/ntrip_common.cpp'
    if not base_path.exists():
        base_path = common_path = firmware / 'src/functions/ntrip/NTRIP_Handler_IP.cpp'
    base = base_path.read_text()
    common = common_path.read_text()
    agent_path = firmware / 'src/functions/backend/Backend_Agent.cpp'
    agent = agent_path.read_text()
    config = base[base.index('constexpr size_t CONFIG_DOCUMENT_SIZE'):base.index('bool streamActive(')]
    if base_path == common_path:
        # Old monolith has transport/rover state between endpoint storage and config loader.
        config = config[:config.index('static Vn2000Session')] + function(base, 'loadEndpoints')
    fragments = [(agent_path, function(agent, 'jsonBool')), (agent_path, function(agent, 'jsonString')),
                 (common_path, function(common, 'safeNtripField')),
                 (base_path, config),
                 (common_path, function(common, 'waitForNtripResponse'))]
    body = ''.join(text if previous else mapped(path, text) for path, text in fragments)
    cpp = directory / ('previous.cpp' if previous else 'current.cpp')
    cpp.write_text(shim + body + checks)
    binary = cpp.with_suffix('')
    compile_cpp(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-Wno-unused-const-variable', '-fsanitize=address,undefined',
                 '-I'+str(root/'test/host'), '-I'+str(root/'.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                 str(cpp), '-o', str(binary)], check=True)
    return cpp_output([str(binary)], text=True)


with tempfile.TemporaryDirectory(prefix='ntrip-config-') as directory:
    path = Path(directory)
    current = execute(root, path)
    if len(sys.argv) > 1:
        assert current == execute(Path(sys.argv[1]).resolve(), path, previous=True)
print('PASS: 68 endpoint configurations, alias precedence, validation, ICY/HTTP payload preservation and millis wraparound')
