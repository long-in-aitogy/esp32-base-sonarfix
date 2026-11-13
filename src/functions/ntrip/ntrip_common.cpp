#define NTRIP_HANDLER_IP_CODE

#include "functions/ntrip/ntrip_common.h"

#include "Prog_Config.h"
#include "functions/backend/Backend_Agent.h"
#include "functions/backend/Backend_Agent_Internal.h"
#include "hardware/Sim_handler.h"
#include "hardware/Wifi_handler.h"

#include <ArduinoJson.h>
#include <Preferences.h>
#include <array>
#include <cstdlib>
#include <cstring>

extern Preferences prefs;
extern TinyGsm modem;

/** @brief Implements jsonBool. */
bool jsonBool(JsonObjectConst object, const String &key, bool fallback = false)
{
    const JsonVariantConst value = object[key.c_str()];
    if (value.isNull())
        return fallback;
    if (value.is<bool>())
        return value.as<bool>();
    if (value.is<const char *>())
    {
        const String text = value.as<String>();
        if (text.equalsIgnoreCase("true") || text == "1" || text.equalsIgnoreCase("on"))
            return true;
        if (text.equalsIgnoreCase("false") || text == "0" || text.equalsIgnoreCase("off"))
            return false;
    }
    return value.as<int>() != 0;
}

/** @brief Implements jsonString. */
String jsonString(JsonObjectConst object, const String &key, const String &fallback = String())
{
    const JsonVariantConst value = object[key.c_str()];
    return value.isNull() ? fallback : value.as<String>();
}

/** @brief Implements safeNtripField. */
bool safeNtripField(const String &value)
{
    return value.indexOf('\r') < 0 && value.indexOf('\n') < 0;
}

struct LocalNtripConfig
{
    String host;
    String mountpoint;
    String password;
    uint16_t port = NTRIP_CASTER_PORT;
};

/** @brief Implements loadLocalNtripConfig. */
LocalNtripConfig loadLocalNtripConfig()
{
    LocalNtripConfig legacy;
    prefs.begin("myPrefs", true);
    legacy.host = prefs.getString("NTRIP_SERVER", String(NTRIP_CASTER_ADDRESS));
    legacy.port = prefs.getUShort("NTRIP_PORT", NTRIP_CASTER_PORT);
    legacy.mountpoint = prefs.getString("NTRIP_MPT", String(NTRIP_MOUNTPOINT));
    legacy.password = prefs.getString("NT_AUTH_BS", String(NTRIP_AUTH_BASE_STATION));
    prefs.end();
    return legacy;
}

/** @brief Implements endpointHost. */
String endpointHost(JsonObjectConst service, uint8_t index)
{
    const auto suffix = String(index + 1);
    const auto generic = index == 0 ? "ip" : "ip2";
    const auto fallback = index == 0 ? jsonString(service, "host", String()) : String();
    return jsonString(service, "serverhost" + suffix,
                      jsonString(service, "server" + suffix + "_host",
                                 jsonString(service, "host" + suffix,
                                            jsonString(service, generic, fallback))));
}

/** @brief Implements endpointPort. */
uint16_t endpointPort(JsonObjectConst service, uint8_t index, uint16_t legacyPort)
{
    const auto suffix = String(index + 1);
    const auto generic = index == 0 ? "port" : "port2";
    const uint16_t fallback = index == 0 ? legacyPort : 2101;
    JsonVariantConst value = service["port" + suffix];
    if (value.isNull()) value = service["serverport" + suffix];
    if (value.isNull()) value = service[generic];
    if (value.isNull()) return fallback;
    long port = 0;
    if (value.is<int>())
        port = value.as<int>();
    else if (value.is<const char *>())
    {
        const char *text = value.as<const char *>();
        char *end = nullptr;
        port = std::strtol(text, &end, 10);
        if (end == text || *end != '\0') return 0;
    }
    return port >= 1 && port <= 65535 ? static_cast<uint16_t>(port) : 0;
}

/** @brief Implements base64Encode. */
String base64Encode(const String &plain)
{
    static constexpr char alphabet[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    String encoded;
    encoded.reserve(((plain.length() + 2) / 3) * 4);
    for (size_t i = 0; i < plain.length(); i += 3)
    {
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

namespace ntrip_common
{
    constexpr size_t CONFIG_DOCUMENT_SIZE = BackendAgentInternal::CONFIG_DOCUMENT_SIZE;
    WiFiClient wifiNtripClient1;
    WiFiClient wifiNtripClient2;
    TinyGsmClient gsmNtripClient1(modem, 0);
    TinyGsmClient gsmNtripClient2(modem, 2);
    NtripEndpoint &endpointFor(uint8_t index)
    {
        static std::array<NtripEndpoint, NTRIP_SERVER_COUNT> endpoints;
        return endpoints[index];
    }

    Client &clientFor(uint8_t index)
    {
        if (index == 0)
        {
            return isWifiConnection()
                       ? static_cast<Client &>(wifiNtripClient1)
                       : static_cast<Client &>(gsmNtripClient1);
        }
        return isWifiConnection()
                   ? static_cast<Client &>(wifiNtripClient2)
                   : static_cast<Client &>(gsmNtripClient2);
    }

/** @brief Implements clearEndpointState. */
    void clearEndpointState(NtripEndpoint &endpoint)
    {
        endpoint.authenticated = false;
        endpoint.bytesInWindow = 0;
        endpoint.bytesPerSecond = 0;
        endpoint.windowStartedMs = millis();
        endpoint.lastKeepAliveMs = endpoint.windowStartedMs;
    }

/** @brief Implements normalizeEndpoint. */
    void normalizeEndpoint(NtripEndpoint &endpoint)
    {
        while (endpoint.mountpoint.startsWith("/"))
            endpoint.mountpoint.remove(0, 1);
        endpoint.enabled = endpoint.enabled && !endpoint.host.isEmpty() && !endpoint.mountpoint.isEmpty() && endpoint.port > 0 && safeNtripField(endpoint.host) && safeNtripField(endpoint.mountpoint) && safeNtripField(endpoint.username) && safeNtripField(endpoint.password);
    }

/** @brief Implements loadEndpoint. */
    void loadEndpoint(NtripEndpoint &endpoint, uint8_t index, JsonObjectConst service,
                      bool hasServiceConfig, const LocalNtripConfig &legacy)
    {
        const auto suffix = String(index + 1);
        auto genericUser = "user2";
        auto genericPassword = "password2";
        auto genericMountpoint = "mountpoint2";
        String legacyHost;
        String legacyMountpoint;
        String legacyPassword;
        uint16_t legacyPort = 2101;
        if (index == 0)
        {
            genericUser = "user";
            genericPassword = "password";
            genericMountpoint = "mountpoint";
            legacyHost = legacy.host;
            legacyMountpoint = legacy.mountpoint;
            legacyPassword = legacy.password;
            legacyPort = legacy.port;
        }

        if (hasServiceConfig)
        {
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
        }
        else
        {
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

/** @brief Implements loadEndpoints. */
    void loadEndpoints()
    {
        DynamicJsonDocument serviceDoc(CONFIG_DOCUMENT_SIZE);
        const auto serialized = backendAgent.serviceConfigJson();
        const auto parseError = deserializeJson(serviceDoc, serialized);
        if (parseError == DeserializationError::NoMemory)
        {
            for (uint8_t index = 0; index < NTRIP_SERVER_COUNT; ++index)
                endpointFor(index).enabled = false;
            return;
        }
        const auto hasServiceConfig = parseError == DeserializationError::Ok && serviceDoc.is<JsonObject>();
        const JsonObjectConst service = serviceDoc.as<JsonObjectConst>();

        const LocalNtripConfig legacy = loadLocalNtripConfig();

        for (uint8_t index = 0; index < NTRIP_SERVER_COUNT; ++index)
        {
            loadEndpoint(endpointFor(index), index, service, hasServiceConfig, legacy);
        }
    }

/** @brief Implements streamActive. */
    bool streamActive(uint8_t index)
    {
        if (index >= NTRIP_SERVER_COUNT || backendDeviceLocked(index + 1) || !backendLicenseValid() || !backendDeviceProvisioned() || !backendBaseStartupConfigured())
            return false;
        DynamicJsonDocument serviceDoc(CONFIG_DOCUMENT_SIZE);
        const auto parseError = deserializeJson(serviceDoc, backendAgent.serviceConfigJson());
        if (parseError == DeserializationError::NoMemory)
            return false;
        if (parseError != DeserializationError::Ok || !serviceDoc.is<JsonObject>())
        {
            return index == 0;
        }
        return BackendAgent::effectiveStreamActive(
            serviceDoc.as<JsonObjectConst>(), index + 1, backendControlPlaneFailOpen());
    }

/** @brief Implements stopEndpoint. */
    void stopEndpoint(uint8_t index)
    {
        clientFor(index).stop();
        clearEndpointState(endpointFor(index));
    }

/** @brief Implements waitForNtripResponse. */
    bool waitForNtripResponse(Client &client, String *statusLine, String *selectedMountpoint)
    {
        String response;
        response.reserve(512);
        const uint32_t started = millis();
        bool headerComplete = false;
        bool readFailed = false;
        while ((client.connected() || client.available() > 0) && millis() - started < 10000UL && response.length() < 4096 && !headerComplete && !readFailed)
        {
            while (client.available() > 0 && response.length() < 4096 && !headerComplete && !readFailed)
            {
                const auto value = client.read();
                if (value < 0)
                {
                    readFailed = true;
                }
                else
                {
                    response += static_cast<char>(value);
                    headerComplete = response.endsWith("\r\n\r\n") || response == "ICY 200 OK\r\n";
                }
            }
            if (!headerComplete && !readFailed)
                delay(1);
        }
        if (statusLine)
        {
            const auto end = response.indexOf('\n');
            *statusLine = response.substring(0, end >= 0 ? end : 240);
            statusLine->trim();
            if (statusLine->isEmpty())
                *statusLine = "No response from caster (timeout or closed connection)";
        }
        const bool accepted = headerComplete && !readFailed
            && (response == "ICY 200 OK\r\n"
                || response.indexOf("HTTP/1.1 200 ") == 0 || response.indexOf("HTTP/1.1 200\r\n") == 0
                || response.indexOf("HTTP/1.0 200 ") == 0 || response.indexOf("HTTP/1.0 200\r\n") == 0);
        if (!selectedMountpoint) 
            return accepted;
        selectedMountpoint->clear();
        if (!accepted || !response.endsWith("\r\n\r\n"))
            return accepted;
        bool found = false;
        int start = response.indexOf('\n') + 1;
        while (start > 0)
        {
            const int end = response.indexOf('\r', start);
            if (end <= start)
                break;
            const int colon = response.indexOf(':', start);
            if (colon > start && colon < end
                && response.substring(start, colon).equalsIgnoreCase("X-NTRIP-Selected-Mountpoint"))
            {
                if (found)
                {
                    selectedMountpoint->clear();
                    return false;
                }
                *selectedMountpoint = response.substring(colon + 1, end);
                selectedMountpoint->trim();
                found = true;
            }
            start = end + 2;
        }
        return accepted;
    }

} // namespace ntrip_common
