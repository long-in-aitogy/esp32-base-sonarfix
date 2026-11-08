#pragma once

#include <Arduino.h>
#include "Top_Lvl_Config.h"
#include "hardware/Connection_type.h"

extern SemaphoreHandle_t rtcmBufferMutex;
extern SemaphoreHandle_t tcpStreamMutex;

// Shared source/Rover transport; callers serialize access with tcpStreamMutex.
namespace ntrip_common {
extern bool roverSessionActive;
extern bool roverSessionAuthenticated;
extern uint32_t roverLastGgaMs;
Client &clientFor(uint8_t index);
bool safeNtripField(const String &value);
bool waitForNtripResponse(Client &client, String *statusLine = nullptr, bool rover = false);
} // namespace ntrip_common
