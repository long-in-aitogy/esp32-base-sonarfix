#pragma once
#include <Arduino.h>
#include "functions/gnss/Ubx_Base_Status.h"
#include "functions/gnss/Ubx_Navigation.h"

namespace UbloxReadback
{
    bool readTmode(uint8_t *payload, String &error);
    bool readBaseStatus(UbxBaseStatus &status, String &error);
    bool readNavigation(UbxNavigation &status, String &error);
    bool readDop(UbxDop &status, String &error);
}
