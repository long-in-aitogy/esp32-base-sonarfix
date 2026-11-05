#include "functions/gnss/Gnss_Detection.h"
#include "functions/gnss/Unicore_Identification.h"
#include "Prog_Config.h"
#include <cstring>

namespace {
  inline constexpr uint8_t ubxMonVerPoll[] = {
    0xB5, 0x62, 0x0A, 0x04, 0x00, 0x00, 0x0E, 0x34
  };

  void clearGnssInput()
  {
    while (Serial1.available() > 0) {
      Serial1.read();
    }
  }

  bool hasValidUbxFrame(const uint8_t *data, size_t length)
  {
    for (size_t start = 0; start + 8 <= length; ++start) {
      if (data[start] != 0xB5 || data[start + 1] != 0x62 ||
          data[start + 2] != 0x0A || data[start + 3] != 0x04) {
        continue;
      }

      const size_t payloadLength =
          static_cast<size_t>(data[start + 4]) |
          (static_cast<size_t>(data[start + 5]) << 8);
      const size_t frameLength = payloadLength + 8;
      // A MON-VER response contains SW (30 bytes) and HW (10 bytes), never an empty poll.
      if (payloadLength < 40 || frameLength > 512) continue;
      if (start + frameLength > length) {
        continue;
      }

      uint8_t checksumA = 0;
      uint8_t checksumB = 0;
      for (size_t i = start + 2; i < start + 6 + payloadLength; ++i) {
        checksumA = static_cast<uint8_t>(checksumA + data[i]);
        checksumB = static_cast<uint8_t>(checksumB + checksumA);
      }

      if (checksumA == data[start + frameLength - 2] &&
          checksumB == data[start + frameLength - 1]) {
        return true;
      }
    }
    return false;
  }

  bool receiveUbxFrame(uint32_t timeoutMs)
  {
    uint8_t buffer[512] = {};
    size_t length = 0;
    const uint32_t start = millis();

    while (millis() - start < timeoutMs) {
      while (Serial1.available() > 0) {
        const int value = Serial1.read();
        if (length < sizeof(buffer)) {
          buffer[length++] = static_cast<uint8_t>(value);
        } else {
          memmove(buffer, buffer + 1, sizeof(buffer) - 1);
          buffer[sizeof(buffer) - 1] = static_cast<uint8_t>(value);
        }

        if (hasValidUbxFrame(buffer, length)) {
          return true;
        }
      }
      delay(2);
    }
    return false;
  }

  bool receiveUnicoreIdentification(uint32_t timeoutMs)
  {
    UnicoreIdentification identity;
    const uint32_t start = millis();
    while (millis() - start < timeoutMs) {
      while (Serial1.available() > 0) {
        if (identity.feed(static_cast<uint8_t>(Serial1.read()))) {
          Serial.printf("[GNSS][UNICORE RESPONSE] %s\n", identity.line);
          return true;
        }
      }
      delay(2);
    }

    return false;
  }
} // namespace

GnssCmdBuilder::GnssSensorType detectGnssSensorType() {
  Serial.println("[GNSS] Cho receiver khoi dong 2000 ms truoc khi probe.");
  delay(2000);
  const uint32_t baudRates[] = {GNSS_BAUD, 38400, 9600, 19200, 57600, 230400, 460800};
  for (const uint32_t baud : baudRates) {
    Serial1.updateBaudRate(baud);
    delay(30);
    Serial.printf("[GNSS] Probe baud=%lu\n", static_cast<unsigned long>(baud));
    clearGnssInput();
    Serial1.write(ubxMonVerPoll, sizeof(ubxMonVerPoll));
    Serial1.flush();
    if (receiveUbxFrame(1000)) {
      Serial.printf("[GNSS] Da nhan dien u-blox qua UBX-MON-VER, baud=%lu.\n", static_cast<unsigned long>(baud));
      return GnssCmdBuilder::GnssSensorType::Ublox;
    }

    clearGnssInput();
    Serial1.print("VERSIONA\r\n");
    Serial1.flush();
    delay(50);
    if (receiveUnicoreIdentification(1000)) {
      Serial.printf("[GNSS] Da nhan dien Unicore qua lenh VERSIONA, baud=%lu.\n", static_cast<unsigned long>(baud));
      return GnssCmdBuilder::GnssSensorType::Unicore;
    }
  }

  Serial1.updateBaudRate(GNSS_BAUD);
  delay(30);
  clearGnssInput();
  Serial.printf("[GNSS] Thu lai VERSIONA tai baud=%lu sau khi receiver da khoi dong.\n",
                static_cast<unsigned long>(GNSS_BAUD));
  Serial1.print("VERSIONA\r\n");
  Serial1.flush();
  if (receiveUnicoreIdentification(1500)) return GnssCmdBuilder::GnssSensorType::Unicore;
  Serial.println("[GNSS][ERROR] Khong the nhan dien chip GNSS.");
  return GnssCmdBuilder::GnssSensorType::Invalid;
}
