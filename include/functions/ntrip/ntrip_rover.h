#pragma once

#include "functions/ntrip/ntrip_common.h"
#include "functions/backend/Vn2000_Datum.h"

// Temporary rover-side NTRIP session used by the auto-base/reference
// workflows. RTCM received here is injected into the GNSS module unchanged;
// datum frames are decoded separately for the current receive session.
bool startNtripRover(const String &host, uint16_t port, const String &username,
                    const String &password, String mountpoint,
                    uint8_t version = 1);
int loopNtripRover();
void stopNtripRover();
bool ntripRoverActive();
uint32_t ntripRoverBytesReceived();
uint32_t ntripRoverPacketsReceived();
const char *ntripRoverLastError();
// Caller owns tcpStreamMutex, like start/loop/stopNtripRover.
Vn2000Datum ntripRoverDatum();
