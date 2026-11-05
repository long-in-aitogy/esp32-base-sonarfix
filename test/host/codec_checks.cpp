#include "functions/backend/Backend_Agent_Codec.h"
#include <array>
#include <cassert>
#include <cstring>
#include <iostream>

using namespace BackendAgentInternal;

int main() {
    for (const auto &pair : std::array<std::array<const char *, 2>, 7>{{
        {{"", ""}}, {{"f", "Zg=="}}, {{"fo", "Zm8="}}, {{"foo", "Zm9v"}},
        {{"foob", "Zm9vYg=="}}, {{"fooba", "Zm9vYmE="}}, {{"foobar", "Zm9vYmFy"}}
    }}) {
        assert(encodeBase64(String(pair[0])) == pair[1]);
    }
    uint8_t decoded[3072] = {};
    for (size_t length : {1U, 2U, 3U, 16U, 255U, 256U, 3072U}) {
        std::array<uint8_t, 3072> input{};
        for (size_t i = 0; i < length; ++i) input[i] = static_cast<uint8_t>(i);
        const String encoded = encodeBase64(input.data(), length);
        assert(decodeBase64(encoded, decoded, sizeof(decoded)) == length);
        assert(std::memcmp(input.data(), decoded, length) == 0);
    }
    for (const char *invalid : {"Z", "Zg=", "Zg===", "Zh==", "Zg==AAAA", "!!!!"})
        assert(decodeBase64(invalid, decoded, sizeof(decoded)) == 0);
    assert(decodeBase64(" Z g = = \n", decoded, sizeof(decoded)) == 1 && decoded[0] == 'f');
    assert(decodeBase64("Zm9v", decoded, 2) == 0);
    assert(urlEncode("a b/+?") == "a%20b%2F%2B%3F");
    uint32_t duration = 0;
    for (const char *text : {"$DELAY_0$", "$DELAY_2000$", "$DELAY_99999$"})
        assert(delayMarker(reinterpret_cast<const uint8_t *>(text), std::strlen(text), duration));
    assert(duration == 10000);
    const char *invalidDelay = "$DELAY_bad$";
    assert(!delayMarker(reinterpret_cast<const uint8_t *>(invalidDelay), std::strlen(invalidDelay), duration));
    assert(tokenFingerprint("").isEmpty());
    assert(tokenFingerprint("secret").length() == 16);
    assert(!licenseMatchesSerial("", "dt_test") && !licenseMatchesSerial("esp_test", ""));
    std::cout << "PASS: shared codec vectors, binary round trips, malformed Base64, bounds, URL encoding and delay markers\n";
}
