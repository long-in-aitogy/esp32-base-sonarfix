#pragma once
#include <cstddef>
#include <cstdint>

// Bounded UBX reply reader for configuration exchanges, including checksum.
struct UbxReply {
    uint8_t frame[256] = {};
    size_t used = 0;
    size_t expected = 0;
    size_t length = 0;

    bool feed(uint8_t byte) {
        if (used == 0) {
            if (byte == 0xB5) frame[used++] = byte;
            return false;
        }
        if (used == 1 && byte != 0x62) {
            used = byte == 0xB5 ? 1 : 0;
            return false;
        }
        frame[used++] = byte;
        if (used == 6) {
            expected = 8 + size_t(frame[4]) + (size_t(frame[5]) << 8);
            if (expected > sizeof(frame)) used = 0;
        }
        if (used < 8 || used != expected) return false;
        length = used;
        used = 0;
        uint8_t a = 0, b = 0;
        for (size_t i = 2; i < length - 2; ++i) { a += frame[i]; b += a; }
        return a == frame[length - 2] && b == frame[length - 1];
    }
};
