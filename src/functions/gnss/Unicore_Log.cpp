#include "functions/gnss/Unicore_Log.h"

// N4 MODE uses XOR including '#'; ASCII data logs use CRC32 excluding '#'.
namespace unicore_log_detail
{

    inline int hexDigit(char c)
    {
        if (c >= '0' && c <= '9')
            return c - '0';
        if (c >= 'A' && c <= 'F')
            return c - 'A' + 10;
        if (c >= 'a' && c <= 'f')
            return c - 'a' + 10;
        return -1;
    }

    inline bool parseExpectedChecksum(const char *line, size_t star, size_t length,
                                      uint32_t &expected)
    {
        for (size_t i = star + 1; i < length; ++i)
        {
            const int value = hexDigit(line[i]);
            if (value < 0)
                return false;
            expected = (expected << 4) | static_cast<uint32_t>(value);
        }
        return true;
    }

    inline uint32_t crc32Byte(uint32_t checksum, uint8_t value)
    {
        checksum ^= value;
        for (uint8_t bit = 0; bit < 8; ++bit)
        {
            checksum = (checksum >> 1) ^ (checksum & 1 ? 0xedb88320U : 0U);
        }
        return checksum;
    }

    inline uint32_t calculateChecksum(const char *line, size_t star, size_t digits)
    {
        uint32_t checksum = 0;
        const size_t start = digits == 2 ? 0 : 1;
        for (size_t i = start; i < star; ++i)
        {
            checksum = digits == 2
                           ? checksum ^ static_cast<uint8_t>(line[i])
                           : crc32Byte(checksum, static_cast<uint8_t>(line[i]));
        }
        return checksum;
    }

} // namespace unicore_log_detail

bool validUnicoreLogChecksum(const char *line, size_t length) {
    if (!line || length < 4 || line[0] != '#') return false;
    size_t star = length;
    while (star > 0 && line[star - 1] != '*') --star;
    if (star == 0) return false;
    --star;
    const size_t digits = length - star - 1;
    if (digits != 2 && digits != 8) return false;
    uint32_t expected = 0;
    if (!unicore_log_detail::parseExpectedChecksum(line, star, length, expected)) return false;
    const uint32_t checksum = unicore_log_detail::calculateChecksum(line, star, digits);
    return checksum == expected;
}
