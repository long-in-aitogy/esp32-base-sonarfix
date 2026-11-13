#include "functions/gnss/Ublox_Readback.h"
#include "functions/gnss/Ubx_Reply.h"
#include "functions/gnss/Ubx_Satellites.h"
#include "functions/backend/Backend_Agent_Codec.h"
#include "functions/gnss/Ubx_Config_Verification.h"
#include "functions/ntrip/RTCM_Receiver.h"
#include "Prog_Config.h"
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>
#include <array>
#include <cstring>

extern SemaphoreHandle_t rtcmBufferMutex;
extern SemaphoreHandle_t gnssSerialMutex;

namespace
{

/** @brief Implements query. */
    template <size_t Capacity>
    bool query(uint8_t cls, uint8_t id, UbxReplyBuffer<Capacity> &reply, String &error,
               const uint8_t *payload = nullptr, size_t length = 0)
    {
        if (length > 4 + UbxConfigVerification::MAX_KEYS * 4 || (length && !payload))
        {
            error = "u-blox query exceeds readback limit";
            return false;
        }
        if (!rtcmBufferMutex || xSemaphoreTake(rtcmBufferMutex, pdMS_TO_TICKS(MUTEX_TIMEOUT_MS)) != pdTRUE)
        {
            error = "GNSS command port is busy";
            return false;
        }
        if (!gnssSerialMutex || xSemaphoreTake(gnssSerialMutex, pdMS_TO_TICKS(MUTEX_TIMEOUT_MS)) != pdTRUE)
        {
            xSemaphoreGive(rtcmBufferMutex);
            error = "GNSS reader is busy";
            return false;
        }
        while (Serial1.available())
            bufferGnssQueryByte(static_cast<uint8_t>(Serial1.read()));
        std::array<uint8_t, 12 + UbxConfigVerification::MAX_KEYS * 4> poll = {
            0xB5, 0x62, cls, id, static_cast<uint8_t>(length), 0};
        if (length)
            std::memcpy(poll.data() + 6, payload, length);
        uint8_t a = 0;
        uint8_t b = 0;
        for (size_t i = 2; i < length + 6; ++i)
        {
            a += poll[i];
            b += a;
        }
        poll[length + 6] = a;
        poll[length + 7] = b;
        Serial.printf("[GNSS][READBACK][TX] UBX %02X/%02X; baud=%lu\n", cls, id,
                      static_cast<unsigned long>(Serial1.baudRate()));
        const auto written = Serial1.write(poll.data(), length + 8) == length + 8;
        Serial1.flush();
        const uint32_t started = millis();
        auto matched = false;
        uint32_t receivedBytes = 0;
        while (written && millis() - started < 3000UL && !matched)
        {
            while (Serial1.available())
            {
                const auto value = static_cast<uint8_t>(Serial1.read());
                bufferGnssQueryByte(value);
                ++receivedBytes;
                if (reply.feed(value) && reply.frame[2] == cls && reply.frame[3] == id)
                {
                    matched = true;
                    break;
                }
            }
            if (!matched)
                vTaskDelay(pdMS_TO_TICKS(5));
        }
        xSemaphoreGive(gnssSerialMutex);
        xSemaphoreGive(rtcmBufferMutex);
        const char *result;
        if (!written)
            result = "WRITE_FAILED";
        else
            result = matched ? "OK" : "TIMEOUT";
        Serial.printf("[GNSS][READBACK][RX] UBX %02X/%02X; bytes=%lu; elapsed_ms=%lu; reply=%s\n",
                      cls, id, static_cast<unsigned long>(receivedBytes),
                      static_cast<unsigned long>(millis() - started), result);
#if PROGRAM_DEBUG
        if (matched)
        {
            Serial.printf("[GNSS][READBACK][RAW] UBX %02X/%02X payload=", cls, id);
            for (size_t i = 6; i < reply.length - 2; ++i)
                Serial.printf("%02X", reply.frame[i]);
            Serial.println();
        }
#endif
        if (!matched)
            error = written ? "u-blox base readback timeout" : "u-blox query write failed";
        return matched;
    }

} // namespace

bool UbloxReadback::readTmode(uint8_t *payload, String &error)
{
    if (!payload)
    {
        error = "Missing CFG-TMODE3 output buffer";
        return false;
    }
    UbxReply reply;
    if (!query(0x06, 0x71, reply, error))
        return false;
    if (reply.length != 48 || reply.frame[6] != 0)
    {
        error = "Invalid CFG-TMODE3 response";
        return false;
    }
    std::memcpy(payload, reply.frame.data() + 6, 40);
    return true;
}

/** @brief Implements UbloxReadback::readBaseStatus. */
bool UbloxReadback::readBaseStatus(UbxBaseStatus &status, String &error)
{
    std::array<uint8_t, 40> mode{};
    if (!readTmode(mode.data(), error))
        return false;
    if (!status.tmode(mode.data(), mode.size()))
    {
        error = "Invalid CFG-TMODE3 response";
        return false;
    }
    if (status.mode != 1)
        return true;
    UbxReply survey;
    if (!query(0x01, 0x3B, survey, error))
        return false;
    if (!status.svin(survey.frame.data() + 6, survey.length - 8))
    {
        error = "Invalid NAV-SVIN response";
        return false;
    }
    return true;
}

bool UbloxReadback::readNavigation(UbxNavigation &status, String &error)
{
    UbxReply reply;
    if (!query(0x01, 0x07, reply, error))
        return false;
    if (status.decode(reply.frame.data() + 6, reply.length - 8))
        return true;
    error = "Invalid NAV-PVT response";
    return false;
}

bool UbloxReadback::readDop(UbxDop &status, String &error)
{
    UbxReply reply;
    if (!query(0x01, 0x04, reply, error))
        return false;
    if (status.decode(reply.frame.data() + 6, reply.length - 8))
        return true;
    error = "Invalid NAV-DOP response";
    return false;
}

bool UbloxReadback::readVersion(String &payloadBase64, String &error)
{
    UbxReplyBuffer<528> reply;
    if (!query(0x0A, 0x04, reply, error))
        return false;
    const size_t length = reply.length - 8;
    const uint8_t *payload = reply.frame.data() + 6;
    if (length < 40 || length > 520 || (length - 40) % 30 || !payload[0])
    {
        error = "Invalid MON-VER payload";
        return false;
    }
    for (size_t start = 0; start < length; start += start == 30 ? 10 : 30)
    {
        const size_t width = start == 30 ? 10 : 30;
        for (size_t i = start; i < start + width && payload[i]; ++i)
        {
            if (payload[i] < 32 || payload[i] > 126)
            {
                error = "Invalid MON-VER text";
                return false;
            }
        }
    }
    String encoded = BackendAgentInternal::encodeBase64(payload, length);
    if (encoded.isEmpty())
    {
        error = "Cannot encode MON-VER response";
        return false;
    }
    payloadBase64 = encoded;
    return true;
}

bool UbloxReadback::readSatellites(String &payloadBase64, String &error)
{
    UbxReplyBuffer<UbxSatellites::MAX_PAYLOAD + 8> reply;
    if (!query(0x01, 0x35, reply, error))
        return false;
    if (!UbxSatellites::valid(reply.frame.data() + 6, reply.length - 8))
    {
        error = "Invalid NAV-SAT response";
        return false;
    }
    String encoded = BackendAgentInternal::encodeBase64(reply.frame.data() + 6, reply.length - 8);
    if (encoded.isEmpty())
    {
        error = "Cannot encode NAV-SAT response";
        return false;
    }
    payloadBase64 = encoded;
    return true;
}

bool UbloxReadback::readBaud(uint8_t port, uint32_t &baud, String &error)
{
    if (port != 1 && port != 2)
    {
        error = "Invalid u-blox UART port";
        return false;
    }
    UbxReply reply;
    if (!query(0x06, 0x00, reply, error, &port, 1))
        return false;
    if (reply.length != 28 || reply.frame[6] != port)
    {
        error = "Invalid CFG-PRT response";
        return false;
    }
    baud = UbxBaseStatus::u32(reply.frame.data() + 14);
    return true;
}

bool UbloxReadback::readOutputValues(const uint8_t *expected, size_t length,
                                     uint8_t *values, String &error)
{
    if (!values || !UbxConfigVerification::validExpected(expected, length))
    {
        error = "Invalid output verification keys";
        return false;
    }
    std::array<uint8_t, 4 + UbxConfigVerification::MAX_KEYS * 4> payload{};
    for (size_t i = 0; i < length / 5; ++i)
        std::memcpy(payload.data() + 4 + i * 4, expected + i * 5, 4);
    UbxReply reply;
    if (!query(0x06, 0x8B, reply, error, payload.data(), 4 + length / 5 * 4))
        return false;
    if (!UbxConfigVerification::outputValues(expected, length, reply.frame.data() + 6, reply.length - 8, values))
    {
        error = "Incomplete or invalid CFG-VALGET response";
        return false;
    }
    return true;
}
