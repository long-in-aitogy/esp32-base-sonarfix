#ifndef NTRIP_ROVER_H
#define NTRIP_ROVER_H

#include "functions/ntrip/ntrip_common.h"

bool startNtripRover(const String &host, uint16_t port, const String &username,
                     const String &password, String mountpoint,
                     uint8_t version = 1);
// Returns 200 while the session is alive, or 504 when unavailable/disconnected.
int loopNtripRover();
void stopNtripRover();
void clearNtripRoverSession();
bool ntripRoverSessionStarted();
bool ntripRoverActive();
uint32_t ntripRoverBytesReceived();
uint32_t ntripRoverPacketsReceived();

#endif
