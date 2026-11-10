#define NTRIP_HANDLER_IP_CODE

#include "functions/ntrip/NTRIP_Handler_IP.h"

#include "Prog_Config.h"
#include "functions/backend/Backend_Agent.h"
#include "functions/backend/Backend_Agent_Internal.h"
#include "functions/ntrip/RTCM_Receiver.h"
#include "hardware/Sim_handler.h"
#include "hardware/Wifi_handler.h"

#include <ArduinoJson.h>
#include <Preferences.h>
#include <cstring>

extern Preferences prefs;
extern TinyGsm modem;

using BackendAgentInternal::jsonBool;
using BackendAgentInternal::jsonString;
using BackendAgentInternal::encodeBase64;

namespace {

bool safeNtripField(const String &value) {
    return value.indexOf('\r') < 0 && value.indexOf('\n') < 0;
}

constexpr size_t CONFIG_DOCUMENT_SIZE = 4096;
constexpr uint8_t NTRIP_SERVER_COUNT = 2;
constexpr uint32_t RECONNECT_INTERVAL_MS = 5000;
constexpr uint32_t BPS_WINDOW_MS = 1000;

struct NtripEndpoint {
    bool enabled = false;
    bool authenticated = false;
    String host;
    uint16_t port = 2101;
    String mountpoint;
    String username;
    String password;
    uint8_t version = 1;
    uint32_t lastReconnectMs = 0;
    uint32_t bytesInWindow = 0;
    uint32_t bytesPerSecond = 0;
    uint32_t windowStartedMs = 0;
    uint32_t lastKeepAliveMs = 0;
    String lastError;
};

NtripEndpoint endpoints[NTRIP_SERVER_COUNT];
static Vn2000Session roverDatumSession;
WiFiClient wifiNtripClient1;
WiFiClient wifiNtripClient2;
TinyGsmClient gsmNtripClient1(modem, 0);
TinyGsmClient gsmNtripClient2(modem, 2);
bool roverSessionActive = false;
bool roverSessionAuthenticated = false;
uint32_t roverLastGgaMs = 0;
uint32_t roverBytesReceived = 0;
uint32_t roverPacketsReceived = 0;
uint32_t roverBytesWritten = 0, roverLastDiagnosticMs = 0;
const char *roverLastError = "CORS rover connection lost";

Client &clientFor(uint8_t index) {
    if (index == 0) {
        return isWifiConnection()
            ? static_cast<Client &>(wifiNtripClient1)
            : static_cast<Client &>(gsmNtripClient1);
    }
    return isWifiConnection()
        ? static_cast<Client &>(wifiNtripClient2)
        : static_cast<Client &>(gsmNtripClient2);
}

void clearEndpointState(NtripEndpoint &endpoint) {
    endpoint.authenticated = false;
    endpoint.bytesInWindow = 0;
    endpoint.bytesPerSecond = 0;
    endpoint.windowStartedMs = millis();
    endpoint.lastKeepAliveMs = endpoint.windowStartedMs;
}

void loadEndpoints() {
    DynamicJsonDocument serviceDoc(CONFIG_DOCUMENT_SIZE);
    const String serialized = backendAgent.serviceConfigJson();
    const bool hasServiceConfig = deserializeJson(serviceDoc, serialized) == DeserializationError::Ok
        && serviceDoc.is<JsonObject>();
    const JsonObjectConst service = serviceDoc.as<JsonObjectConst>();

    String legacyHost;
    String legacyMountpoint;
    String legacyPassword;
    uint16_t legacyPort = NTRIP_CASTER_PORT;
    prefs.begin("myPrefs", true);
    legacyHost = prefs.getString("NTRIP_SERVER", String(NTRIP_CASTER_ADDRESS));
    legacyPort = prefs.getUShort("NTRIP_PORT", NTRIP_CASTER_PORT);
    legacyMountpoint = prefs.getString("NTRIP_MPT", String(NTRIP_MOUNTPOINT));
    legacyPassword = prefs.getString("NT_AUTH_BS", String(NTRIP_AUTH_BASE_STATION));
    prefs.end();

    for (uint8_t index = 0; index < NTRIP_SERVER_COUNT; ++index) {
        NtripEndpoint &endpoint = endpoints[index];
        const uint8_t serverId = index + 1;
        const String suffix = String(serverId);
        const String enabledKey = "server" + suffix + "_enabled";
        const String hostKey = "serverhost" + suffix;
        const String portKey = "port" + suffix;
        const String mountpointKey = "mountpoint" + suffix;
        const String usernameKey = "username" + suffix;
        const String passwordKey = "password" + suffix;
        const String versionKey = "ntrip_version" + suffix;
        const String genericHostKey = index == 0 ? String("ip") : String("ip2");
        const String genericPortKey = index == 0 ? String("port") : String("port2");
        const String genericUserKey = index == 0 ? String("user") : String("user2");
        const String genericPasswordKey = index == 0 ? String("password") : String("password2");
        const String genericMountpointKey = index == 0 ? String("mountpoint") : String("mountpoint2");

        endpoint.enabled = hasServiceConfig
            ? jsonBool(service, enabledKey, false)
            : index == 0 && !legacyHost.isEmpty();
        endpoint.host = hasServiceConfig
            ? jsonString(service, hostKey,
                         jsonString(service, "server" + suffix + "_host",
                                    jsonString(service, "host" + suffix,
                                               jsonString(service, genericHostKey,
                                                          index == 0 ? jsonString(service, "host", String()) : String()))))
            : (index == 0 ? legacyHost : String());
        endpoint.port = hasServiceConfig
            ? static_cast<uint16_t>(service[portKey.c_str()]
                | (service[("serverport" + suffix).c_str()]
                    | (service[genericPortKey.c_str()] | (index == 0 ? legacyPort : 2101))))
            : (index == 0 ? legacyPort : 2101);
        endpoint.mountpoint = hasServiceConfig
            ? jsonString(service, mountpointKey,
                         jsonString(service, "mp" + suffix,
                                    jsonString(service, genericMountpointKey, String())))
            : (index == 0 ? legacyMountpoint : String());
        endpoint.username = hasServiceConfig
            ? jsonString(service, usernameKey,
                         jsonString(service, "user" + suffix,
                                    jsonString(service, genericUserKey, "source")))
            : "source";
        endpoint.password = hasServiceConfig
            ? jsonString(service, passwordKey,
                         jsonString(service, "pass" + suffix,
                                    jsonString(service, genericPasswordKey,
                                               index == 0 ? legacyPassword : String())))
            : (index == 0 ? legacyPassword : String());
        endpoint.version = hasServiceConfig
            ? static_cast<uint8_t>(service[versionKey.c_str()] | 1)
            : 1;

        while (endpoint.mountpoint.startsWith("/")) endpoint.mountpoint.remove(0, 1);
        endpoint.enabled = endpoint.enabled && endpoint.host.length() > 0
            && endpoint.mountpoint.length() > 0 && endpoint.port > 0
            && safeNtripField(endpoint.host) && safeNtripField(endpoint.mountpoint)
            && safeNtripField(endpoint.username) && safeNtripField(endpoint.password);
    }
}

bool streamActive(uint8_t index) {
    if (index >= NTRIP_SERVER_COUNT || backendDeviceLocked(index + 1)
        || !backendLicenseValid() || !backendDeviceProvisioned() || !backendBaseStartupConfigured()) return false;
    DynamicJsonDocument serviceDoc(CONFIG_DOCUMENT_SIZE);
    if (deserializeJson(serviceDoc, backendAgent.serviceConfigJson()) != DeserializationError::Ok
        || !serviceDoc.is<JsonObject>()) {
        return index == 0;
    }
    return BackendAgent::effectiveStreamActive(
        serviceDoc.as<JsonObjectConst>(), index + 1, backendControlPlaneFailOpen());
}

void stopEndpoint(uint8_t index) {
    clientFor(index).stop();
    clearEndpointState(endpoints[index]);
}

bool waitForNtripResponse(Client &client, String *statusLine = nullptr, String *selectedMountpoint = nullptr) {
    String response;
    response.reserve(512);
    const uint32_t started = millis();
    while ((client.connected() || client.available() > 0) && millis() - started < 10000UL && response.length() < 4096) {
        while (client.available() > 0 && response.length() < 4096) {
            const int value = client.read();
            if (value < 0) break;
            response += static_cast<char>(value);
            if (response.endsWith("\r\n\r\n") || response == "ICY 200 OK\r\n") break;
        }
        if (response.indexOf("\r\n\r\n") >= 0 || response == "ICY 200 OK\r\n") break;
        delay(1);
    }
    if (statusLine) {
        const int end = response.indexOf('\n');
        *statusLine = response.substring(0, end >= 0 ? end : 240);
        statusLine->trim();
        if (statusLine->isEmpty()) *statusLine = "No response from caster (timeout or closed connection)";
    }
    if (selectedMountpoint && response.endsWith("\r\n\r\n")) {
        const char *header = "\r\nX-NTRIP-Selected-Mountpoint:";
        const int field = response.indexOf(header);
        if (field >= 0) {
            const int start = field + strlen(header);
            const int end = response.indexOf('\r', start);
            if (end > start) {
                *selectedMountpoint = response.substring(start, end);
                selectedMountpoint->trim();
            }
        }
    }
    return response.indexOf("ICY 200 OK") >= 0
        || response.indexOf("HTTP/1.1 200 OK") >= 0
        || response.indexOf("HTTP/1.0 200 OK") >= 0;
}

void sendRoverGgaIfAvailable(Client &client, const bool force = false) {
    if (!force && millis() - roverLastGgaMs < 5000UL) return;
    const GnssTelemetrySnapshot snapshot = getGnssTelemetrySnapshot();
    if (snapshot.lastGga[0] == '\0' || snapshot.lastGgaMs == 0
        || millis() - snapshot.lastGgaMs > 3000UL) {
        if (force || millis() - roverLastGgaMs >= 5000UL) {
            Serial.println("[NTRIP ROVER] Chua co GGA moi tu UART GNSS; chua gui GGA len caster");
            roverLastGgaMs = millis();
        }
        return;
    }
    const String outbound = String(snapshot.lastGga) + "\r\n";
    if (client.print(outbound) != outbound.length()) {
        Serial.println("[NTRIP ROVER] Loi ghi GGA len socket caster");
        roverLastGgaMs = millis();
        return;
    }
    Serial.printf("[NTRIP ROVER] GGA -> caster: %s\n", snapshot.lastGga);
    roverLastGgaMs = millis();
}

bool connectEndpoint(uint8_t index) {
    if (index >= NTRIP_SERVER_COUNT || !endpoints[index].enabled || !streamActive(index)) return false;
    NtripEndpoint &endpoint = endpoints[index];
    Client &client = clientFor(index);
    endpoint.lastReconnectMs = millis();
    client.stop();
    client.setTimeout(3000);

    Serial.println("[NTRIP] Ket noi S" + String(index + 1) + ": "
                   + endpoint.host + ":" + String(endpoint.port)
                   + "/" + endpoint.mountpoint);
    if (!client.connect(endpoint.host.c_str(), endpoint.port)) {
        endpoint.lastError = "TCP connection failed";
        Serial.printf("[NTRIP][ERROR] S%u: %s\n", index + 1, endpoint.lastError.c_str());
        clearEndpointState(endpoint);
        return false;
    }

    const String user = endpoint.username.isEmpty() ? String("source") : endpoint.username;
    const String auth = encodeBase64(user + ":" + endpoint.password);
    String request;
    if (endpoint.version == 2) {
        request = "POST /" + endpoint.mountpoint + " HTTP/1.1\r\n"
                  "Host: " + endpoint.host + ":" + String(endpoint.port) + "\r\n"
                  "Ntrip-Version: Ntrip/2.0\r\n"
                  "User-Agent: NTRIP ESP32-Agent/" + String(AGENT_VERSION) + "\r\n"
                  "Authorization: Basic " + auth + "\r\n"
                  "Transfer-Encoding: chunked\r\n"
                  "Connection: Keep-Alive\r\n\r\n";
    } else {
        request = "SOURCE " + endpoint.password + " /" + endpoint.mountpoint + " HTTP/1.1\r\n"
                  "Host: " + endpoint.host + ":" + String(endpoint.port) + "\r\n"
                  "Ntrip-Version: Ntrip/2.0\r\n"
                  "User-Agent: NTRIP ESP32-Agent/" + String(AGENT_VERSION) + "\r\n"
                  "Authorization: Basic " + auth + "\r\n"
                  "Connection: Keep-Alive\r\n\r\n";
    }
    client.print(request);

    String responseLine;
    if (!waitForNtripResponse(client, &responseLine)) {
        if (!endpoint.password.isEmpty()) responseLine.replace(endpoint.password, "[redacted]");
        endpoint.lastError = responseLine;
        Serial.printf("[NTRIP][ERROR] Caster tu choi S%u: %s\n", index + 1, responseLine.c_str());
        client.stop();
        clearEndpointState(endpoint);
        return false;
    }

    endpoint.authenticated = true;
    endpoint.lastError = "";
    endpoint.windowStartedMs = millis();
    endpoint.bytesInWindow = 0;
    endpoint.bytesPerSecond = 0;
    endpoint.lastKeepAliveMs = endpoint.windowStartedMs;
    Serial.println("[NTRIP] Xac thuc thanh cong S" + String(index + 1));
    return true;
}

void updateBps(NtripEndpoint &endpoint) {
    const uint32_t now = millis();
    if (endpoint.windowStartedMs == 0) endpoint.windowStartedMs = now;
    if (now - endpoint.windowStartedMs >= BPS_WINDOW_MS) {
        const uint32_t elapsed = now - endpoint.windowStartedMs;
        endpoint.bytesPerSecond = elapsed > 0
            ? static_cast<uint32_t>((static_cast<uint64_t>(endpoint.bytesInWindow) * 1000ULL) / elapsed)
            : endpoint.bytesInWindow;
        endpoint.bytesInWindow = 0;
        endpoint.windowStartedMs = now;
    }
}

} // namespace

Client &activeNtripClient() {
    return clientFor(0);
}

int setupNTRIP() {
    for (uint8_t index = 0; index < NTRIP_SERVER_COUNT; ++index) stopEndpoint(index);
    loadEndpoints();
    return 0;
}

int connectNTRIP() {
    loadEndpoints();
    int connected = 0;
    for (uint8_t index = 0; index < NTRIP_SERVER_COUNT; ++index) {
        if (connectEndpoint(index)) ++connected;
    }
    return connected > 0 ? 0 : -1;
}

static bool sendEndpointRtcm(NtripEndpoint &endpoint, Client &client, const String &rtcmData) {
    if (rtcmData.isEmpty()) {
        if (endpoint.version == 2 && millis() - endpoint.lastKeepAliveMs >= 10000UL) {
            client.print("0\r\n\r\n");
            endpoint.lastKeepAliveMs = millis();
        }
        return false;
    }
    const size_t payloadLength = rtcmData.length();
    if (endpoint.version == 2) client.print(String(payloadLength, HEX) + "\r\n");
    const size_t sent = client.write(reinterpret_cast<const uint8_t *>(rtcmData.c_str()), payloadLength);
    if (endpoint.version == 2) client.print("\r\n");
    if (sent != payloadLength) return false;
    endpoint.bytesInWindow += static_cast<uint32_t>(sent);
    return true;
}

int loopNTRIP(String &rtcmData) {
    if (roverSessionActive || backendAgent.workflowActive()) return 504;

    int returnCode = NTRIP_MODE;
    bool anyConnected = false;
    bool anySent = false;

    for (uint8_t index = 0; index < NTRIP_SERVER_COUNT; ++index) {
        NtripEndpoint &endpoint = endpoints[index];
        Client &client = clientFor(index);
        if (!endpoint.enabled || !streamActive(index)) {
            if (client.connected()) client.stop();
            clearEndpointState(endpoint);
            continue;
        }

        if (!client.connected() || !endpoint.authenticated) {
            endpoint.authenticated = false;
            if (millis() - endpoint.lastReconnectMs >= RECONNECT_INTERVAL_MS) {
                if (connectEndpoint(index)) anyConnected = true;
            }
            continue;
        }

        anyConnected = true;
        anySent = sendEndpointRtcm(endpoint, client, rtcmData) || anySent;
        updateBps(endpoint);
    }

    if (anySent) returnCode += 4;
    if (!anyConnected) returnCode = 504;
    return returnCode;
}

void stopNtrip() {
    for (uint8_t index = 0; index < NTRIP_SERVER_COUNT; ++index) stopEndpoint(index);
    roverSessionActive = false;
    roverSessionAuthenticated = false;
    roverLastGgaMs = 0;
}

bool isNtripConnected() {
    return ntripServerConnected(1) || ntripServerConnected(2);
}

bool ntripServerConnected(uint8_t serverId) {
    if (serverId < 1 || serverId > NTRIP_SERVER_COUNT) return false;
    const uint8_t index = serverId - 1;
    return endpoints[index].authenticated && clientFor(index).connected();
}

uint32_t ntripServerBps(uint8_t serverId) {
    if (serverId < 1 || serverId > NTRIP_SERVER_COUNT) return 0;
    updateBps(endpoints[serverId - 1]);
    return endpoints[serverId - 1].bytesPerSecond;
}

String ntripServerError(uint8_t serverId) {
    if (serverId < 1 || serverId > NTRIP_SERVER_COUNT) return String();
    return endpoints[serverId - 1].lastError;
}

bool startNtripRover(const String &host, const uint16_t port, const String &username,
                    const String &password, String mountpoint, const uint8_t version, String *selectedMountpoint,
                    const String &receiverId) {
    if (host.isEmpty() || port == 0 || mountpoint.isEmpty()
        || !safeNtripField(host) || !safeNtripField(username)
        || !safeNtripField(password) || !safeNtripField(mountpoint)
        || !safeNtripField(receiverId)) return false;
    while (mountpoint.startsWith("/")) mountpoint.remove(0, 1);
    if (mountpoint.isEmpty()) return false;

    // The temporary rover reuses source server 1's client and modem mux 0.
    // Close that client before opening a receive-only correction stream.
    roverDatumSession.reset();
    roverBytesReceived = 0;
    roverPacketsReceived = 0;
    roverBytesWritten = 0;
    roverLastDiagnosticMs = millis();
    roverLastError = "CORS rover connection lost";
    roverSessionActive = true;
    roverSessionAuthenticated = false;
    roverLastGgaMs = 0;
    Client &client = clientFor(0);
    client.stop();
    client.setTimeout(3000);
    if (!client.connect(host.c_str(), port)) {
        roverSessionActive = false;
        return false;
    }

    const String user = username.isEmpty() ? String("source") : username;
    const String auth = encodeBase64(user + ":" + password);
    String agent = "NTRIP ESP32-Agent/" + String(AGENT_VERSION);
    if (!receiverId.isEmpty()) agent += "/" + receiverId;
    String request;
    if (version == 2) {
        request = "GET /" + mountpoint + " HTTP/1.1\r\n"
                  "Host: " + host + ":" + String(port) + "\r\n"
                  "Ntrip-Version: Ntrip/2.0\r\n"
                  "User-Agent: " + agent + "\r\n"
                  "Authorization: Basic " + auth + "\r\n"
                  "Accept: */*\r\n"
                  "Connection: Keep-Alive\r\n\r\n";
    } else {
        request = "GET /" + mountpoint + " HTTP/1.0\r\n"
                  "User-Agent: " + agent + "\r\n"
                  "Authorization: Basic " + auth + "\r\n"
                  "Accept: */*\r\n"
                  "Connection: close\r\n\r\n";
    }
    // AutoNearest có thể quyết định ngay từ yêu cầu, trước khi trả ICY.
    const auto snapshot = getGnssTelemetrySnapshot();
    if (snapshot.lastGga[0] != '\0' && snapshot.lastGgaMs != 0
        && millis() - snapshot.lastGgaMs <= 3000UL) {
        String gga = snapshot.lastGga;
        gga.trim();
        if (gga.indexOf('\r') < 0 && gga.indexOf('\n') < 0) {
            request.remove(request.length() - 2);
            request += "Ntrip-GGA: " + gga + "\r\n\r\n";
        }
    }
    if (selectedMountpoint) {
        selectedMountpoint->clear();
        request.remove(request.length() - 2);
        request += "X-NTRIP-Report-Selected: 1\r\n\r\n";
    }
    client.print(request);

    String responseLine;
    if (!waitForNtripResponse(client, &responseLine, selectedMountpoint)) {
        if (responseLine == "ERROR - NO STATION WITHIN 20 KM")
            roverLastError = "ERROR - NO STATION WITHIN 20 KM";
        else if (responseLine == "ERROR - FIXED STATION IN RANGE UNAVAILABLE")
            roverLastError = "ERROR - FIXED STATION IN RANGE UNAVAILABLE";
        else if (responseLine == "ERROR - FIXED STATION CATALOG UNAVAILABLE")
            roverLastError = "ERROR - FIXED STATION CATALOG UNAVAILABLE";
        else if (responseLine == "ERROR - AUTONEAREST NOT ENABLED")
            roverLastError = "ERROR - AUTONEAREST NOT ENABLED";
        client.stop();
        roverSessionActive = false;
        return false;
    }
    if (selectedMountpoint && selectedMountpoint->isEmpty()) {
        roverLastError = "Caster did not confirm the selected mountpoint";
        client.stop();
        roverSessionActive = false;
        return false;
    }
    roverSessionAuthenticated = true;
    sendRoverGgaIfAvailable(client, true);
    Serial.println("[NTRIP ROVER] Da ket noi CORS " + host + ":" + String(port)
                   + "/" + mountpoint);
    return true;
}

int loopNtripRover() {
    if (!roverSessionActive || !roverSessionAuthenticated) return 504;
    Client &client = clientFor(0);
    if (!client.connected()) {
        Serial.printf("[NTRIP ROVER][ERROR] CORS socket closed; cors_rx=%lu B; uart_tx=%lu B; rtcm_frames=%lu\n",
                      static_cast<unsigned long>(roverBytesReceived),
                      static_cast<unsigned long>(roverBytesWritten),
                      static_cast<unsigned long>(roverDatumSession.validFrames()));
        roverSessionActive = false;
        roverSessionAuthenticated = false;
        return 504;
    }
    sendRoverGgaIfAvailable(client);
    if (millis() - roverLastDiagnosticMs >= 5000UL) {
        roverLastDiagnosticMs = millis();
        const auto snapshot = getGnssTelemetrySnapshot();
        Serial.printf("[NTRIP ROVER][DATA] cors_rx=%lu B; uart_tx=%lu B; rtcm_frames=%lu; fix=%s\n",
                      static_cast<unsigned long>(roverBytesReceived),
                      static_cast<unsigned long>(roverBytesWritten),
                      static_cast<unsigned long>(roverDatumSession.validFrames()), snapshot.fixStatus);
    }
    if (client.available() <= 0) return 200;

    uint8_t buffer[512] = {};
    if (!rtcmBufferMutex
        || xSemaphoreTake(rtcmBufferMutex, pdMS_TO_TICKS(MUTEX_TIMEOUT_MS)) != pdTRUE) {
        return 200;
    }
    const int available = client.available();
    const size_t bytesToRead = min(static_cast<size_t>(available), sizeof(buffer));
    const int bytesRead = client.read(buffer, bytesToRead);
    if (bytesRead > 0) {
        roverDatumSession.feed(buffer, static_cast<size_t>(bytesRead));
        const size_t written = Serial1.write(buffer, static_cast<size_t>(bytesRead));
        roverBytesReceived += static_cast<uint32_t>(bytesRead);
        roverBytesWritten += static_cast<uint32_t>(written);
        ++roverPacketsReceived;
        if (written != static_cast<size_t>(bytesRead)) {
            roverLastError = "GNSS UART did not accept all CORS bytes";
            Serial.printf("[NTRIP ROVER][ERROR] UART accepted %u/%u bytes\n",
                          static_cast<unsigned>(written), static_cast<unsigned>(bytesRead));
            xSemaphoreGive(rtcmBufferMutex);
            return 504;
        }
    }
    xSemaphoreGive(rtcmBufferMutex);
    // Return status, not byte count: a valid 504-byte read must not look like failure.
    return 200;
}

void stopNtripRover() {
    if (roverSessionActive) clientFor(0).stop();
    roverSessionActive = false;
    roverSessionAuthenticated = false;
    roverLastGgaMs = 0;
}

bool ntripRoverActive() {
    return roverSessionActive && roverSessionAuthenticated;
}

uint32_t ntripRoverBytesReceived() { return roverBytesReceived; }
uint32_t ntripRoverPacketsReceived() { return roverPacketsReceived; }

Vn2000Datum ntripRoverDatum() { return roverDatumSession.datum(); }

const char *ntripRoverLastError() { return roverLastError; }
