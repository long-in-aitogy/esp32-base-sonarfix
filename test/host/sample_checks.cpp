#include "functions/backend/Base_Sample.h"
#include <cassert>
#include <cmath>
#include <iostream>

int main() {
    assert(freshRtkSample(4000, 1000, "RTK_FIXED"));
    assert(!freshRtkSample(4001, 1000, "RTK_FIXED"));
    assert(!freshRtkSample(1000, 0, "RTK_FIXED"));
    assert(!freshRtkSample(1000, 1000, "RTK_FLOAT"));
    assert(!freshRtkSample(1000, 1000, "SINGLE"));
    assert(freshRtkSample(1000, UINT32_MAX - 999, "RTK_FIXED"));
    assert(!freshRtkSample(3001, UINT32_MAX - 999, "RTK_FIXED"));
    assert(std::abs(ggaEllipsoidalHeight("12.5", "M", "-3.25", "M") - 9.25) < 1e-12);
    assert(std::abs(ggaEllipsoidalHeight("-12.5", "M", "3.25", "M") + 9.25) < 1e-12);
    assert(ggaEllipsoidalHeight("0", "M", "0", "M") == 0);
    for (const char *invalid : {"", "bad", "1m", "nan", "inf", "1e9999"}) {
        assert(std::isnan(ggaEllipsoidalHeight(invalid, "M", "1", "M")));
        assert(std::isnan(ggaEllipsoidalHeight("1", "M", invalid, "M")));
    }
    assert(std::isnan(ggaEllipsoidalHeight(nullptr, "M", "1", "M")));
    assert(std::isnan(ggaEllipsoidalHeight("1", nullptr, "1", "M")));
    assert(std::isnan(ggaEllipsoidalHeight("1", "M", nullptr, "M")));
    assert(std::isnan(ggaEllipsoidalHeight("1", "M", "1", nullptr)));
    assert(std::isnan(ggaEllipsoidalHeight("1", "F", "1", "M")));
    assert(std::isnan(ggaEllipsoidalHeight("1", "M", "1", "F")));
    std::cout << "PASS: RTK sample age, clock wraparound, GGA height/geoid units and invalid numbers\n";
}
