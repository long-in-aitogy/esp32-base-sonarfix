#include "functions/backend/Backend_Agent.h"
#include "functions/backend/Backend_Agent_Internal.h"
#include "functions/gnss/Ublox_Readback.h"
#include "functions/gnss/Unicore_Readback.h"
#include <array>
#include <cmath>
#include <cstdlib>
#include <cstdio>
#include <cstring>

using namespace BackendAgentInternal;

namespace
{
    constexpr uint32_t AUTO_SURVEY_IN_SECONDS = 120;

    double configNumber(JsonVariantConst value, double fallback)
    {
        if (value.isNull())
            return fallback;
        if (value.is<bool>())
            return NAN;
        if (value.is<const char *>())
        {
            const char *text = value.as<const char *>();
            char *end = nullptr;
            const auto number = std::strtod(text, &end);
            return end != text && *end == '\0' && std::isfinite(number) ? number : double(NAN);
        }
        return value.is<double>() ? value.as<double>() : double(NAN);
    }
}

bool BackendAgent::readStartupReceiverMode(GnssCmdBuilder::GnssSensorType detected, String &error)
{
    if (detected == GnssCmdBuilder::GnssSensorType::Unicore)
    {
        String mode;
        return UnicoreReadback::readMode(mode, error);
    }
    UbxBaseStatus status;
    return UbloxReadback::readBaseStatus(status, error);
}

bool BackendAgent::prepareStartupConfig(DynamicJsonDocument &config, JsonObject &base,
                                        bool &saved, String &method, String &error)
{
    if (deserializeJson(config, baseConfig_.c_str()) != DeserializationError::Ok || !config.is<JsonObject>())
    {
        error = "Saved Base configuration is invalid";
        return false;
    }
    base = config.as<JsonObject>();
    saved = base.size() > 0;
    method = base["base_setup_method"] | String();
    if (saved && method.isEmpty())
    {
        error = "Saved Base mode is missing";
        return false;
    }
    if (saved)
        return true;

    base["base_setup_method"] = "SURVEY_IN";
    base["survey_in_duration"] = AUTO_SURVEY_IN_SECONDS;
    base["survey_in_accuracy"] = 5;
    base["mode"] = "BASE";
    JsonObject options = base.createNestedObject("gnss_options");
    options["output_mode"] = "rtcm_only";
    options["msm_level"] = "both";
    method = "SURVEY_IN";
    return true;
}

bool BackendAgent::buildStartupCommands(JsonObject base,
                                        GnssCmdBuilder::GnssSensorType detected,
                                        bool restoreFixed,
                                        GnssCmdBuilder::CommandList &commands,
                                        StartupPosition &position,
                                        String &error)
{
    using namespace GnssCmdBuilder;
    GnssOptions options;
    options.ports = {"UART1"};
    const JsonObjectConst output = base["gnss_options"].as<JsonObjectConst>();
    options.outputMode = String(output["output_mode"] | "rtcm_only") == "rtcm_only"
                             ? OutputMode::RtcmOnly
                             : OutputMode::DiagnosticsRtcm;
    const String level = output["msm_level"] | "both";
    if (level == "7")
        options.msmLevel = MsmLevel::Msm7;
    else if (level == "4")
        options.msmLevel = MsmLevel::Msm4;
    else
        options.msmLevel = MsmLevel::Both;
    const JsonObjectConst systems = output["constellations"].as<JsonObjectConst>();
    options.gps = systems["gps"] | true;
    options.glo = systems["glo"] | true;
    options.gal = systems["gal"] | true;
    options.bds = systems["bds"] | true;
    options.qzss = systems["qzss"] | true;
    options.sbas = systems["sbas"] | true;
    position.ellipsoid = detected == GnssSensorType::Ublox;
    if (!restoreFixed)
    {
        const auto duration = AUTO_SURVEY_IN_SECONDS;
        const auto accuracy = configNumber(base["survey_in_accuracy"], 5.0);
        if (const auto maxDuration = detected == GnssSensorType::Unicore ? 3600 : 604800;
            !std::isfinite(duration) || std::floor(duration) != duration || duration < 1 || duration > maxDuration || !std::isfinite(accuracy) || accuracy < 0.001 || accuracy > 10000)
        {
            error = "Saved Survey-In parameters are invalid";
            return false;
        }
        surveyInTargetSeconds_ = duration;
        surveyInMonitoring_ = true;
        surveyInResultPending_ = true;
        commands = buildBaseSurveyInCommand(static_cast<uint32_t>(duration), accuracy, detected, options);
        return true;
    }

    JsonObjectConst coords = base["coords"].as<JsonObjectConst>();
    if (coords.isNull())
        coords = base;
    const auto lat = configNumber(coords["lat"], NAN);
    const auto lon = configNumber(coords["lon"], NAN);
    const auto alt = configNumber(coords["alt"], NAN);
    const auto accuracy = configNumber(base["accuracy"], 0.01);
    if (!std::isfinite(lat) || !std::isfinite(lon) || !std::isfinite(alt) || std::abs(lat) > 90 || std::abs(lon) > 180 || alt < -12000 || alt > 100000 || !std::isfinite(accuracy) || accuracy < 0.0001 || accuracy > 10000)
    {
        error = "Saved Fixed LLA coordinates or accuracy are invalid";
        return false;
    }
    position.latitude = lat;
    position.longitude = lon;
    position.altitude = alt;
    if (detected == GnssSensorType::Unicore)
    {
        const String reference = base["altitude_reference"] | "LEGACY";
        if (reference != "ELLIPSOID" && reference != "LEGACY")
        {
            error = "Unsupported saved altitude reference";
            return false;
        }
        if (reference == "ELLIPSOID")
        {
            position.ellipsoid = true;
            const String zero = "config undulation 0.0\r\n";
            commands.emplace_back(zero.begin(), zero.end());
        }
    }
    const CommandList fixed = buildBaseFixedLlaCommand(lat, lon, alt, accuracy, detected, options);
    commands.insert(commands.end(), fixed.begin(), fixed.end());
    return true;
}

bool BackendAgent::verifyStartupReadback(GnssCmdBuilder::GnssSensorType detected,
                                         bool restoreFixed, const StartupPosition &expected,
                                         String &error)
{
    DynamicJsonDocument readback(2048);
    deserializeJson(readback, receiverBaseReadback_.c_str());

    if (const String expected = restoreFixed ? "base" : "survey_in";
        String(readback["mode_kind"] | "") != expected)
    {
        error = "Receiver mode does not match startup configuration";
        return false;
    }
    if (!restoreFixed)
        return true;

    const JsonObjectConst position = readback["bestpos"].as<JsonObjectConst>();
    if (position["state"] != "ok" || position["position_type"] != "FIXEDPOS")
    {
        error = "Receiver has not confirmed the saved fixed position";
        return false;
    }
    auto lat = 0;
    auto lon = 0;
    auto height = 0;
    if (detected == GnssCmdBuilder::GnssSensorType::Ublox)
    {
        lat = position["lat"].as<double>();
        lon = position["lon"].as<double>();
        height = position["alt"].as<double>();
    }
    else
    {
        const auto raw = position["raw"] | String();
        const auto separator = raw.indexOf(';');
        double undulation = 0.0;
        if (std::array<char, 16> datum{};
            separator < 0 || std::sscanf(raw.c_str() + separator + 1, "%*[^,],%*[^,],%lf,%lf,%lf,%lf,%15[^,]", &lat, &lon, &height, &undulation, datum.data()) != 5 || std::strcmp(datum.data(), "WGS84") != 0)
        {
            error = "Receiver fixed-coordinate readback is invalid";
            return false;
        }
        if (expected.ellipsoid)
            height += undulation;
    }
    if (!std::isfinite(lat) || !std::isfinite(lon) || !std::isfinite(height) || std::abs(lat - expected.latitude) > 1e-8 || std::abs(lon - expected.longitude) > 1e-8 || std::abs(height - expected.altitude) > 0.002)
    {
        error = "Receiver fixed coordinates do not match the saved coordinates";
        return false;
    }
    return true;
}

bool BackendAgent::initializeBaseAtBoot(GnssCmdBuilder::GnssSensorType detected)
{
    using namespace GnssCmdBuilder;
    if (baseStartupAttempted_)
        return baseStartupState_ != "error";
    if (detected == GnssSensorType::Invalid)
    {
        sensorType_ = "UNKNOWN";
        baseStartupState_ = "awaiting_receiver";
        markStatusDirty();
        return false;
    }
    baseStartupAttempted_ = true;
    sensorType_ = detected == GnssSensorType::Unicore ? "Unicorecomm" : "Ublox";
    const auto fail = [&](const String &error)
    {
        baseStartupState_ = "error";
        baseStartupError_ = error;
        Serial.printf("[GNSS][STARTUP][ERROR] %s\n", error.c_str());
        markStatusDirty();
        return false;
    };
    DynamicJsonDocument config(CONFIG_DOCUMENT_SIZE);
    JsonObject base;
    auto saved = false;
    String method;
    if (String configError;
        !prepareStartupConfig(config, base, saved, method, configError))
        return fail(configError);
    if (stationLock_.all)
    {
        baseStartupState_ = "locked";
        markStatusDirty();
        return true;
    }
    if (method == "AUTO_CORS")
    {
        baseStartupState_ = "preserved";
        markStatusDirty();
        return true;
    }
    if (String queryError; !readStartupReceiverMode(detected, queryError))
        return fail(queryError.isEmpty() ? String("Receiver mode could not be read") : queryError);
    const auto restoreFixed = method == "FIXED_LLA";
    if (!restoreFixed && !method.isEmpty() && method != "SURVEY_IN")
        return fail("Unsupported saved Base mode");
    CommandList commands;
    StartupPosition position;
    if (String commandError;
        !buildStartupCommands(base, detected, restoreFixed, commands, position, commandError))
        return fail(commandError);
    if (!commands.empty() && !writeGnssCommands(commands))
        return fail("Receiver rejected startup configuration");
    if (!saved)
    {
        baseConfig_.clear();
        serializeJson(config, baseConfig_);
    }
    if (!saveStatePreferences())
        return fail("Could not save Base configuration");
    baseStartupState_ = restoreFixed ? "fixed_restored"
                                     : "survey_started";
    lastReceiverPollMs_ = 0;
    String error;
    if (!refreshReceiverReadback(error))
        return fail(error);
    if (!verifyStartupReadback(detected, restoreFixed, position, error))
        return fail(error);
    Serial.printf("[GNSS][STARTUP] %s; chip=%s\n", baseStartupState_.c_str(), sensorType_.c_str());
    markStatusDirty();
    return true;
}
