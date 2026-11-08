#pragma once

#include "functions/ntrip/ntrip_common.h"

int setupNTRIP();
int loopNTRIP(String& rtcmData);
int connectNTRIP();
bool isNtripConnected();
void stopNtrip();
bool ntripServerConnected(uint8_t serverId);
uint32_t ntripServerBps(uint8_t serverId);
String ntripServerError(uint8_t serverId);
Client& activeNtripClient();
