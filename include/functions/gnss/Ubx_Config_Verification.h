#pragma once
#include "functions/gnss/Ubx_Base_Status.h"
#include <array>

namespace UbxConfigVerification {
constexpr size_t MAX_KEYS = 40; // A U1 VALGET reply fits the existing 256-byte reader.
inline uint32_t enabledKey(unsigned port) {
    constexpr std::array<uint32_t, 5> keys = {0x10510003, 0x10520005, 0x10530005, 0x10650001, 0x10640006};
    return port < keys.size() ? keys[port] : 0;
}

inline bool validExpected(const uint8_t *records, size_t length) {
    if (!records || !length || length % 5 || length / 5 > MAX_KEYS) return false;
    for (size_t i = 0; i < length; i += 5) {
        const uint32_t key = UbxBaseStatus::u32(records + i);
        // Only exact one-byte output protocol/rate keys; no wildcard queries.
        const bool enabled = key == enabledKey(0) || key == enabledKey(1) || key == enabledKey(2) || key == enabledKey(3) || key == enabledKey(4);
        if ((!enabled && key >> 16 != 0x2091 && key >> 16 != 0x1072 && key >> 16 != 0x1074
             && key >> 16 != 0x1076 && key >> 16 != 0x1078 && key >> 16 != 0x107A)
            || (key & 0xFFFF) == 0xFFFF || records[i + 4] > 1) return false;
        for (size_t j = 0; j < i; j += 5)
            if (UbxBaseStatus::u32(records + j) == key) return false;
    }
    return true;
}

inline bool fixedMatches(const uint8_t *expected, const uint8_t *actual, size_t length) {
    if (!expected || !actual || length != 40 || expected[2] != 2 || expected[3] != 1) return false;
    if (actual[2] != 2 || actual[3] != 1) return false;
    // Compare combined coordinates: equivalent integer/HP encodings are valid.
    // One quantization step tolerates decimal-vs-binary rounding on restoration.
    for (size_t i = 0; i < 3; ++i) {
        if (UbxBaseStatus::hp(actual[16 + i]) < -99 || UbxBaseStatus::hp(actual[16 + i]) > 99) return false;
        const int64_t wanted = int64_t(UbxBaseStatus::i32(expected + 4 + i * 4)) * 100 + UbxBaseStatus::hp(expected[16 + i]);
        const int64_t got = int64_t(UbxBaseStatus::i32(actual + 4 + i * 4)) * 100 + UbxBaseStatus::hp(actual[16 + i]);
        if (got - wanted < -1 || got - wanted > 1) return false;
    }
    const int64_t accuracyDelta = int64_t(UbxBaseStatus::u32(actual + 20)) - UbxBaseStatus::u32(expected + 20);
    return accuracyDelta >= -1 && accuracyDelta <= 1;
}

inline bool outputValues(const uint8_t *expected, size_t length,
                         const uint8_t *payload, size_t payloadLength, uint8_t *values) {
    if (!validExpected(expected, length) || !payload || !values || payloadLength != length + 4
        || payload[0] != 1 || payload[1] != 0 || payload[2] || payload[3]) return false;
    // Match by key rather than relying on response order. Missing/duplicate keys fail closed.
    for (size_t i = 0; i < length; i += 5) {
        const uint32_t key = UbxBaseStatus::u32(expected + i);
        size_t found = 0;
        for (size_t j = 4; j < payloadLength; j += 5) {
            if (UbxBaseStatus::u32(payload + j) != key) continue;
            values[i / 5] = payload[j + 4];
            ++found;
        }
        if (found != 1) return false;
    }
    return true;
}
} // namespace UbxConfigVerification
