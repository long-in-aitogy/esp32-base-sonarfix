#define NTRIP_HANDLER_IP_CODE

#include "functions/ntrip/NTRIP_Handler_IP.h"

#include "Prog_Config.h"
#include "functions/backend/Backend_Agent.h"
#include "functions/ntrip/RTCM_Receiver.h"
#include "functions/gnss/unicore_commands.h"
#include "functions/gnss/Unicore_Identification.h"
#include "hardware/Sim_handler.h"
#include "hardware/Wifi_handler.h"

#include <ArduinoJson.h>
#include <Preferences.h>
#include <array>
#include <cstring>

extern Preferences prefs;
extern TinyGsm modem;

namespace {
  class ntripConfig {
  public:
    inline static bool isIcyOk = false;
    inline static unsigned long lastReconnect = 0;
    inline static bool isNmeaSent = false;
  };

  // ================= HẰNG STRING =================
  inline constexpr const char nmeaCmdUnlog[] = "UNLOG\r\n";
  inline constexpr const char nmeaCmdSetBase[] = "MODE BASE TIME 120 2.5\r\n";
  inline constexpr const char rtcm1084SetOutputCom2[] = "RTCM1084 COM2 1\r\n";
  inline constexpr const char rtcm1074SetOutputCom2[] = "RTCM1074 COM2 1\r\n";
  inline constexpr const char rtcm1006SetOutputCom2[] = "RTCM1006 COM2 1\r\n";
  inline constexpr const char rtcm1124SetOutputCom2[] = "RTCM1124 COM2 1\r\n";
  inline constexpr const char rtcm1087SetOutputCom2[] = "RTCM1087 COM2 1\r\n";
  inline constexpr const char rtcm1077SetOutputCom2[] = "RTCM1077 COM2 1\r\n";
  inline constexpr const char rtcm1127SetOutputCom2[] = "RTCM1127 COM2 1\r\n";
  inline constexpr const char rtcmSetBaudCom2[] = "CONFIG COM2 115200\r\n";
  inline constexpr const char cmdSaveConfig[] = "saveconfig\r\n";
    inline constexpr std::array<uint8_t, 8> ubxMonVerPoll = {
    0xB5, 0x62, 0x0A, 0x04, 0x00, 0x00, 0x0E, 0x34
  };

  void waitForUm980Input()
  {
    const auto started = millis();
    while (!Serial1.available() && millis() - started < 2000) delay(10);
  }

  void logUm980Response()
  {
#ifdef PROGRAM_DEBUG
    waitForUm980Input();
    const auto response = Serial1.readStringUntil('\n');
    Serial.println("[NMEA CMD] Response: " + response);
#endif
  }

  inline void sendUm980Command(const char *command, size_t maxLength, bool logResponse,
                               uint32_t pauseMs)
  {
    waitForUm980Input();
    Serial1.write(command, strnlen(command, maxLength));
    if (logResponse) logUm980Response();
    if (pauseMs > 0) delay(pauseMs);
  }

  void clearGnssInput()
  {
    while (Serial1.available() > 0) {
      Serial1.read();
    }
  }

  bool hasValidUbxFrame(const uint8_t *data, size_t length)
  {
    for (size_t start = 0; start + 8 <= length; ++start) {
      if (data[start] != 0xB5 || data[start + 1] != 0x62 ||
          data[start + 2] != 0x0A || data[start + 3] != 0x04) {
        continue;
      }

      const auto payloadLength =
          static_cast<size_t>(data[start + 4]) |
          (static_cast<size_t>(data[start + 5]) << 8);
      const auto frameLength = payloadLength + 8;
      // A MON-VER response contains SW (30 bytes) and HW (10 bytes), never an empty poll.
      if (payloadLength < 40 || frameLength > 512) continue;
      if (start + frameLength > length) {
        continue;
      }

      uint8_t checksumA = 0;
      uint8_t checksumB = 0;
      for (size_t i = start + 2; i < start + 6 + payloadLength; ++i) {
        checksumA = static_cast<uint8_t>(checksumA + data[i]);
        checksumB = static_cast<uint8_t>(checksumB + checksumA);
      }

      if (checksumA == data[start + frameLength - 2] &&
          checksumB == data[start + frameLength - 1]) {
        return true;
      }
    }
    return false;
  }

  bool receiveUbxFrame(uint32_t timeoutMs)
  {
    std::array<uint8_t, 512> buffer{};
    auto length = 0;
    const uint32_t start = millis();

    while (millis() - start < timeoutMs) {
      while (Serial1.available() > 0) {
        const auto value = Serial1.read();
                if (length < buffer.size()) {
          buffer[length++] = static_cast<uint8_t>(value);
        } else {
                    memmove(buffer.data(), buffer.data() + 1, buffer.size() - 1);
                    buffer[buffer.size() - 1] = static_cast<uint8_t>(value);
        }
        if (hasValidUbxFrame(buffer.data(), length)) {
          return true;
        }
      }
      delay(2);
    }
    return false;
  }

  bool receiveUnicoreIdentification(uint32_t timeoutMs)
  {
    UnicoreIdentification identity;
    const uint32_t start = millis();
    while (millis() - start < timeoutMs) {
      while (Serial1.available() > 0) {
        if (identity.feed(static_cast<uint8_t>(Serial1.read()))) {
          Serial.printf("[GNSS][UNICORE RESPONSE] %s\n", identity.line.data());
          return true;
        }
      }
      delay(2);
    }

    return false;
  }
} // namespace

bool jsonBool(JsonObjectConst object, const String &key, bool fallback = false) {
    const JsonVariantConst value = object[key.c_str()];
    if (value.isNull()) return fallback;
    if (value.is<bool>()) return value.as<bool>();
    if (value.is<const char *>()) {
        const String text = value.as<String>();
        if (text.equalsIgnoreCase("true") || text == "1" || text.equalsIgnoreCase("on")) return true;
        if (text.equalsIgnoreCase("false") || text == "0" || text.equalsIgnoreCase("off")) return false;
    }
    return value.as<int>() != 0;
}

String jsonString(JsonObjectConst object, const String &key, const String &fallback = String()) {
    const JsonVariantConst value = object[key.c_str()];
    return value.isNull() ? fallback : value.as<String>();
}

bool safeNtripField(const String &value) {
    return value.indexOf('\r') < 0 && value.indexOf('\n') < 0;
}

struct LegacyNtripConfig {
    String host;
    String mountpoint;
    String password;
    uint16_t port = NTRIP_CASTER_PORT;
};

LegacyNtripConfig loadLegacyNtripConfig() {
    LegacyNtripConfig legacy;
    prefs.begin("myPrefs", true);
    legacy.host = prefs.getString("NTRIP_SERVER", String(NTRIP_CASTER_ADDRESS));
    legacy.port = prefs.getUShort("NTRIP_PORT", NTRIP_CASTER_PORT);
    legacy.mountpoint = prefs.getString("NTRIP_MPT", String(NTRIP_MOUNTPOINT));
    legacy.password = prefs.getString("NT_AUTH_BS", String(NTRIP_AUTH_BASE_STATION));
    prefs.end();
    return legacy;
}

String endpointHost(JsonObjectConst service, uint8_t index) {
    const auto suffix = String(index + 1);
    const auto generic = index == 0 ? "ip" : "ip2";
    const auto fallback = index == 0 ? jsonString(service, "host", String()) : String();
    return jsonString(service, "serverhost" + suffix,
        jsonString(service, "server" + suffix + "_host",
            jsonString(service, "host" + suffix,
                jsonString(service, generic, fallback))));
}

uint16_t endpointPort(JsonObjectConst service, uint8_t index, uint16_t legacyPort) {
    const auto suffix = String(index + 1);
    const auto generic = index == 0 ? "port" : "port2";
    const uint16_t fallback = index == 0 ? legacyPort : 2101;
    return static_cast<uint16_t>(service["port" + suffix]
        | (service["serverport" + suffix] | (service[generic] | fallback)));
}

String base64Encode(const String &plain) {
    static constexpr char alphabet[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    String encoded;
    encoded.reserve(((plain.length() + 2) / 3) * 4);
    for (size_t i = 0; i < plain.length(); i += 3) {
        const uint32_t a = static_cast<uint8_t>(plain[i]);
        const uint32_t b = i + 1 < plain.length() ? static_cast<uint8_t>(plain[i + 1]) : 0;
        const uint32_t c = i + 2 < plain.length() ? static_cast<uint8_t>(plain[i + 2]) : 0;
        const uint32_t value = (a << 16) | (b << 8) | c;
        encoded += alphabet[(value >> 18) & 0x3F];
        encoded += alphabet[(value >> 12) & 0x3F];
        encoded += i + 1 < plain.length() ? alphabet[(value >> 6) & 0x3F] : '=';
        encoded += i + 2 < plain.length() ? alphabet[value & 0x3F] : '=';
    }
    return encoded;
}

namespace {
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

std::array<NtripEndpoint, NTRIP_SERVER_COUNT> endpoints;
WiFiClient wifiNtripClient1;
WiFiClient wifiNtripClient2;
TinyGsmClient gsmNtripClient1(modem, 0);
TinyGsmClient gsmNtripClient2(modem, 2);
bool roverSessionActive = false;
bool roverSessionAuthenticated = false;
uint32_t roverLastGgaMs = 0;
uint32_t roverBytesReceived = 0;
uint32_t roverPacketsReceived = 0;

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
}

void clearEndpointState(NtripEndpoint &endpoint) {
    endpoint.authenticated = false;
    endpoint.bytesInWindow = 0;
    endpoint.bytesPerSecond = 0;
    endpoint.windowStartedMs = millis();
    endpoint.lastKeepAliveMs = endpoint.windowStartedMs;
}

void normalizeEndpoint(NtripEndpoint &endpoint) {
    while (endpoint.mountpoint.startsWith("/")) endpoint.mountpoint.remove(0, 1);
    endpoint.enabled = endpoint.enabled && !endpoint.host.isEmpty()
        && !endpoint.mountpoint.isEmpty() && endpoint.port > 0
        && safeNtripField(endpoint.host) && safeNtripField(endpoint.mountpoint)
        && safeNtripField(endpoint.username) && safeNtripField(endpoint.password);
}

void loadEndpoint(NtripEndpoint &endpoint, uint8_t index, JsonObjectConst service,
                  bool hasServiceConfig, const LegacyNtripConfig &legacy) {
    const auto suffix = String(index + 1);
    auto genericUser = "user2";
    auto genericPassword = "password2";
    auto genericMountpoint = "mountpoint2";
    String legacyHost;
    String legacyMountpoint;
    String legacyPassword;
    uint16_t legacyPort = 2101;
    if (index == 0) {
        genericUser = "user";
        genericPassword = "password";
        genericMountpoint = "mountpoint";
        legacyHost = legacy.host;
        legacyMountpoint = legacy.mountpoint;
        legacyPassword = legacy.password;
        legacyPort = legacy.port;
    }

    if (hasServiceConfig) {
        endpoint.enabled = jsonBool(service, "server" + suffix + "_enabled", false);
        endpoint.host = endpointHost(service, index);
        endpoint.port = endpointPort(service, index, legacy.port);
        endpoint.mountpoint = jsonString(service, "mountpoint" + suffix,
            jsonString(service, "mp" + suffix,
                jsonString(service, genericMountpoint, String())));
        endpoint.username = jsonString(service, "username" + suffix,
            jsonString(service, "user" + suffix,
                jsonString(service, genericUser, "source")));
        endpoint.password = jsonString(service, "password" + suffix,
            jsonString(service, "pass" + suffix,
                jsonString(service, genericPassword, legacyPassword)));
        endpoint.version = static_cast<uint8_t>(service["ntrip_version" + suffix] | 1);
    } else {
        endpoint.enabled = index == 0 && !legacy.host.isEmpty();
        endpoint.host = legacyHost;
        endpoint.port = legacyPort;
        endpoint.mountpoint = legacyMountpoint;
        endpoint.username = "source";
        endpoint.password = legacyPassword;
        endpoint.version = 1;
    }
    normalizeEndpoint(endpoint);
}

void loadEndpoints() {
    DynamicJsonDocument serviceDoc(CONFIG_DOCUMENT_SIZE);
    const auto serialized = backendAgent.serviceConfigJson();
    const auto hasServiceConfig = deserializeJson(serviceDoc, serialized) == DeserializationError::Ok
        && serviceDoc.is<JsonObject>();
    const JsonObjectConst service = serviceDoc.as<JsonObjectConst>();

    const LegacyNtripConfig legacy = loadLegacyNtripConfig();

    for (uint8_t index = 0; index < NTRIP_SERVER_COUNT; ++index) {
        loadEndpoint(endpoints[index], index, service, hasServiceConfig, legacy);
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

bool waitForNtripResponse(Client &client, String *statusLine = nullptr) {
    String response;
    response.reserve(512);
    const uint32_t deadline = millis() + 10000UL;
    bool headerComplete = false;
    bool readFailed = false;
    while ((client.connected() || client.available() > 0) && millis() < deadline
        && response.length() < 4096 && !headerComplete && !readFailed) {
        while (client.available() > 0 && response.length() < 4096
            && !headerComplete && !readFailed) {
            const auto value = client.read();
            if (value < 0) {
                readFailed = true;
            } else {
                response += static_cast<char>(value);
                headerComplete = response.endsWith("\r\n\r\n");
            }
        }
        if (!headerComplete && !readFailed) delay(1);
    }
    if (statusLine) {
        const auto end = response.indexOf('\n');
        *statusLine = response.substring(0, end >= 0 ? end : 240);
        statusLine->trim();
        if (statusLine->isEmpty()) *statusLine = "No response from caster (timeout or closed connection)";
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
    const auto outbound = String(snapshot.lastGga.data()) + "\r\n";
    if (client.print(outbound) != outbound.length()) {
        Serial.println("[NTRIP ROVER] Loi ghi GGA len socket caster");
        roverLastGgaMs = millis();
        return;
    }
    Serial.printf("[NTRIP ROVER] GGA -> caster: %s\n", snapshot.lastGga.data());
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

    const auto user = endpoint.username.isEmpty() ? String("source") : endpoint.username;
    const auto auth = base64Encode(user + ":" + endpoint.password);
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

Client &activeNtripClient() {
    return clientFor(0);
}

bool sendEndpointRtcm(NtripEndpoint &endpoint, Client &client, const String &rtcmData) {
    if (rtcmData.isEmpty()) {
        if (endpoint.version == 2 && millis() - endpoint.lastKeepAliveMs >= 10000UL) {
            client.print("0\r\n\r\n");
            endpoint.lastKeepAliveMs = millis();
        }
        return false;
    }

    const auto payloadLength = rtcmData.length();
    auto sent = 0;
    if (endpoint.version == 2) {
        client.print(String(payloadLength, HEX) + "\r\n");
        sent = client.write(reinterpret_cast<const uint8_t *>(rtcmData.c_str()), payloadLength);
        client.print("\r\n");
    } else {
        sent = client.write(reinterpret_cast<const uint8_t *>(rtcmData.c_str()), payloadLength);
    }
    if (sent != payloadLength) return false;
    endpoint.bytesInWindow += static_cast<uint32_t>(sent);
    return true;
}

int bootstrapUM980() {
  sendUm980Command(nmeaCmdUnlog, 8, true, 20);
  sendUm980Command(rtcmSetBaudCom2, 21, false, 0);
  sendUm980Command(nmeaCmdSetBase, 25, true, 20);
  sendUm980Command(rtcm1084SetOutputCom2, 18, true, 20);
  sendUm980Command(rtcm1074SetOutputCom2, 18, true, 20);
  sendUm980Command(rtcm1006SetOutputCom2, 18, true, 20);
  sendUm980Command(rtcm1124SetOutputCom2, 18, true, 20);
  sendUm980Command(rtcm1087SetOutputCom2, 18, true, 20);
  sendUm980Command(rtcm1077SetOutputCom2, 18, true, 20);
  sendUm980Command(rtcm1127SetOutputCom2, 18, true, 20);
  logUm980Response();
  delay(20);

  // Send ephemeris output commands before saving the receiver configuration.
  for (const auto &command : UnicoreCommands::buildEphemerisOutputCommands("COM2")) {
    if (Serial1.write(command.data(), command.size()) != command.size()) {
      Serial.println("[UNICORE][ERROR] Khong gui duoc lenh bat ephemeris.");
      return -1;
    }
    Serial1.flush();
    delay(100);
  }

  sendUm980Command(cmdSaveConfig, 13, true, 20);
  return 0;
}

int bootstrapUblox() {
  GnssCmdBuilder::GnssOptions options;
  options.ports = {"UART1"};
  options.outputMode = GnssCmdBuilder::OutputMode::DiagnosticsRtcm;
  options.msmLevel = GnssCmdBuilder::MsmLevel::Both;

  const GnssCmdBuilder::Command outputConfig =
      GnssCmdBuilder::buildUbloxOutputConfigCommand(options);
  if (outputConfig.empty()) {
    Serial.println("[UBLOX][ERROR] Khong tao duoc lenh cau hinh output.");
    return -1;
  }

  Serial1.write(outputConfig.data(), outputConfig.size());
  Serial1.flush();
  delay(100);

  const GnssCmdBuilder::Command saveConfig = {
      0xB5, 0x62, 0x06, 0x09, 0x0D, 0x00,
      0x00, 0x00, 0x00, 0x00, 0xFF, 0xFF,
      0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
      0x03, 0x1D, 0xAB};
  Serial1.write(saveConfig.data(), saveConfig.size());
  Serial1.flush();

  Serial.println("[UBLOX] Da cau hinh output RTCM/NMEA tren UART1.");
  return 0;
}

GnssCmdBuilder::GnssSensorType detectGnssSensorType() {
  Serial.println("[GNSS] Cho receiver khoi dong 2000 ms truoc khi probe.");
  delay(2000);
    const std::array<uint32_t, 7> baudRates = {
        GNSS_BAUD, 38400, 9600, 19200, 57600, 230400, 460800
    };
  for (const uint32_t baud : baudRates) {
    Serial1.updateBaudRate(baud);
    delay(30);
    Serial.printf("[GNSS] Probe baud=%lu\n", static_cast<unsigned long>(baud));
    clearGnssInput();
    Serial1.write(ubxMonVerPoll.data(), ubxMonVerPoll.size());
    Serial1.flush();
    if (receiveUbxFrame(1000)) {
      Serial.printf("[GNSS] Da nhan dien u-blox qua UBX-MON-VER, baud=%lu.\n", static_cast<unsigned long>(baud));
      return GnssCmdBuilder::GnssSensorType::Ublox;
    }

    clearGnssInput();
    Serial1.print("VERSIONA\r\n");
    Serial1.flush();
    delay(50);
    if (receiveUnicoreIdentification(1000)) {
      Serial.printf("[GNSS] Da nhan dien Unicore qua lenh VERSIONA, baud=%lu.\n", static_cast<unsigned long>(baud));
      return GnssCmdBuilder::GnssSensorType::Unicore;
    }
  }

  Serial1.updateBaudRate(GNSS_BAUD);
  delay(30);
  clearGnssInput();
  Serial.printf("[GNSS] Thu lai VERSIONA tai baud=%lu sau khi receiver da khoi dong.\n",
                static_cast<unsigned long>(GNSS_BAUD));
  Serial1.print("VERSIONA\r\n");
  Serial1.flush();
  if (receiveUnicoreIdentification(1500)) return GnssCmdBuilder::GnssSensorType::Unicore;
  Serial.println("[GNSS][ERROR] Khong the nhan dien chip GNSS.");
  return GnssCmdBuilder::GnssSensorType::Invalid;
}

int setupNTRIP() {
    for (uint8_t index = 0; index < NTRIP_SERVER_COUNT; ++index) stopEndpoint(index);
    loadEndpoints();
    return 0;
}

int connectNTRIP() {
    loadEndpoints();
    auto connected = 0;
    for (uint8_t index = 0; index < NTRIP_SERVER_COUNT; ++index) {
        if (connectEndpoint(index)) ++connected;
    }
    return connected > 0 ? 0 : -1;
}

int loopNTRIP(String &rtcmData) {
    if (roverSessionActive) return 504;

    auto returnCode = NTRIP_MODE;
    auto anyConnected = false;
    auto anySent = false;

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
                connectEndpoint(index);
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
                    const String &password, String mountpoint, const uint8_t version) {
    if (host.isEmpty() || port == 0 || mountpoint.isEmpty()
        || !safeNtripField(host) || !safeNtripField(username)
        || !safeNtripField(password) || !safeNtripField(mountpoint)) return false;
    while (mountpoint.startsWith("/")) mountpoint.remove(0, 1);
    if (mountpoint.isEmpty()) return false;

    // The temporary rover reuses source server 1's client and modem mux 0.
    // Close that client before opening a receive-only correction stream.
    roverBytesReceived = 0;
    roverPacketsReceived = 0;
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

    const auto user = username.isEmpty() ? String("source") : username;
    const auto auth = base64Encode(user + ":" + password);
    String request;
    if (version == 2) {
        request = "GET /" + mountpoint + " HTTP/1.1\r\n"
                  "Host: " + host + ":" + String(port) + "\r\n"
                  "Ntrip-Version: Ntrip/2.0\r\n"
                  "User-Agent: NTRIP ESP32-Agent/" + String(AGENT_VERSION) + "\r\n"
                  "Authorization: Basic " + auth + "\r\n"
                  "Accept: */*\r\n"
                  "Connection: Keep-Alive\r\n\r\n";
    } else {
        request = "GET /" + mountpoint + " HTTP/1.0\r\n"
                  "User-Agent: NTRIP ESP32-Agent/" + String(AGENT_VERSION) + "\r\n"
                  "Authorization: Basic " + auth + "\r\n"
                  "Accept: */*\r\n"
                  "Connection: close\r\n\r\n";
    }
    client.print(request);

    if (!waitForNtripResponse(client)) {
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
        roverSessionActive = false;
        roverSessionAuthenticated = false;
        return 504;
    }
    sendRoverGgaIfAvailable(client);
    if (client.available() <= 0) return 200;

    std::array<uint8_t, 512> buffer{};
    if (!rtcmBufferMutex
        || xSemaphoreTake(rtcmBufferMutex, pdMS_TO_TICKS(MUTEX_TIMEOUT_MS)) != pdTRUE) {
        return 200;
    }
    const auto available = client.available();
    const auto bytesToRead = min(static_cast<size_t>(available), sizeof(buffer));
    const auto bytesRead = client.read(buffer.data(), bytesToRead);
    if (bytesRead > 0) {
        Serial1.write(buffer.data(), static_cast<size_t>(bytesRead));
        roverBytesReceived += static_cast<uint32_t>(bytesRead);
        ++roverPacketsReceived;
    }
    xSemaphoreGive(rtcmBufferMutex);
    return bytesRead > 0 ? bytesRead : 200;
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
