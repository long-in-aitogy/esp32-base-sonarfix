#pragma once
#include <cstdint>
#include <cstring>

inline bool freshRtkSample(uint32_t now, uint32_t lastGga, const char *fix) {
    return lastGga != 0 && static_cast<uint32_t>(now - lastGga) <= 3000U
        && strcmp(fix, "RTK_FIXED") == 0;
}
