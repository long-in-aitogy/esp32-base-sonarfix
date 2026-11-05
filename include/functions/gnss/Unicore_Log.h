#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>

// N4 MODE uses XOR including '#'; ASCII data logs use CRC32 excluding '#'.
inline bool validUnicoreLogChecksum(const char *line, size_t length) {
    if (!line || length < 4 || line[0] != '#') return false;
    size_t star = length;
    while (star > 0 && line[star - 1] != '*') --star;
    if (star == 0) return false;
    --star;
    const size_t digits = length - star - 1;
    if (digits != 2 && digits != 8) return false;
    uint32_t expected = 0;
    for (size_t i = star + 1; i < length; ++i) {
        const char c = line[i];
        const int value = c >= '0' && c <= '9' ? c - '0'
            : c >= 'A' && c <= 'F' ? c - 'A' + 10
            : c >= 'a' && c <= 'f' ? c - 'a' + 10 : -1;
        if (value < 0) return false;
        expected = (expected << 4) | static_cast<uint32_t>(value);
    }
    uint32_t checksum = 0;
    for (size_t i = digits == 2 ? 0 : 1; i < star; ++i) {
        checksum ^= static_cast<uint8_t>(line[i]);
        if (digits == 8)
            for (uint8_t bit = 0; bit < 8; ++bit)
                checksum = (checksum >> 1) ^ (checksum & 1 ? 0xedb88320U : 0U);
    }
    return checksum == expected;
}
