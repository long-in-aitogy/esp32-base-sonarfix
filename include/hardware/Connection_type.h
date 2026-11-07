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
extern ConnectionType connectionType;

void loadConnectionTypeFromPrefs();

/** @brief Implements isWifiConnection. */
inline bool isWifiConnection()
{
    return connectionType == ConnectionType::WIFI;
}

/** @brief Implements isGsmConnection. */
inline bool isGsmConnection()
{
    return connectionType == ConnectionType::GSM;
}

#endif