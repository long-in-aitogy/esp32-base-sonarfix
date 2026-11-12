#pragma once
#include <Arduino.h>
#include "functions/gnss/Ubx_Base_Status.h"
#include "functions/gnss/Ubx_Navigation.h"

namespace UbloxReadback
{
    bool readOutputValues(const uint8_t *expected, size_t length, uint8_t *values, String &error);
    bool readVersion(String &payloadBase64, String &error);
    bool readSatellites(String &payloadBase64, String &error);
    bool readBaud(uint8_t port, uint32_t &baud, String &error);
    bool readTmode(uint8_t *payload, String &error);
    bool readBaseStatus(UbxBaseStatus &status, String &error);
    bool readNavigation(UbxNavigation &status, String &error);
    bool readDop(UbxDop &status, String &error);
}
