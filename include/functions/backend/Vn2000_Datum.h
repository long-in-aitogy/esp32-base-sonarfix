#pragma once
#include <array>
#include <cstddef>
#include <cstdint>

// Parameters are populated only by CRC-valid frames in the current CORS session.
struct Vn2000MessageStatus {
    bool has1021 = false;
    bool has1023 = false;
    bool has1025 = false;
    uint32_t count1021 = 0;
    uint32_t count1023 = 0;
    uint32_t count1025 = 0;
};

struct Vn2000Helmert {
    double dX = 0;
    double dY = 0;
    double dZ = 0;
    double rX = 0;
    double rY = 0;
    double rZ = 0;
    double kT = 1;
};

struct Vn2000Residuals {
    double resB = 0;
    double resL = 0;
    double resH = 0;
    double resN = 0;
    double resE = 0;
    double resHS = 0;
};

struct Vn2000Projection {
    double centralMeridianDeg = 0;
    double scale = 0;
    double falseEasting = 500000;
    double falseNorthing = 0;
    uint8_t type = 0;
    int64_t longitudeRaw = 0;
    uint32_t scaleRaw = 0;
    uint16_t frameBytes = 0;
    std::array<char, 65> frameHex{};
};

struct Vn2000Datum {
    Vn2000MessageStatus messages;
    Vn2000Helmert helmert;
    Vn2000Residuals residuals;
    Vn2000Projection projection;
};

class Vn2000Session {
public:
    void reset();
    void feed(const uint8_t *data, size_t size);
    const Vn2000Datum &datum() const { return datum_; }
    uint32_t validFrames() const { return validFrames_; }
private:
    Vn2000Datum datum_;
    uint32_t validFrames_ = 0;
    std::array<uint8_t, 1029> frame_ = {};
    size_t size_ = 0;
    void decode(size_t length);
};

struct Vn2000Result {
    double north = 0;
    double east = 0;
    double h = 0;
    double latitude = 0;
    double longitude = 0;
    double altitude = 0;
};
bool transformVn2000(double latitude, double longitude, double altitude,
                     const Vn2000Datum &datum, Vn2000Result &result);
