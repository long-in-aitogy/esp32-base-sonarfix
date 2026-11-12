#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include "functions/backend/Backend_Agent_Codec.h"

// Shared implementation details for BackendAgent translation units.
namespace BackendAgentInternal
{
    inline constexpr size_t STATUS_DOCUMENT_SIZE = 8192;
    inline constexpr size_t VERIFICATION_DOCUMENT_SIZE = 12288;
    inline constexpr size_t CONFIG_DOCUMENT_SIZE = 4096;
    inline constexpr size_t COMMAND_DOCUMENT_SIZE = 24576;

    bool enforceBaseAccuracy(JsonObject base);
    Preferences &backendPreferences();
    bool beginBackendPreferences(bool readOnly);
    String readPreference(const char *key, const String &fallback = String());
    String epochString();
    bool jsonBool(JsonObjectConst object, const String &key, bool fallback);
    String jsonString(JsonObjectConst object, const String &key, const String &fallback = String());
    void copyJsonObject(JsonDocument &target, const char *key, const String &serialized);
} // namespace BackendAgentInternal
