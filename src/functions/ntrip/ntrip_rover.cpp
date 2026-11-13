#define NTRIP_HANDLER_IP_CODE

#include "functions/ntrip/ntrip_rover.h"
#include "functions/ntrip/unicore_bootstrap_cmds.h"

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

using namespace ntrip_common;

namespace
{
    struct RoverSession
    {
        Vn2000Session datum;
        bool active = false;
        bool authenticated = false;
        uint32_t lastGgaMs = 0;
        uint32_t bytesReceived = 0;
        uint32_t bytesWritten = 0;
        uint32_t packetsReceived = 0;
        uint32_t lastDiagnosticMs = 0;
        const char *lastError = "CORS rover connection lost";
    };

    RoverSession &roverSession()
    {
        static RoverSession session;
        return session;
    }
}

/** @brief Implements sendRoverGgaIfAvailable. */
void sendRoverGgaIfAvailable(Client &client, const bool force = false)
{
    if (!force && millis() - roverSession().lastGgaMs < 5000UL)
        return;
    const GnssTelemetrySnapshot snapshot = getGnssTelemetrySnapshot();
    if (snapshot.lastGga[0] == '\0' || snapshot.lastGgaMs == 0 || millis() - snapshot.lastGgaMs > 3000UL)
    {
        if (force || millis() - roverSession().lastGgaMs >= 5000UL)
        {
            Serial.println("[NTRIP ROVER] Chua co GGA moi tu UART GNSS; chua gui GGA len caster");
            roverSession().lastGgaMs = millis();
        }
        return;
    }
    const auto outbound = String(snapshot.lastGga.data()) + "\r\n";
    if (client.print(outbound) != outbound.length())
    {
        Serial.println("[NTRIP ROVER] Loi ghi GGA len socket caster");
        roverSession().lastGgaMs = millis();
        return;
    }
    Serial.printf("[NTRIP ROVER] GGA -> caster: %s\n", snapshot.lastGga.data());
    roverSession().lastGgaMs = millis();
}

String buildNtripRoverRequest(const String &host, const uint16_t port, const String &user,
                              const String &password, const String &mountpoint,
                              const NtripRoverOptions &options)
{
    const auto auth = base64Encode(user + ":" + password);
    String agent = "NTRIP ESP32-Agent/" + String(AGENT_VERSION);
    if (!options.receiverId.isEmpty())
        agent += "/" + options.receiverId;

    String request;
    if (options.version == 2)
    {
        request = "GET /" + mountpoint + " HTTP/1.1\r\n"
                                         "Host: " +
                  host + ":" + String(port) + "\r\n"
                                              "Ntrip-Version: Ntrip/2.0\r\n"
                                              "User-Agent: " +
                  agent + "\r\n"
                          "Authorization: Basic " +
                  auth + "\r\n"
                         "Accept: */*\r\n"
                         "Connection: Keep-Alive\r\n\r\n";
    }
    else
    {
        request = "GET /" + mountpoint + " HTTP/1.0\r\n"
                                         "User-Agent: " +
                  agent + "\r\n"
                          "Authorization: Basic " +
                  auth + "\r\n"
                         "Accept: */*\r\n"
                         "Connection: close\r\n\r\n";
    }

    const GnssTelemetrySnapshot snapshot = getGnssTelemetrySnapshot();
    if (snapshot.lastGga[0] != '\0' && snapshot.lastGgaMs != 0
        && millis() - snapshot.lastGgaMs <= 3000UL)
    {
        String gga = snapshot.lastGga.data();
        gga.trim();
        if (!gga.isEmpty() && gga.indexOf('\r') < 0 && gga.indexOf('\n') < 0)
        {
            request.remove(request.length() - 2);
            request += "Ntrip-GGA: " + gga + "\r\n\r\n";
        }
    }
    if (options.selectedMountpoint)
    {
        request.remove(request.length() - 2);
        request += "X-NTRIP-Report-Selected: 1\r\n\r\n";
    }
    return request;
}

bool sendNtripRoverRequest(Client &client, const String &request,
                           String *selectedMountpoint)
{
    if (client.print(request) != request.length())
    {
        client.stop();
        roverSession().active = false;
        roverSession().lastError = "incomplete NTRIP request write";
        return false;
    }

    String responseLine;
    if (!waitForNtripResponse(client, &responseLine, selectedMountpoint))
    {
        for (const char *reason : {"ERROR - NO STATION WITHIN 20 KM",
                                   "ERROR - FIXED STATION IN RANGE UNAVAILABLE",
                                   "ERROR - FIXED STATION CATALOG UNAVAILABLE",
                                   "ERROR - AUTONEAREST NOT ENABLED"})
        {
            if (responseLine == reason)
            {
                roverSession().lastError = reason;
                break;
            }
        }
        client.stop();
        roverSession().active = false;
        return false;
    }
    if (selectedMountpoint && (selectedMountpoint->isEmpty() || !safeNtripField(*selectedMountpoint)))
    {
        roverSession().lastError = "Caster did not confirm the selected mountpoint";
        client.stop();
        roverSession().active = false;
        return false;
    }
    return true;
}

/** @brief Implements startNtripRover. */
bool startNtripRover(const String &host, const uint16_t port, const String &username,
                     const String &password, String mountpoint,
                     const NtripRoverOptions &options)
{
    if (options.selectedMountpoint)
        options.selectedMountpoint->clear();
    roverSession().lastError = "cannot connect to CORS rover mountpoint";
    if (host.isEmpty() || port == 0 || mountpoint.isEmpty() || !safeNtripField(host) || !safeNtripField(username) || !safeNtripField(password) || !safeNtripField(mountpoint) || !safeNtripField(options.receiverId))
        return false;
    while (mountpoint.startsWith("/"))
        mountpoint.remove(0, 1);
    if (mountpoint.isEmpty())
        return false;

    // The temporary rover reuses source server 1's client and modem mux 0.
    // Close that client before opening a receive-only correction stream.
    roverSession().datum.reset();
    roverSession().bytesReceived = 0;
    roverSession().bytesWritten = 0;
    roverSession().packetsReceived = 0;
    roverSession().lastDiagnosticMs = millis();
    roverSession().active = true;
    roverSession().authenticated = false;
    roverSession().lastGgaMs = 0;
    Client &client = clientFor(0);
    client.stop();
    client.setTimeout(3000);
    if (!client.connect(host.c_str(), port))
    {
        roverSession().active = false;
        return false;
    }

    const auto user = username.isEmpty() ? String("source") : username;
    const auto request = buildNtripRoverRequest(host, port, user, password, mountpoint, options);
    if (!sendNtripRoverRequest(client, request, options.selectedMountpoint))
        return false;
    roverSession().authenticated = true;
    roverSession().lastError = "CORS rover connection lost";
    sendRoverGgaIfAvailable(client, true);
    Serial.println("[NTRIP ROVER] Da ket noi CORS " + host + ":" + String(port) + "/" + mountpoint);
    return true;
}

/** @brief Implements loopNtripRover. */
int loopNtripRover()
{
    if (!roverSession().active || !roverSession().authenticated)
        return 504;
    Client &client = clientFor(0);
    if (!client.connected())
    {
        Serial.printf("[NTRIP ROVER][ERROR] CORS socket closed; cors_rx=%lu B; uart_tx=%lu B; rtcm_frames=%lu\n",
                      static_cast<unsigned long>(roverSession().bytesReceived),
                      static_cast<unsigned long>(roverSession().bytesWritten),
                      static_cast<unsigned long>(roverSession().datum.validFrames()));
        roverSession().active = false;
        roverSession().authenticated = false;
        return 504;
    }
    sendRoverGgaIfAvailable(client);
    if (millis() - roverSession().lastDiagnosticMs >= 5000UL)
    {
        roverSession().lastDiagnosticMs = millis();
        const auto snapshot = getGnssTelemetrySnapshot();
        Serial.printf("[NTRIP ROVER][DATA] cors_rx=%lu B; uart_tx=%lu B; rtcm_frames=%lu; fix=%s\n",
                      static_cast<unsigned long>(roverSession().bytesReceived),
                      static_cast<unsigned long>(roverSession().bytesWritten),
                      static_cast<unsigned long>(roverSession().datum.validFrames()), snapshot.fixStatus.data());
    }
    if (client.available() <= 0)
        return 200;

    std::array<uint8_t, 512> buffer{};
    if (!rtcmBufferMutex || xSemaphoreTake(rtcmBufferMutex, pdMS_TO_TICKS(MUTEX_TIMEOUT_MS)) != pdTRUE)
    {
        return 200;
    }
    const auto available = client.available();
    const auto bytesToRead = min(static_cast<size_t>(available), sizeof(buffer));
    const auto bytesRead = client.read(buffer.data(), bytesToRead);
    if (bytesRead > 0)
    {
        roverSession().datum.feed(buffer.data(), static_cast<size_t>(bytesRead));
        const size_t written = Serial1.write(buffer.data(), static_cast<size_t>(bytesRead));
        roverSession().bytesReceived += static_cast<uint32_t>(bytesRead);
        roverSession().bytesWritten += static_cast<uint32_t>(written);
        ++roverSession().packetsReceived;
        if (written != static_cast<size_t>(bytesRead))
        {
            roverSession().lastError = "GNSS UART did not accept all CORS bytes";
            Serial.printf("[NTRIP ROVER][ERROR] UART accepted %u/%u bytes\n",
                          static_cast<unsigned>(written), static_cast<unsigned>(bytesRead));
            xSemaphoreGive(rtcmBufferMutex);
            return 504;
        }
    }
    xSemaphoreGive(rtcmBufferMutex);
    // Return status, not byte count: a valid 504-byte read is not a disconnect.
    return 200;
}

/** @brief Implements stopNtripRover. */
void stopNtripRover()
{
    if (roverSession().active)
        clientFor(0).stop();
    clearNtripRoverSession();
}

void clearNtripRoverSession()
{
    auto &session = roverSession();
    session.active = false;
    session.authenticated = false;
    session.lastGgaMs = 0;
}

bool ntripRoverSessionStarted() { return roverSession().active; }

/** @brief Implements ntripRoverActive. */
bool ntripRoverActive()
{
    return roverSession().active && roverSession().authenticated;
}

/** @brief Implements ntripRoverBytesReceived. */
uint32_t ntripRoverBytesReceived() { return roverSession().bytesReceived; }
/** @brief Implements ntripRoverPacketsReceived. */
uint32_t ntripRoverPacketsReceived() { return roverSession().packetsReceived; }

const char *ntripRoverLastError() { return roverSession().lastError; }

Vn2000Datum ntripRoverDatum() { return roverSession().datum.datum(); }
