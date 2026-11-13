#ifndef NTRIP_ROVER_H
#define NTRIP_ROVER_H

#include "functions/ntrip/ntrip_common.h"
#include "functions/backend/Vn2000_Datum.h"

struct NtripRoverOptions
{
    uint8_t version = 1;
    String *selectedMountpoint = nullptr;
    String receiverId;
};

bool startNtripRover(const String &host, uint16_t port, const String &username,
                     const String &password, String mountpoint,
                     const NtripRoverOptions &options = NtripRoverOptions());
// Returns 200 while the session is alive, or 504 when unavailable/disconnected.
int loopNtripRover();
void stopNtripRover();
void clearNtripRoverSession();
bool ntripRoverSessionStarted();
bool ntripRoverActive();
uint32_t ntripRoverBytesReceived();
uint32_t ntripRoverPacketsReceived();
const char *ntripRoverLastError();
// Caller must hold tcpStreamMutex while accessing the active Rover session.
Vn2000Datum ntripRoverDatum();

#endif
