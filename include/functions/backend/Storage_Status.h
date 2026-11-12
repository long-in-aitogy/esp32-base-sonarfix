#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>

void appendStorageStatus(JsonObject system);
bool clearUnusedWifi(String &error);
bool readNvsInventory(uint32_t offset, const String &commandId, String &output, String &error);
