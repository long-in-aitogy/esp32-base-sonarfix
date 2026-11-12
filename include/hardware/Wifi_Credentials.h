#pragma once
#include <Arduino.h>

inline bool validWifiSsid(const String &ssid) {
    if (ssid.isEmpty() || ssid.length() > 32) return false;
    for (size_t i = 0; i < ssid.length(); ++i)
        if (static_cast<uint8_t>(ssid[i]) < 32 || ssid[i] == 127) return false;
    return true;
}
inline bool validWifiPassword(const String &password) {
    if (password.isEmpty()) return true; // Only explicitly selected open networks.
    if (password.length() < 8 || password.length() > 63) return false;
    for (size_t i = 0; i < password.length(); ++i)
        if (static_cast<uint8_t>(password[i]) < 32 || password[i] == 127) return false;
    return true;
}
