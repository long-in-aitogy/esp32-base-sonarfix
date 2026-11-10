#pragma once
#include <Arduino.h>

namespace BackendAgentInternal
{
    String urlEncode(const String &value);
    String tokenFingerprint(const String &token);
    size_t decodeBase64(const String &encoded, uint8_t *output, size_t outputCapacity);
    bool delayMarker(const uint8_t *data, size_t length, uint32_t &delayMs);
    bool licenseMatchesSerial(const String &serial, const String &token);
} // namespace BackendAgentInternal
