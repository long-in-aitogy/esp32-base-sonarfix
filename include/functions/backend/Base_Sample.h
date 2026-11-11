#pragma once
#include <cstdint>
#include <cstring>
#include <cmath>
#include <cstdlib>

inline bool freshRtkSample(uint32_t now, uint32_t lastGga, const char *fix)
{
    return lastGga != 0 && (now - lastGga) <= 3000U && strcmp(fix, "RTK_FIXED") == 0;
}

// GGA reports orthometric height H and geoid separation N; ellipsoidal h = H + N.
inline double ggaEllipsoidalHeight(const char *height, const char *heightUnit,
                                   const char *separation, const char *separationUnit)
{
    if (!height || !*height || !separation || !*separation || !heightUnit || !separationUnit
        || strcmp(heightUnit, "M") != 0 || strcmp(separationUnit, "M") != 0)
        return NAN;
    char *heightEnd = nullptr;
    char *separationEnd = nullptr;
    const double hMsl = std::strtod(height, &heightEnd);
    const double geoid = std::strtod(separation, &separationEnd);
    return heightEnd != height && *heightEnd == '\0'
        && separationEnd != separation && *separationEnd == '\0'
        && std::isfinite(hMsl) && std::isfinite(geoid) ? hMsl + geoid : NAN;
}
