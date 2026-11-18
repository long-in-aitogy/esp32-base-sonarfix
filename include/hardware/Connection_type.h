#ifndef CONNECTION_TYPE_H
#define CONNECTION_TYPE_H

#include <Arduino.h>

enum class ConnectionType : uint8_t
{
    WIFI,
    GSM,
};

// Active transport. Loaded from CONNECTION_TYPE at boot; a temporary Wi-Fi
// fallback changes this value without overwriting the saved SIM preference.
ConnectionType &activeConnectionType();

void loadConnectionTypeFromPrefs();

/** @brief Implements isWifiConnection. */
inline bool isWifiConnection()
{
    return activeConnectionType() == ConnectionType::WIFI;
}

/** @brief Implements isGsmConnection. */
inline bool isGsmConnection()
{
    return activeConnectionType() == ConnectionType::GSM;
}

#endif