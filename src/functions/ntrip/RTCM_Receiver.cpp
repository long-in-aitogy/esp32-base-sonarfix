#include "functions/ntrip/RTCM_Receiver.h"

#include "HardwareSerial.h"
#include "Prog_Config.h"
#include "functions/backend/Backend_Agent.h"
#include "functions/backend/Base_Sample.h"
#include <array>
#include <cstddef>
#include <cmath>
#include <cstdio>
#include <cstdlib>

namespace
{

    constexpr size_t MAX_NMEA_LENGTH = 512;
    constexpr size_t MAX_RTCM_FRAME_LENGTH = 1029; // 3-byte header + 1023 + CRC

    struct RtcmParserState
    {
        String nmeaBuffer;
        String pendingRtcmData;
        std::array<uint8_t, MAX_RTCM_FRAME_LENGTH> rtcmFrame = {};
        size_t rtcmLength = 0;
        size_t rtcmExpectedLength = 0;
        std::array<uint8_t, 6> ubxHeader = {};
        size_t ubxHeaderLength = 0;
        size_t ubxBytesRemaining = 0;
    };

    struct InputRateState
    {
        uint32_t windowStartedMs = 0;
        uint32_t windowBytes = 0;
        uint32_t bytesPerSecond = 0;
    };

    RtcmParserState &parserState()
    {
        static RtcmParserState state;
        return state;
    }

    GnssTelemetrySnapshot &telemetryState()
    {
        static GnssTelemetrySnapshot state;
        return state;
    }

    portMUX_TYPE &telemetryMux()
    {
        static portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
        return mux;
    }

    InputRateState &inputRateState()
    {
        static InputRateState state;
        return state;
    }

/** @brief Implements noteInputBytes. */
    void noteInputBytes(size_t count)
    {
        portENTER_CRITICAL(&telemetryMux());
        telemetryState().traffic.bytesRead += count;
        telemetryState().hasData = true;
        telemetryState().lastDataMs = millis();
        portEXIT_CRITICAL(&telemetryMux());
    }

/** @brief Implements noteRtcmBytes. */
    void noteRtcmBytes(size_t count)
    {
        const uint32_t now = millis();
        portENTER_CRITICAL(&telemetryMux());
        if (inputRateState().windowStartedMs == 0)
            inputRateState().windowStartedMs = now;
        inputRateState().windowBytes += static_cast<uint32_t>(count);
        if (now - inputRateState().windowStartedMs >= 1000UL)
        {
            const uint32_t elapsed = now - inputRateState().windowStartedMs;
            inputRateState().bytesPerSecond = elapsed > 0
                                      ? static_cast<uint32_t>((static_cast<uint64_t>(inputRateState().windowBytes) * 1000ULL) / elapsed)
                                      : inputRateState().windowBytes;
            inputRateState().windowStartedMs = now;
            inputRateState().windowBytes = 0;
        }
        portEXIT_CRITICAL(&telemetryMux());
    }

/** @brief Implements nmeaCoordinate. */
    double nmeaCoordinate(const char *raw, const char *hemisphere, bool latitude)
    {
        if (!raw || !*raw || !hemisphere || !hemisphere[0] || hemisphere[1] != '\0')
            return NAN;
        const char direction = hemisphere[0];
        if (latitude ? (direction != 'N' && direction != 'S') : (direction != 'E' && direction != 'W'))
            return NAN;
        for (const char *p = raw; *p; ++p)
            if ((*p < '0' || *p > '9') && *p != '.')
                return NAN;
        char *end = nullptr;
        const double value = std::strtod(raw, &end);
        if (end == raw || *end != '\0' || !std::isfinite(value) || value < 0 || value > (latitude ? 9000.0 : 18000.0))
            return NAN;
        const auto degrees = static_cast<int>(value / 100.0);
        const auto minutes = value - degrees * 100.0;
        if (minutes < 0 || minutes >= 60)
            return NAN;
        auto coordinate = degrees + minutes / 60.0;
        if (direction == 'S' || direction == 'W')
        {
            coordinate = -coordinate;
        }
        return coordinate;
    }

/** @brief Implements setFixStatus. */
    void setFixStatus(std::array<char, 16> &target, int quality)
    {
        const char *status;
        switch (quality)
        {
        case 0:
            status = "NO_FIX";
            break;
        case 1:
            status = "GPS_FIX";
            break;
        case 2:
            status = "DGPS";
            break;
        case 4:
            status = "RTK_FIXED";
            break;
        case 5:
            status = "RTK_FLOAT";
            break;
        case 7:
            status = "BASE_FIXED";
            break;
        default:
            status = "NO_FIX";
            break;
        }
        snprintf(target.data(), target.size(), "%s", status);
        target[target.size() - 1] = '\0';
    }

    struct GgaReading
    {
        bool hasFixQuality = false;
        int fixQuality = 0;
        bool hasPosition = false;
        double latitude = 0.0;
        double longitude = 0.0;
        double altitude = 0.0;
        float hdop = 0.0F;
        uint8_t satellites = 0;
    };

    GgaReading parseGgaFields(char *const *fields, size_t fieldCount)
    {
        GgaReading reading;
        reading.hasFixQuality = true;
        if (fieldCount > 6)
        {
            char *end = nullptr;
            const long quality = std::strtol(fields[6], &end, 10);
            if (end != fields[6] && *end == '\0' && quality >= 0 && quality <= 8)
                reading.fixQuality = static_cast<int>(quality);
        }
        if (fieldCount <= 9 || !fields[2][0] || !fields[3][0] || !fields[4][0] || !fields[5][0])
            return reading;

        reading.latitude = nmeaCoordinate(fields[2], fields[3], true);
        reading.longitude = nmeaCoordinate(fields[4], fields[5], false);
        if (!std::isfinite(reading.latitude) || !std::isfinite(reading.longitude))
            return reading;
        reading.satellites = static_cast<uint8_t>(constrain(atoi(fields[7]), 0, 255));
        reading.hdop = static_cast<float>(atof(fields[8]));
        reading.altitude = fieldCount > 12
            ? ggaEllipsoidalHeight(fields[9], fields[10], fields[11], fields[12]) : NAN;
        reading.hasPosition = true;
        return reading;
    }

/** @brief Implements parseGsvFields. */
    void parseGsvFields(char *const *fields, size_t fieldCount, bool &updateSnr,
                        float &snrSum, uint32_t &snrCount)
    {
        for (size_t i = 4; i + 3 < fieldCount; i += 4)
        {
            if (!fields[i + 3] || !*fields[i + 3])
                continue;
            const auto snr = atoi(fields[i + 3]);
            if (snr < 0 || snr > 99)
                continue;
            snrSum += static_cast<float>(snr);
            ++snrCount;
        }
        updateSnr = snrCount > 0;
    }

/** @brief Implements parseGstFields. */
    void parseGstFields(char *const *fields, size_t fieldCount, bool &updateGst,
                        float &gstSemiMajor, float &gstSemiMinor, float &gstHacc)
    {
        if (fieldCount <= 7)
            return;
        gstSemiMajor = static_cast<float>(atof(fields[3]));
        gstSemiMinor = static_cast<float>(atof(fields[4]));
        const auto latitudeSigma = static_cast<float>(atof(fields[6]));
        const auto longitudeSigma = static_cast<float>(atof(fields[7]));
        gstHacc = sqrtf(latitudeSigma * latitudeSigma + longitudeSigma * longitudeSigma);
        updateGst = gstHacc > 0.0F;
    }

    int nmeaHexValue(char value)
    {
        if (value >= '0' && value <= '9') return value - '0';
        if (value >= 'A' && value <= 'F') return value - 'A' + 10;
        if (value >= 'a' && value <= 'f') return value - 'a' + 10;
        return -1;
    }

    bool hasValidNmeaChecksum(const String &sentence)
    {
        const int star = sentence.indexOf('*');
        if (star < 0)
            return true;
        if (star != static_cast<int>(sentence.length()) - 3)
            return false;

        const int high = nmeaHexValue(sentence[star + 1]);
        const int low = nmeaHexValue(sentence[star + 2]);
        if (high < 0 || low < 0)
            return false;

        auto checksum = std::byte{0};
        for (int i = 1; i < star; ++i)
            checksum ^= static_cast<std::byte>(static_cast<unsigned char>(sentence[i]));
        return checksum == static_cast<std::byte>((high << 4) | low);
    }

    bool splitNmeaSentence(const String &sentence, std::array<char, MAX_NMEA_LENGTH> &line,
                           std::array<char *, 32> &fields, size_t &fieldCount,
                           const char *&type)
    {
        const auto copyLength = min(sentence.length(), line.size() - 1);
        memcpy(line.data(), sentence.c_str(), copyLength);
        line[copyLength] = '\0';

        char *cursor = line.data() + 1;
        while (fieldCount < fields.size())
        {
            fields[fieldCount++] = cursor;
            char *comma = strchr(cursor, ',');
            if (!comma)
                break;
            *comma = '\0';
            cursor = comma + 1;
        }
        if (fieldCount == 0)
            return false;

        const auto typeLength = strnlen(fields[0], copyLength);
        if (typeLength < 3)
            return false;
        type = fields[0] + typeLength - 3;
        return true;
    }

    struct NmeaMeasurements
    {
        GgaReading gga;
        bool updateSnr = false;
        float snrSum = 0.0F;
        uint32_t snrCount = 0;
        bool updateGst = false;
        float gstSemiMajor = 0.0F;
        float gstSemiMinor = 0.0F;
        float gstHacc = 0.0F;
    };

    NmeaMeasurements parseNmeaMeasurements(const char *type, char *const *fields,
                                           size_t fieldCount)
    {
        NmeaMeasurements measurements;
        if (strcmp(type, "GGA") == 0)
        {
            measurements.gga = parseGgaFields(fields, fieldCount);
        }
        else if (strcmp(type, "GSV") == 0)
        {
            parseGsvFields(fields, fieldCount, measurements.updateSnr,
                           measurements.snrSum, measurements.snrCount);
        }
        else if (strcmp(type, "GST") == 0)
        {
            parseGstFields(fields, fieldCount, measurements.updateGst,
                           measurements.gstSemiMajor, measurements.gstSemiMinor,
                           measurements.gstHacc);
        }
        return measurements;
    }

    void updateNmeaCounters(const char *type)
    {
        ++telemetryState().traffic.nmeaSentences;
        if (strcmp(type, "GGA") == 0)
            ++telemetryState().traffic.ggaCount;
        else if (strcmp(type, "GSA") == 0)
            ++telemetryState().traffic.gsaCount;
        else if (strcmp(type, "GSV") == 0)
            ++telemetryState().traffic.gsvCount;
        else if (strcmp(type, "GST") == 0)
            ++telemetryState().traffic.gstCount;
    }

    void updateGgaTelemetry(const String &sentence, const char *type,
                            const GgaReading &gga)
    {
        if (gga.hasFixQuality)
            setFixStatus(telemetryState().fixStatus, gga.fixQuality);
        if (strcmp(type, "GGA") != 0)
            return;

        snprintf(telemetryState().lastGga.data(), telemetryState().lastGga.size(), "%s", sentence.c_str());
        telemetryState().lastGga[telemetryState().lastGga.size() - 1] = '\0';
        telemetryState().lastGgaMs = millis();
        if (!gga.hasPosition)
        {
            telemetryState().latitude = NAN;
            telemetryState().longitude = NAN;
            telemetryState().altitude = NAN;
        }
    }

    void updateNmeaMeasurements(const NmeaMeasurements &measurements)
    {
        if (const auto &gga = measurements.gga; gga.hasPosition)
        {
            telemetryState().latitude = gga.latitude;
            telemetryState().longitude = gga.longitude;
            telemetryState().altitude = gga.altitude;
            telemetryState().hdop = gga.hdop;
            telemetryState().satellites = gga.satellites;
        }
        if (measurements.updateSnr)
        {
            const uint32_t oldSamples = telemetryState().snrSamples;
            telemetryState().snrSamples += measurements.snrCount;
            telemetryState().latestGsvSamples = measurements.snrCount;
            telemetryState().lastGsvMs = millis();
            telemetryState().latestAverageSnr = measurements.snrSum /
                                         static_cast<float>(measurements.snrCount);
            telemetryState().averageSnr = oldSamples == 0
                                       ? measurements.snrSum / static_cast<float>(measurements.snrCount)
                                       : ((telemetryState().averageSnr * static_cast<float>(oldSamples)) + measurements.snrSum) /
                                             static_cast<float>(telemetryState().snrSamples);
        }
        if (measurements.updateGst)
        {
            telemetryState().gstSemiMajor = measurements.gstSemiMajor;
            telemetryState().gstSemiMinor = measurements.gstSemiMinor;
            telemetryState().gstHacc = measurements.gstHacc;
            telemetryState().lastGstMs = millis();
        }
    }

    void updateNmeaTelemetry(const String &sentence, const char *type,
                             const NmeaMeasurements &measurements)
    {
        portENTER_CRITICAL(&telemetryMux());
        telemetryState().hasData = true;
        telemetryState().lastDataMs = millis();
        updateNmeaCounters(type);
        updateGgaTelemetry(sentence, type, measurements.gga);
        updateNmeaMeasurements(measurements);
        portEXIT_CRITICAL(&telemetryMux());
    }

    void publishNmeaHealthSentence(const String &rawSentence, const char *type)
    {
        if (const auto backendSentence = strcmp(type, "GGA") == 0 || strcmp(type, "GSA") == 0 ||
                                         strcmp(type, "GSV") == 0 || strcmp(type, "GST") == 0;
            !backendSentence)
            return;

        auto outbound = rawSentence;
        outbound.trim();
        outbound += "\r\n";
        backendAgent().enqueueNmea(reinterpret_cast<const uint8_t *>(outbound.c_str()),
                                 outbound.length());
    }

/** @brief Implements parseNmeaSentence. */
    void parseNmeaSentence(const String &rawSentence)
    {
        auto sentence = rawSentence;
        sentence.trim();
        if (sentence.length() < 7 || sentence[0] != '$')
            return;
        if (!hasValidNmeaChecksum(sentence))
            return;
        if (sentence.startsWith("$PUBX"))
            backendAgent().setDetectedChipIfUnknown("Ublox");

        std::array<char, MAX_NMEA_LENGTH> line = {};
        std::array<char *, 32> fields = {};
        size_t fieldCount = 0;
        const char *type = nullptr;
        if (!splitNmeaSentence(sentence, line, fields, fieldCount, type))
            return;
        const auto measurements = parseNmeaMeasurements(type, fields.data(), fieldCount);
        updateNmeaTelemetry(sentence, type, measurements);
        publishNmeaHealthSentence(rawSentence, type);
    }

/** @brief Implements resetRtcmParser. */
    void resetRtcmParser()
    {
        parserState().rtcmLength = 0;
        parserState().rtcmExpectedLength = 0;
    }

/** @brief Implements processRtcmByte. */
    bool processRtcmByte(uint8_t value, String &rtcmOutput)
    {
        if (parserState().rtcmLength == 1 && (std::byte{value} & std::byte{0xFC}) != std::byte{})
        {
            resetRtcmParser();
            return false;
        }
        if (parserState().rtcmLength >= parserState().rtcmFrame.size())
        {
            resetRtcmParser();
            return true;
        }

        parserState().rtcmFrame[parserState().rtcmLength++] = value;
        if (parserState().rtcmLength == 3)
        {
            const uint16_t payloadLength =
                (static_cast<uint16_t>(parserState().rtcmFrame[1]) & 0x03U) * 256U + parserState().rtcmFrame[2];
            parserState().rtcmExpectedLength = static_cast<size_t>(payloadLength) + 6U;
            if (parserState().rtcmExpectedLength > parserState().rtcmFrame.size())
            {
                resetRtcmParser();
                return true;
            }
        }
        if (parserState().rtcmExpectedLength == 0 || parserState().rtcmLength != parserState().rtcmExpectedLength)
            return true;

        // Forward the complete RTCM frame without validating its CRC or decoding its type.
        rtcmOutput.concat(reinterpret_cast<const char *>(parserState().rtcmFrame.data()), parserState().rtcmLength);
        backendAgent().enqueueRtcm(parserState().rtcmFrame.data(), parserState().rtcmLength);
        noteRtcmBytes(parserState().rtcmLength);
        portENTER_CRITICAL(&telemetryMux());
        ++telemetryState().traffic.rtcmFrames;
        telemetryState().hasData = true;
        telemetryState().lastDataMs = millis();
        portEXIT_CRITICAL(&telemetryMux());
        resetRtcmParser();
        return true;
    }

/** @brief Implements processUbxHeaderByte. */
    bool processUbxHeaderByte(uint8_t value)
    {
        if (parserState().ubxHeaderLength == 1 && value != 0x62)
        {
            parserState().ubxHeaderLength = 0;
            return false;
        }

        parserState().ubxHeader[parserState().ubxHeaderLength++] = value;
        if (parserState().ubxHeaderLength != parserState().ubxHeader.size())
            return true;

        const auto payloadLength = size_t(parserState().ubxHeader[4]) | (size_t(parserState().ubxHeader[5]) << 8);
        parserState().ubxHeaderLength = 0;
        if (payloadLength <= 8192)
            parserState().ubxBytesRemaining = payloadLength + 2;
        return true;
    }

/** @brief Implements consumeByte. */
    void consumeByte(uint8_t value, String &rtcmOutput)
    {
        // UBX payload is binary and may contain '$', LF or 0xD3. Skip the whole
        // frame before looking for NMEA/RTCM, including across UART read chunks.
        if (parserState().ubxBytesRemaining > 0)
        {
            --parserState().ubxBytesRemaining;
            return;
        }
        if (parserState().ubxHeaderLength > 0 && processUbxHeaderByte(value))
            return;
        if (parserState().rtcmLength > 0 && processRtcmByte(value, rtcmOutput))
            return;

        if (!parserState().nmeaBuffer.isEmpty())
        {
            if (value == '\n')
            {
                parserState().nmeaBuffer += static_cast<char>(value);
                parseNmeaSentence(parserState().nmeaBuffer);
                parserState().nmeaBuffer = "";
            }
            else if (value == '$')
            {
                // A malformed/incomplete line should not swallow the next valid
                // sentence when the GNSS stream recovers.
                parserState().nmeaBuffer = "$";
            }
            else if ((value < 0x20 && value != '\r') || value > 0x7E)
            {
                parserState().nmeaBuffer = "";
                consumeByte(value, rtcmOutput);
            }
            else if (parserState().nmeaBuffer.length() < MAX_NMEA_LENGTH - 1)
            {
                parserState().nmeaBuffer += static_cast<char>(value);
            }
            else
            {
                parserState().nmeaBuffer = "";
            }
            return;
        }

        if (value == 0xB5)
        {
            parserState().ubxHeader[0] = value;
            parserState().ubxHeaderLength = 1;
        }
        else if (value == 0xD3)
        {
            parserState().rtcmFrame[0] = value;
            parserState().rtcmLength = 1;
            parserState().rtcmExpectedLength = 0;
        }
        else if (value == '$')
        {
            parserState().nmeaBuffer = "$";
        }
    }

} // namespace

/** @brief Implements bufferGnssQueryByte. */
void bufferGnssQueryByte(uint8_t value)
{
    noteInputBytes(1);
    consumeByte(value, parserState().pendingRtcmData);
}

/** @brief Implements receiveRtcmFromGnss. */
String receiveRtcmFromGnss()
{
    String rtcmData;
    rtcmData.reserve(1024);
    std::array<uint8_t, 128> buffer = {};

    if (gnssSerialMutex() == nullptr ||
        !xSemaphoreTake(gnssSerialMutex(), pdMS_TO_TICKS(MUTEX_TIMEOUT_MS)))
    {
        return rtcmData;
    }

    if (!parserState().pendingRtcmData.isEmpty())
    {
        rtcmData = parserState().pendingRtcmData;
        parserState().pendingRtcmData = "";
    }

    while (Serial1.available() > 0)
    {
        const auto bytesAvailable = static_cast<size_t>(Serial1.available());
        const auto bytesToRead = min(bytesAvailable, buffer.size());
        auto stopReading = bytesToRead == 0;

        size_t bytesRead = 0;
        if (!stopReading)
        {
            bytesRead = Serial1.readBytes(
                reinterpret_cast<char *>(buffer.data()), bytesToRead);
            stopReading = bytesRead == 0;
        }
        if (stopReading)
            break;
        noteInputBytes(bytesRead);
        for (size_t i = 0; i < bytesRead; ++i)
        {
            consumeByte(buffer[i], rtcmData);
        }
    }
    xSemaphoreGive(gnssSerialMutex());

    // Count forwarded RTCM bytes for the periodic UART diagnostic log.
    static uint32_t lastLogMs = 0;
    static uint32_t receivedBytes = 0;
    receivedBytes += rtcmData.length();
    if (millis() - lastLogMs >= 5000UL)
    {
        Serial.printf("[RTCM] Framed UART bytes in last interval (CRC chua kiem tra): %lu\n",
                      static_cast<unsigned long>(receivedBytes));
        const auto snapshot = getGnssTelemetrySnapshot();
        Serial.printf("[GNSS UART] GGA total=%lu; last_age_ms=%lu; RX bytes=%llu\n",
                      static_cast<unsigned long>(snapshot.traffic.ggaCount),
                      snapshot.lastGgaMs == 0 ? UINT32_MAX : millis() - snapshot.lastGgaMs,
                      static_cast<unsigned long long>(snapshot.traffic.bytesRead));
        receivedBytes = 0;
        lastLogMs = millis();
    }
    return rtcmData;
}

/** @brief Implements consumeRtcmMessageCounts. */
RtcmMessageCounts consumeRtcmMessageCounts()
{
    // Return zero per-type counters; this parser does not classify RTCM messages.
    return RtcmMessageCounts{};
}

/** @brief Implements getGnssTelemetrySnapshot. */
GnssTelemetrySnapshot getGnssTelemetrySnapshot()
{
    GnssTelemetrySnapshot copy;
    portENTER_CRITICAL(&telemetryMux());
    copy = telemetryState();
    portEXIT_CRITICAL(&telemetryMux());
    if (copy.lastGgaMs == 0 || millis() - copy.lastGgaMs > 15000UL)
    {
        copy.fixStatus = {'N', 'O', '_', 'F', 'I', 'X'};
    }
    return copy;
}

/** @brief Implements getRtcmInputBps. */
uint32_t getRtcmInputBps()
{
    const uint32_t now = millis();
    portENTER_CRITICAL(&telemetryMux());
    if (inputRateState().windowStartedMs > 0 && now - inputRateState().windowStartedMs >= 1000UL)
    {
        const uint32_t elapsed = now - inputRateState().windowStartedMs;
        inputRateState().bytesPerSecond = elapsed > 0
                                  ? static_cast<uint32_t>((static_cast<uint64_t>(inputRateState().windowBytes) * 1000ULL) / elapsed)
                                  : inputRateState().windowBytes;
        inputRateState().windowStartedMs = now;
        inputRateState().windowBytes = 0;
    }
    const uint32_t result = inputRateState().bytesPerSecond;
    portEXIT_CRITICAL(&telemetryMux());
    return result;
}
