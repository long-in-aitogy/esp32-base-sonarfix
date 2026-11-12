#pragma once
#include <cstddef>
#include <cstdint>

namespace UbxSatellites {
constexpr size_t MAX_SATELLITES = 128;
constexpr size_t MAX_PAYLOAD = 8 + 12 * MAX_SATELLITES;

inline bool valid(const uint8_t *p, size_t size) {
    if (size < 8 || p[4] != 1 || p[5] > MAX_SATELLITES || size != 8 + size_t(p[5]) * 12) return false;
    for (size_t i = 8; i < size; i += 12) {
        if (p[i] > 7 || p[i + 1] == 0) return false;
        if (p[i] == 6 && p[i + 1] == 255) continue; // Unknown GLONASS slot.
        for (size_t j = 8; j < i; j += 12)
            if (p[i] == p[j] && p[i + 1] == p[j + 1]) return false;
    }
    return true;
}
}
