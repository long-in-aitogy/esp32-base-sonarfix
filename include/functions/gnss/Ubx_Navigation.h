#pragma once
#include <cstddef>
#include <cstdint>

// NAV-PVT layout and units: UBX-22008968. No configuration writes.
struct UbxNavigation {
    uint32_t haccMm = 0;
    uint16_t pdop = 0;
    uint8_t satellites = 0;
    uint8_t fixType = 0;
    bool valid = false;

    bool decode(const uint8_t *p, size_t size) {
        if (size != 92 || p[20] > 5) return false;
        fixType = p[20];
        valid = (p[21] & 1) && fixType >= 2 && !(p[78] & 1);
        satellites = p[23];
        haccMm = uint32_t(p[40]) | uint32_t(p[41]) << 8
            | uint32_t(p[42]) << 16 | uint32_t(p[43]) << 24;
        pdop = uint16_t(p[76]) | uint16_t(p[77]) << 8;
        return true;
    }
};

// NAV-DOP (01/04): all values are dimensionless, scaled by 0.01.
struct UbxDop {
    uint16_t hdop = 0;
    uint16_t pdop = 0;
    bool decode(const uint8_t *p, size_t size) {
        if (size != 18) return false;
        pdop = uint16_t(p[6]) | uint16_t(p[7]) << 8;
        hdop = uint16_t(p[12]) | uint16_t(p[13]) << 8;
        return true;
    }
};
