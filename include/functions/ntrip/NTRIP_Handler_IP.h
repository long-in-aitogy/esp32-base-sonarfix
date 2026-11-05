#ifndef NTRIP_HANDLER_IP_H
#define NTRIP_HANDLER_IP_H

// ============ GẮN CÁC THƯ VIỆN CẦN THIẾT ==============

#include <Arduino.h>
#include "functions/backend/Vn2000_Datum.h"
#include "Top_Lvl_Config.h"
#include "hardware/Connection_type.h"

extern SemaphoreHandle_t rtcmBufferMutex;
extern SemaphoreHandle_t tcpStreamMutex;

// =============== KHAI BÁO HÀM =================

int setupNTRIP();
int loopNTRIP(String& rtcmData);
int connectNTRIP();
bool isNtripConnected();
void stopNtrip();
bool ntripServerConnected(uint8_t serverId);
uint32_t ntripServerBps(uint8_t serverId);
String ntripServerError(uint8_t serverId);
Client& activeNtripClient();

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

#endif
