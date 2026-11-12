#include "functions/backend/Backend_Agent_Codec.h"
#include "functions/backend/Device_Token.h"
#include <array>
#include <cstddef>
#include <vector>
#include <cmath>
#include <cctype>
#include <cstdlib>
#include <cstdio>
#if !defined(NATIVE_BUILD)
#include <mbedtls/sha256.h>
#endif

namespace BackendAgentInternal
{
    String encodeBase64(const uint8_t *data, size_t length) {
    static constexpr char alphabet[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    String encoded;
    encoded.reserve(((length + 2) / 3) * 4);
    for (size_t i = 0; i < length; i += 3) {
        const uint32_t a = data[i];
        const uint32_t b = i + 1 < length ? data[i + 1] : 0;
        const uint32_t c = i + 2 < length ? data[i + 2] : 0;
        const uint32_t value = (a << 16) | (b << 8) | c;
        encoded += alphabet[(value >> 18) & 0x3F];
        encoded += alphabet[(value >> 12) & 0x3F];
        encoded += i + 1 < length ? alphabet[(value >> 6) & 0x3F] : '=';
        encoded += i + 2 < length ? alphabet[value & 0x3F] : '=';
    }
    return encoded;
}


    String urlEncode(const String &value)
    {
        static constexpr char hexDigits[] = "0123456789ABCDEF";
        String encoded;
        encoded.reserve(value.length() + 8);
        for (const char character : value)
        {
            const auto c = static_cast<uint8_t>(character);
            if (isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~')
            {
                encoded += static_cast<char>(c);
            }
            else
            {
                encoded += '%';
                const std::byte byte{c};
                encoded += hexDigits[std::to_integer<unsigned int>(byte >> 4)];
                encoded += hexDigits[std::to_integer<unsigned int>(byte & std::byte{0x0F})];
            }
        }
        return encoded;
    }

    String tokenFingerprint(const String &token)
    {
        if (token.isEmpty())
        {
            return String();
        }

#if !defined(NATIVE_BUILD)
        std::array<uint8_t, 32> digest = {};
        mbedtls_sha256_context context;
        mbedtls_sha256_init(&context);
        if (mbedtls_sha256_starts_ret(&context, 0) == 0 && mbedtls_sha256_update_ret(&context, reinterpret_cast<const unsigned char *>(token.c_str()), token.length()) == 0 && mbedtls_sha256_finish_ret(&context, digest.data()) == 0)
        {
            mbedtls_sha256_free(&context);
            std::array<char, 17> result = {};
            for (size_t i = 0; i < 8; ++i)
            {
                snprintf(result.data() + (i * 2), 3, "%02x", digest[i]);
            }
            return String(result.data());
        }
        mbedtls_sha256_free(&context);
#endif

        // Fallback fingerprint when SHA-256 support is absent or hashing fails.
        uint32_t hash = 2166136261UL;
        for (const char character : token)
        {
            hash ^= static_cast<uint8_t>(character);
            hash *= 16777619UL;
        }
        std::array<char, 17> result = {};
        snprintf(result.data(), result.size(), "%08lx%08lx",
                 static_cast<unsigned long>(hash),
                 static_cast<unsigned long>(hash ^ 0xA5A5A5A5UL));
        return String(result.data());
    }

    int base64Value(char c)
    {
        if (c >= 'A' && c <= 'Z')
            return c - 'A';
        if (c >= 'a' && c <= 'z')
            return c - 'a' + 26;
        if (c >= '0' && c <= '9')
            return c - '0' + 52;
        if (c == '+')
            return 62;
        if (c == '/')
            return 63;
        return -1;
    }

    size_t decodeBase64(const String &encoded, uint8_t *output, size_t outputCapacity)
    {
        uint32_t value = 0;
        int bits = -8;
        size_t outputLength = 0, symbols = 0, padding = 0;
        for (const char character : encoded)
        {
            const auto c = character;
            if (c == '\r' || c == '\n' || c == ' ' || c == '\t')
                continue;
            if (c == '=')
            {
                if (++padding > 2)
                    return 0;
                continue;
            }
            const auto decoded = base64Value(c);
            if (decoded < 0 || padding)
                return 0;
            ++symbols;
            value = (value << 6) | static_cast<uint32_t>(decoded);
            bits += 6;
            if (bits >= 0)
            {
                if (!output || outputLength >= outputCapacity)
                {
                    return 0;
                }
                output[outputLength++] = static_cast<uint8_t>((value >> bits) & 0xFF);
                bits -= 8;
            }
        }
        if (symbols % 4 == 1 || (padding && (symbols + padding) % 4 != 0) ||
            (value & ((1U << (bits + 8)) - 1U)))
            return 0;
        return outputLength;
    }

    bool delayMarker(const uint8_t *data, size_t length, uint32_t &delayMs)
    {
        if (length < 9 || memcmp(data, "$DELAY_", 7) != 0 || data[length - 1] != '$')
        {
            return false;
        }
        uint32_t value = 0;
        for (size_t i = 7; i + 1 < length; ++i)
        {
            if (data[i] < '0' || data[i] > '9')
            {
                return false;
            }
            value = value * 10UL + static_cast<uint32_t>(data[i] - '0');
            if (value > 10000UL)
            {
                value = 10000UL;
            }
        }
        delayMs = value;
        return true;
    }

    String licenseCodeFromBase(const String &base)
    {
        const auto length = static_cast<int>(base.length());
        if (length < 2 || length > 31)
            return String();

        std::vector<int> parts(static_cast<size_t>(length), 0);
        std::vector<double> smoothed(static_cast<size_t>(length) + 1U, 0.0);
        auto number = atof(base.c_str());
        if (!std::isfinite(number))
            return String();

        number *= length;
        auto remainingDigits = length;
        parts[0] = static_cast<int>(number * pow(10.0, -static_cast<double>(remainingDigits)));
        for (int index = 1; index < length; ++index)
        {
            number -= static_cast<double>(parts[index - 1]) / pow(10.0, -static_cast<double>(remainingDigits));
            --remainingDigits;
            parts[index] = static_cast<int>(number * pow(10.0, -static_cast<double>(remainingDigits)));
        }
        // Keep the averaged final part in floating point; truncation changes the license code.
        const auto finalPart = (parts[length - 2] + parts[length - 1]) / 2.0 + 1.0;
        smoothed[0] = static_cast<double>(parts[0]);

        String output;
        output.reserve(static_cast<size_t>(length) * 2U);
        const auto logarithm = log10(finalPart);
        for (int index = 0; index < length; ++index)
        {
            const auto nextPart = index + 1 == length
                                      ? finalPart
                                      : static_cast<double>(parts[index + 1]);
            smoothed[index + 1] = (smoothed[index] + nextPart) / 2.0;
            const auto first = smoothed[index + 1] * exp(-0.2);
            const auto second = logarithm * pow(nextPart, 0.2);
            // Use round-to-nearest, ties-to-even under the default rounding mode.
            output += String(static_cast<long>(std::nearbyint(first + second)));
        }
        return output;
    }

    String licenseBaseForSerial(const String &serial)
    {
        const auto start = serial.length() > 10
                               ? static_cast<int>(serial.length() - 10U)
                               : 0;
        String base;
        for (int index = start; index < static_cast<int>(serial.length()); ++index)
        {
            auto character = serial[static_cast<unsigned int>(index)];
            if (character >= 'a' && character <= 'z')
                character -= 'a' - 'A';
            base += String(static_cast<int>(static_cast<unsigned char>(character)));
        }
        if (base.length() > 12)
            base = base.substring(0, 12);
        while (base.length() < 12)
            base += '0';
        return base;
    }

    bool licenseMatchesSerial(const String &serial, const String &token)
    {
        if (serial.isEmpty() || token.isEmpty())
            return false;
        return isDeviceBearerToken(token.c_str(), token.length()) || token == licenseCodeFromBase(licenseBaseForSerial(serial));
    }

} // namespace BackendAgentInternal
