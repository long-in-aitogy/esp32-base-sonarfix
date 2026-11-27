#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>
#include <array>

namespace BackendAgentTypes
{
    struct AutoBaseLocationReply
    {
        static constexpr size_t capacity = 1536;
        std::array<char, capacity> json{};
    };

    struct AutoBaseConfig
    {
        String host;
        uint16_t port = 0;
        String username;
        String password;
        String mountpoint;
        uint8_t ntripVersion = 0;
        uint32_t timeoutSeconds = 0;
        uint8_t fixedStreakRequired = 0;
    };

    struct AutoBaseResultInput
    {
        double finalLatitude = 0;
        double finalLongitude = 0;
        double finalAltitude = 0;
        double rawLatitude = 0;
        double rawLongitude = 0;
        double rawAltitude = 0;
        bool transformed = false;
        bool transportRestored = false;
        size_t sampleCount = 0;
        const char *projectionSource = "";
        const char *provinceCode = "";
        const char *provinceName = "";
        double centralMeridianDeg = 0;
        double scale = 0;
    };

    struct ReferenceCheckConfig
    {
        JsonObject reference;
        double referenceLatitude = 0;
        double referenceLongitude = 0;
        double referenceAltitude = 0;
        double restoreLatitude = 0;
        double restoreLongitude = 0;
        double restoreAltitude = 0;
        String host;
        uint16_t port = 0;
        String username;
        String password;
        String mountpoint;
        uint32_t timeoutSeconds = 0;
        uint16_t requestedSamples = 0;
    };

    struct StartupPosition
    {
        double latitude = 0.0;
        double longitude = 0.0;
        double altitude = 0.0;
        bool ellipsoid = false;
    };

    struct ProjectedPosition
    {
        double latitude;
        double longitude;
        double altitude;
        double northing = 0.0;
        double easting = 0.0;
        double projectedHeight = 0.0;
    };
} // namespace BackendAgentTypes
