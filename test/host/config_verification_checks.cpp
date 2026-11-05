#include "functions/gnss/Ubx_Config_Verification.h"
#include "functions/gnss/Ubx_Reply.h"
#include "functions/gnss/Ubx_Navigation.h"
#include "functions/gnss/Ubx_Satellites.h"
#include "functions/gnss/Unicore_Config_Verification.h"
#include <cassert>
#include <cstdio>
#include <initializer_list>
#include <string>
#include <vector>

int main() {
    std::vector<uint8_t> sat(8 + 28 * 12);
    sat[4] = 1; sat[5] = 28;
    for (size_t n = 0; n < 28; ++n) {
        sat[8 + n * 12] = 0;
        sat[9 + n * 12] = n + 1;
        sat[10 + n * 12] = 40;
        sat[11 + n * 12] = 45;
    }
    assert(UbxSatellites::valid(sat.data(), sat.size()));
    assert(!UbxSatellites::valid(sat.data(), sat.size() - 1));
    std::vector<uint8_t> frame = {0xB5, 0x62, 1, 0x35, uint8_t(sat.size()), uint8_t(sat.size() >> 8)};
    frame.insert(frame.end(), sat.begin(), sat.end());
    uint8_t a = 0, b = 0;
    for (size_t i = 2; i < frame.size(); ++i) { a += frame[i]; b += a; }
    frame.push_back(a); frame.push_back(b);
    UbxReplyBuffer<UbxSatellites::MAX_PAYLOAD + 8> satelliteReply;
    UbxReply ordinaryReply;
    bool satelliteMatched = false, ordinaryMatched = false;
    for (uint8_t byte : frame) { satelliteMatched |= satelliteReply.feed(byte); ordinaryMatched |= ordinaryReply.feed(byte); }
    assert(satelliteMatched && satelliteReply.length == frame.size());
    assert(!ordinaryMatched && sizeof(ordinaryReply.frame) == 256);
    frame.back() ^= 1;
    bool corruptMatched = false;
    for (uint8_t byte : frame) corruptMatched |= satelliteReply.feed(byte);
    assert(!corruptMatched);
    sat[20] = sat[8]; sat[21] = sat[9];
    assert(!UbxSatellites::valid(sat.data(), sat.size()));

    uint8_t dop[18] = {};
    dop[6] = 120; dop[12] = 85;
    UbxDop dopStatus;
    assert(dopStatus.decode(dop, sizeof(dop)) && dopStatus.pdop == 120 && dopStatus.hdop == 85);
    assert(!dopStatus.decode(dop, 17));
    uint8_t pvt[92] = {};
    pvt[20] = 5; pvt[21] = 1; pvt[23] = 35;
    pvt[40] = 0xF0; pvt[41] = 0x0F; // 4080 mm, not 4.08 mm.
    pvt[76] = 123;
    UbxNavigation nav;
    assert(nav.decode(pvt, sizeof(pvt)) && nav.valid);
    assert(nav.haccMm == 4080 && nav.pdop == 123 && nav.satellites == 35);
    pvt[78] = 1;
    assert(nav.decode(pvt, sizeof(pvt)) && !nav.valid);
    pvt[78] = 0; pvt[21] = 0;
    assert(nav.decode(pvt, sizeof(pvt)) && !nav.valid);
    assert(!nav.decode(pvt, 91));

    uint8_t expected[40] = {}, actual[40] = {};
    expected[2] = actual[2] = 2;
    expected[3] = actual[3] = 1;
    expected[16] = actual[16] = uint8_t(-12);
    expected[20] = actual[20] = 100;
    assert(UbxConfigVerification::fixedMatches(expected, actual, 40));
    for (size_t offset : {size_t(2), size_t(3), size_t(4), size_t(8), size_t(12),
                          size_t(16), size_t(17), size_t(18), size_t(20), size_t(23)}) {
        actual[offset] ^= 2;
        assert(!UbxConfigVerification::fixedMatches(expected, actual, 40));
        actual[offset] ^= 2;
    }
    actual[19] = 99; // Reserved bytes cannot cause a false mismatch.
    assert(UbxConfigVerification::fixedMatches(expected, actual, 40));
    actual[20] += 1; // 0.1 mm: one conversion quantization step.
    assert(UbxConfigVerification::fixedMatches(expected, actual, 40));
    actual[20] -= 1;
    assert(!UbxConfigVerification::fixedMatches(expected, actual, 39));
    // Independent keys from UBX-22008968: Galileo 1097 and BeiDou 1127 UART1.
    const uint8_t records[] = {0x19, 0x03, 0x91, 0x20, 1, 0xD7, 0x02, 0x91, 0x20, 0};
    uint8_t payload[] = {1, 0, 0, 0, 0xD7, 0x02, 0x91, 0x20, 0, 0x19, 0x03, 0x91, 0x20, 1};
    uint8_t values[2] = {};
    assert(UbxConfigVerification::validExpected(records, sizeof(records)));
    assert(UbxConfigVerification::outputValues(records, sizeof(records), payload, sizeof(payload), values));
    assert(values[0] == 1 && values[1] == 0); // Response order need not match the request.
    payload[13] = 0;
    assert(UbxConfigVerification::outputValues(records, sizeof(records), payload, sizeof(payload), values));
    assert(values[0] != records[4]); // A valid reply can still contain a mismatch.
    payload[1] = 1;
    assert(!UbxConfigVerification::outputValues(records, sizeof(records), payload, sizeof(payload), values));
    payload[1] = 0;
    assert(!UbxConfigVerification::outputValues(records, sizeof(records), payload, sizeof(payload) - 1, values));
    payload[9] = 0xD7; payload[10] = 0x02; // Duplicate BeiDou, missing Galileo.
    assert(!UbxConfigVerification::outputValues(records, sizeof(records), payload, sizeof(payload), values));
    uint8_t invalid[] = {0xFF, 0xFF, 0x91, 0x20, 1};
    assert(!UbxConfigVerification::validExpected(invalid, sizeof(invalid)));
    assert(!UbxConfigVerification::validExpected(records, 9));
    uint8_t tooMany[205] = {};
    assert(!UbxConfigVerification::validExpected(tooMany, sizeof(tooMany)));
    const uint8_t i2c[] = {1, 0, 0x72, 0x10, 0, 3, 0, 0x51, 0x10, 0};
    const uint8_t spi[] = {1, 0, 0x7A, 0x10, 0, 6, 0, 0x64, 0x10, 0};
    assert(UbxConfigVerification::validExpected(i2c, sizeof(i2c)));
    assert(UbxConfigVerification::validExpected(spi, sizeof(spi)));
    assert(UbxConfigVerification::enabledKey(3) == 0x10650001);
    const auto packet = [](const std::string &body) {
        uint32_t crc = 0;
        for (size_t i = 1; i < body.size(); ++i) {
            crc ^= static_cast<uint8_t>(body[i]);
            for (int bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ ((crc & 1) ? 0xEDB88320U : 0);
        }
        char checksum[10]; std::snprintf(checksum, sizeof(checksum), "*%08x", crc);
        return body + checksum;
    };
    const std::string header = "#UNILOGLIST,66,GPS,FINE,2203,447089000,0,0,18,33;\r\n";
    std::vector<UnicoreConfigVerification::Log> logs;
    std::string list = packet(header + "< 3\r\n< RTCM1094 COM1 1\r\n< LOG COM2 RTCM1097 ONTIME 1\r\n< BESTNAVA COM1 ONCE\r\n");
    const std::vector<char> packetBytes(list.begin(), list.end());
    assert(UnicoreConfigVerification::parseLogs(packetBytes.data(), packetBytes.size(), logs));
    assert(logs.size() == 3 && logs[0].port == 1 && logs[1].port == 2 && logs[2].period == 0);
    for (const std::string &body : {
            header + "< 2\r\n< RTCM1094 COM1 1\r\n", // Truncated rows.
            header + "< 2\r\n< RTCM1094 COM1 1\r\n< RTCM1094 COM1 1\r\n", // Duplicate key.
            header + "< 1\r\n< RTCM1094 COM9 1\r\n",
            header + "< 1\r\n< RTCM1094 COM1 nan\r\n",
            header + "< 1\r\n< RTCM1094 COM1 ONCHANGED\r\n"}) {
        list = packet(body);
        assert(!UnicoreConfigVerification::parseLogs(list.c_str(), list.size(), logs));
    }
    list = packet(header + "< 0\r\n");
    assert(UnicoreConfigVerification::parseLogs(list.c_str(), list.size(), logs) && logs.empty());
    list.back() ^= 1;
    assert(!UnicoreConfigVerification::parseLogs(list.c_str(), list.size(), logs));
    const std::string counted = header + "<\t3\r\n<\tGPGGA COM2 1 \r\n<\tRTCM1074 COM3 1 \r\n<\tRTCM1077 COM3 1 \r\n\r\n";
    assert(UnicoreConfigVerification::parseLogs(counted.c_str(), counted.size(), logs));
    assert(logs.size() == 3 && logs[0].port == 2 && logs[1].port == 3);
    assert(!UnicoreConfigVerification::parseLogs(counted.c_str(), counted.size() - 2, logs));
    list = counted;
    list.replace(list.find("<\t3"), 3, "<\t4");
    assert(!UnicoreConfigVerification::parseLogs(list.c_str(), list.size(), logs));
    list = counted + "binary";
    assert(!UnicoreConfigVerification::parseLogs(list.c_str(), list.size(), logs));
    logs.clear();
    assert(UnicoreConfigVerification::comparisonPort(0, logs) == 0);
    UnicoreConfigVerification::Log single;
    single.port = 1;
    logs.push_back(single);
    logs.push_back(single);
    assert(UnicoreConfigVerification::comparisonPort(0, logs) == 1);
    assert(UnicoreConfigVerification::comparisonPort(3, logs) == 3);
    single.port = 2;
    logs.push_back(single);
    assert(UnicoreConfigVerification::comparisonPort(0, logs) == 0);
    assert(UnicoreConfigVerification::comparisonPort(1, logs) == 1);
    puts("PASS: Fixed LLA/accuracy mismatch, reordered values, missing/duplicate keys, wrong layer and bounded parsing");
    puts("PASS: UM CRC and checksum-free lists, port/period/trigger parsing, truncated/duplicate entries and invalid values");
}
