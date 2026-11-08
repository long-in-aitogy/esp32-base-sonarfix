#include "functions/ntrip/ntrip_common.h"
#include "hardware/Sim_handler.h"
#include "hardware/Wifi_handler.h"

extern TinyGsm modem;

namespace ntrip_common {
bool safeNtripField(const String &value) {
    return value.indexOf('\r') < 0 && value.indexOf('\n') < 0;
}

WiFiClient wifiNtripClient1;
WiFiClient wifiNtripClient2;
TinyGsmClient gsmNtripClient1(modem, 0);
TinyGsmClient gsmNtripClient2(modem, 2);
bool roverSessionActive = false;
bool roverSessionAuthenticated = false;
uint32_t roverLastGgaMs = 0;
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

bool waitForNtripResponse(Client &client, String *statusLine, bool rover) {
    String response;
    response.reserve(512);
    const uint32_t started = millis();
    while ((client.connected() || client.available() > 0) && millis() - started < 10000UL && response.length() < 4096) {
        while (client.available() > 0 && response.length() < 4096) {
            const int value = client.read();
            if (value < 0) break;
            response += static_cast<char>(value);
            if (response.endsWith("\r\n\r\n") || (rover && response == "ICY 200 OK\r\n")) break;
        }
        if (response.indexOf("\r\n\r\n") >= 0 || (rover && response == "ICY 200 OK\r\n")) break;
        delay(1);
    }
    if (statusLine) {
        const int end = response.indexOf('\n');
        *statusLine = response.substring(0, end >= 0 ? end : 240);
        statusLine->trim();
        if (statusLine->isEmpty()) *statusLine = "No response from caster (timeout or closed connection)";
    }
    return response.indexOf("ICY 200 OK") >= 0
        || response.indexOf("HTTP/1.1 200 OK") >= 0
        || response.indexOf("HTTP/1.0 200 OK") >= 0;
}

} // namespace ntrip_common
