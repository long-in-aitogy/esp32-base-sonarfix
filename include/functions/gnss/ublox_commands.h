#pragma once
#include "functions/gnss/gnss_cmd_builder.h"
#include <cmath>
#include <limits>

namespace UbloxCommands
{
    inline int64_t fixedCoordinateUnits(double value, double scale)
    {
        double units = value * scale * 100.0;
        if (const double nearest = std::round(units); std::abs(units - nearest) <= 4 * std::numeric_limits<double>::epsilon() * std::fmax(1.0, std::abs(units)))
            units = nearest;
        return static_cast<int64_t>(units);
    }

    using GnssCmdBuilder::Command;
    using GnssCmdBuilder::CommandList;
    using GnssCmdBuilder::GnssOptions;

    Command buildOutputConfigCommand(const GnssOptions &options);
    CommandList buildBaseSurveyInCommand(uint32_t duration, float accuracy, const GnssOptions &options);
    CommandList buildBaseFixedLlaCommand(double lat, double lon, double alt, float accuracy, const GnssOptions &options);
    CommandList buildBaseRtcmOutputCommand(const String &message, const String &port, bool enabled);
    CommandList buildBaseAllRtcmOutputCommand(const String &port, bool enabled);
    CommandList buildRoverCommand();
    void routeUbloxOutput(uint8_t *data, size_t length);
}
