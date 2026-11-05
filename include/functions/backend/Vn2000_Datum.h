#pragma once
#include <cstddef>
#include <cstdint>

// Parameters are populated only by CRC-valid frames in the current CORS session.
struct Vn2000Datum {
    bool has1021 = false, has1023 = false, has1025 = false;
    uint32_t count1021 = 0, count1023 = 0, count1025 = 0;
    double dX = 0, dY = 0, dZ = 0, rX = 0, rY = 0, rZ = 0, kT = 1;
    double resB = 0, resL = 0, resH = 0;
    double resN = 0, resE = 0, resHS = 0;
    double centralMeridianDeg = 0, scale = 0;
    double falseEasting = 500000, falseNorthing = 0;
    uint8_t projectionType = 0;
    int64_t projectionLongitudeRaw = 0;
    uint32_t projectionScaleRaw = 0;
    uint16_t projectionFrameBytes = 0;
    char projectionFrameHex[65] = {};
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
    uint8_t frame_[1029] = {};
    size_t size_ = 0;
    void decode(size_t length);
};

struct Vn2000Result {
    double north = 0, east = 0, h = 0;
    double latitude = 0, longitude = 0, altitude = 0;
};
bool transformVn2000(double latitude, double longitude, double altitude,
                     const Vn2000Datum &datum, Vn2000Result &result);
