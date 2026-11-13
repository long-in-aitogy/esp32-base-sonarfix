#pragma once
#include <Arduino.h>
#include <algorithm>

inline bool validWifiCharacters(const String &value) {
    return std::all_of(value.begin(), value.end(), [](char character) {
        const auto byte = static_cast<uint8_t>(character);
        return byte >= 32 && byte != 127;
    });
}
inline bool validWifiSsid(const String &ssid) {
    return !ssid.isEmpty() && ssid.length() <= 32 && validWifiCharacters(ssid);
}
inline bool validWifiPassword(const String &password) {
    if (password.isEmpty()) return true; // Only explicitly selected open networks.
    return password.length() >= 8 && password.length() <= 63 && validWifiCharacters(password);
}
