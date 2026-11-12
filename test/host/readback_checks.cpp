#include <Arduino.h>
#include <ArduinoJson.h>
#include "functions/gnss/Ublox_Readback.h"
#include "functions/gnss/Unicore_Readback.h"
#include "functions/gnss/Ubx_Config_Verification.h"
#include <cassert>
#include <cmath>
#include <iostream>

static void reset() {
    assert(acquiredLocks == releasedLocks);
    Serial1 = {}; hostMillis = 0; deniedLock = nullptr;
    rtcmBufferMutex = reinterpret_cast<void *>(1);
    gnssSerialMutex = reinterpret_cast<void *>(2);
    acquiredLocks = releasedLocks = 0; bufferedQueryBytes.clear();
}

static std::vector<uint8_t> frame(uint8_t cls, uint8_t id, std::vector<uint8_t> payload) {
    std::vector<uint8_t> bytes{0xB5, 0x62, cls, id, uint8_t(payload.size()), uint8_t(payload.size() >> 8)};
    bytes.insert(bytes.end(), payload.begin(), payload.end());
    uint8_t a = 0, b = 0;
    for (size_t i = 2; i < bytes.size(); ++i) { a += bytes[i]; b += a; }
    bytes.push_back(a); bytes.push_back(b); return bytes;
}

static void asciiReply(const std::string &body, bool crc = false) {
    uint32_t checksum = 0;
    for (size_t i = crc ? 1 : 0; i < body.size(); ++i) {
        checksum ^= uint8_t(body[i]);
        if (crc) for (unsigned bit = 0; bit < 8; ++bit)
            checksum = (checksum >> 1) ^ (checksum & 1 ? 0xedb88320U : 0U);
    }
    char suffix[16]; std::snprintf(suffix, sizeof(suffix), crc ? "*%08X\r\n" : "*%02X\r\n", checksum);
    const std::string line = body + suffix;
    Serial1.replies.emplace_back(line.begin(), line.end());
}

static void checkUblox() {
    String error, encoded;
    for (unsigned failure = 0; failure < 5; ++failure) {
        reset(); error.clear();
        if (failure == 0) rtcmBufferMutex = nullptr;
        if (failure == 1) deniedLock = rtcmBufferMutex;
        if (failure == 2) gnssSerialMutex = nullptr;
        if (failure == 3) deniedLock = gnssSerialMutex;
        if (failure == 4) Serial1.shortWrite = true;
        assert(!UbloxReadback::readVersion(encoded, error) && !error.isEmpty());
        assert(acquiredLocks == releasedLocks);
    }
    reset(); error.clear();
    assert(!UbloxReadback::readVersion(encoded, error));
    assert(error == "u-blox base readback timeout" && hostMillis == 3000);
    for (const auto &payload : {std::vector<uint8_t>(39), std::vector<uint8_t>(40),
                               std::vector<uint8_t>(41, 'A'), std::vector<uint8_t>(40, 1)}) {
        reset(); error.clear(); Serial1.replies.push_back(frame(10, 4, payload));
        assert(!UbloxReadback::readVersion(encoded, error));
    }
    reset(); error.clear();
    std::vector<uint8_t> version(70); version[0] = 'S'; version[30] = 'H'; version[40] = 'E';
    auto wrong = frame(1, 4, std::vector<uint8_t>(18));
    auto good = frame(10, 4, version); wrong.insert(wrong.end(), good.begin(), good.end());
    Serial1.input = {0xd3, 0, 1}; Serial1.replies.push_back(wrong);
    assert(UbloxReadback::readVersion(encoded, error) && !encoded.isEmpty());
    assert(bufferedQueryBytes.size() == wrong.size() + 3);
    for (bool valid : {false, true}) {
        reset(); error.clear(); std::vector<uint8_t> sat(8); sat[4] = valid ? 1 : 0;
        Serial1.replies.push_back(frame(1, 0x35, sat));
        assert(UbloxReadback::readSatellites(encoded, error) == valid);
        reset(); error.clear(); std::vector<uint8_t> dop(valid ? 18 : 17); dop[6] = 120; dop[12] = 80;
        Serial1.replies.push_back(frame(1, 4, dop)); UbxDop status;
        assert(UbloxReadback::readDop(status, error) == valid);
        if (valid) assert(status.pdop == 120 && status.hdop == 80);
        reset(); error.clear(); std::vector<uint8_t> nav(92); nav[20] = valid ? 3 : 6; nav[21] = 1; nav[23] = 20;
        Serial1.replies.push_back(frame(1, 7, nav)); UbxNavigation navigation;
        assert(UbloxReadback::readNavigation(navigation, error) == valid);
        if (valid) assert(navigation.valid && navigation.satellites == 20);
    }
    for (bool valid : {false, true}) {
        reset(); error.clear(); std::vector<uint8_t> mode(valid ? 40 : 39); uint8_t out[40] = {};
        Serial1.replies.push_back(frame(6, 0x71, mode));
        assert(UbloxReadback::readTmode(out, error) == valid);
        reset(); error.clear(); std::vector<uint8_t> port(20); port[0] = valid ? 1 : 2; port[8] = 0; port[9] = 0xc2; port[10] = 1;
        Serial1.replies.push_back(frame(6, 0, port)); uint32_t baud = 0;
        assert(UbloxReadback::readBaud(1, baud, error) == valid);
        if (valid) assert(baud == 115200);
    }
    reset(); error.clear(); uint32_t baud = 0;
    assert(!UbloxReadback::readBaud(0, baud, error) && Serial1.writes.empty());
    for (unsigned scenario = 0; scenario < 4; ++scenario) {
        reset(); error.clear(); std::vector<uint8_t> mode(40); mode[2] = scenario ? 1 : 0;
        Serial1.replies.push_back(frame(6, 0x71, mode));
        if (scenario >= 2) Serial1.replies.push_back(frame(1, 0x3b, std::vector<uint8_t>(scenario == 3 ? 40 : 39)));
        UbxBaseStatus status;
        assert(UbloxReadback::readBaseStatus(status, error) == (scenario == 0 || scenario == 3));
    }
    const uint8_t expected[] = {3, 0, 0x51, 0x10, 1}; uint8_t value = 0;
    reset(); error.clear(); assert(!UbloxReadback::readOutputValues(nullptr, 0, &value, error));
    for (bool valid : {false, true}) {
        reset(); error.clear(); std::vector<uint8_t> output{uint8_t(valid ? 1 : 0), 0, 0, 0, 3, 0, 0x51, 0x10, 1};
        Serial1.replies.push_back(frame(6, 0x8b, output));
        assert(UbloxReadback::readOutputValues(expected, sizeof(expected), &value, error) == valid);
        if (valid) assert(value == 1);
    }
}

static void checkUnicore() {
    String mode, error;
    for (unsigned failure = 0; failure < 5; ++failure) {
        reset(); error.clear();
        if (failure == 0) rtcmBufferMutex = nullptr;
        if (failure == 1) deniedLock = rtcmBufferMutex;
        if (failure == 2) gnssSerialMutex = nullptr;
        if (failure == 3) deniedLock = gnssSerialMutex;
        if (failure == 4) Serial1.shortWrite = true;
        assert(!UnicoreReadback::readMode(mode, error) && !error.isEmpty());
    }
    reset(); error.clear(); assert(!UnicoreReadback::readMode(mode, error) && hostMillis == 3000);
    reset(); error.clear();
    const std::string rejected = "$command,MODE,response: ERROR\r\n";
    Serial1.replies.emplace_back(rejected.begin(), rejected.end());
    assert(!UnicoreReadback::readMode(mode, error) && error.startsWith("Unicore rejected query"));
    for (const auto *body : {"#MODE; mode base time 120,", "#MODE;MODE ROVER", "#MODE;MODE BASE 21 105 12"}) {
        reset(); error.clear(); asciiReply(body);
        assert(UnicoreReadback::readMode(mode, error));
        assert(std::string(UnicoreReadback::modeKind(mode)) != "unknown");
    }
    for (const auto *body : {"#MODE,no-separator", "#MODE;INVALID"}) {
        reset(); error.clear(); asciiReply(body); assert(!UnicoreReadback::readMode(mode, error));
    }
    reset(); error.clear();
    const std::string corrupt = "#MODE;MODE ROVER*00\r\n";
    Serial1.replies.emplace_back(corrupt.begin(), corrupt.end());
    assert(!UnicoreReadback::readMode(mode, error) && error == "Unicore MODE checksum mismatch");
    assert(std::string(UnicoreReadback::modeKind("other")) == "unknown");
    unsigned positionCase = 0;
    for (const auto *fields : {"SOL_COMPUTED,FIXEDPOS,21,105,12,3,WGS84,0.3,0.4,0",
                              "SOL_COMPUTED,FIXEDPOS,21,105,12,3,WGS84,-1,0.4,0"}) {
        reset(); error.clear(); asciiReply(std::string("#BESTNAVA,header;") + fields, true);
        DynamicJsonDocument doc(2048);
        assert(UnicoreReadback::readBestPosition(doc.to<JsonObject>(), error));
        assert(doc["latitude"] == 21 && doc["longitude"] == 105 && doc["height_msl"] == 12);
        assert(doc.containsKey("horizontal_sigma_m") == (positionCase++ == 0));
        if (doc.containsKey("horizontal_sigma_m")) assert(std::abs(doc["horizontal_sigma_m"].as<double>() - 0.5) < 1e-9);
    }
    for (const auto *fields : {"short", "NO_SOLUTION,FIXEDPOS,21,105,12,3,WGS84,0,0,0",
                              "SOL_COMPUTED,FIXEDPOS,bad,105,12,3,WGS84,0,0,0",
                              "SOL_COMPUTED,FIXEDPOS,21,bad,12,3,WGS84,0,0,0",
                              "SOL_COMPUTED,FIXEDPOS,21,105,bad,3,WGS84,0,0,0",
                              "SOL_COMPUTED,FIXEDPOS,91,105,12,3,WGS84,0,0,0",
                              "SOL_COMPUTED,FIXEDPOS,nan,105,12,3,WGS84,0,0,0",
                              "SOL_COMPUTED,FIXEDPOS,21,181,12,3,WGS84,0,0,0",
                              "SOL_COMPUTED,FIXEDPOS,21,105,inf,3,WGS84,0,0,0",
                              "SOL_COMPUTED,FIXEDPOS,21,105,12,bad,WGS84,0,0,0",
                              "SOL_COMPUTED,FIXEDPOS,21,105,12,3,OTHER,0,0,0"}) {
        reset(); error.clear(); asciiReply(std::string("#BESTNAVA,header;") + fields, true);
        DynamicJsonDocument doc(2048);
        assert(!UnicoreReadback::readBestPosition(doc.to<JsonObject>(), error) && !error.isEmpty());
    }
    reset(); error.clear(); asciiReply("#UNILOGLIST,header;COM2,RTCM1074,1", true);
    String logs; assert(UnicoreReadback::readLogList(logs, error) && logs.startsWith("#UNILOGLIST,"));
    reset(); error.clear(); logs.clear();
    const std::string multiline = "#UNILOGLIST,header;\r\nCOM2,RTCM1074,1\r\n\r\n";
    Serial1.replies.emplace_back(multiline.begin(), multiline.end());
    assert(UnicoreReadback::readLogList(logs, error));
    reset();
}

int main() {
    checkUblox(); checkUnicore();
    std::cout << "PASS: real UBX/Unicore readback, locks, timeout, malformed data, coordinates and UART preservation\n";
}
