#include "functions/backend/Backend_Agent.h"
#include "functions/backend/Backend_Agent_Internal.h"
#include "functions/gnss/Ublox_Readback.h"
#include "functions/gnss/Unicore_Readback.h"
#include "hardware/Connection_type.h"
#include "hardware/Sim_handler.h"
#include "hardware/Wifi_handler.h"
#include <array>
#include <cmath>
#include <cstdlib>
#include <cstdio>
#include <cstring>

using namespace BackendAgentInternal;

namespace
{
    constexpr uint32_t AUTO_SURVEY_IN_SECONDS = 120;
    static_assert(GnssCmdBuilder::BASE_ACCURACY_METERS == 5.0f, "Base accuracy must remain 5 m");

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

bool BackendAgent::buildStartupCommands(JsonObjectConst base,
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
    options.outputMode = restoreFixed || String(output["output_mode"] | "rtcm_only") == "rtcm_only"
                             ? OutputMode::RtcmOnly
                             : OutputMode::DiagnosticsRtcm;
    const String defaultLevel = restoreFixed ? "4" : "both";
    if (const String level = output["msm_level"].isNull() ? defaultLevel : output["msm_level"].as<String>(); level == "7")
        options.msmLevel = MsmLevel::Msm7;
    else if (level == "both" || (!restoreFixed && level != "4"))
        options.msmLevel = MsmLevel::Both;
    else
        options.msmLevel = MsmLevel::Msm4;
    const JsonObjectConst systems = output["constellations"].as<JsonObjectConst>();
    options.gps = systems["gps"] | true;
    options.glo = systems["glo"] | true;
    options.gal = systems["gal"] | true;
    options.bds = systems["bds"] | true;
    options.qzss = systems["qzss"] | !restoreFixed;
    options.sbas = systems["sbas"] | !restoreFixed;
    position.ellipsoid = detected == GnssSensorType::Ublox;
    if (!restoreFixed)
    {
        const double duration = configNumber(base["survey_in_duration"], AUTO_SURVEY_IN_SECONDS);
        const auto accuracy = GnssCmdBuilder::BASE_ACCURACY_METERS;
        if (const auto maxDuration = detected == GnssSensorType::Unicore ? 3600U : 604800U;
            !std::isfinite(duration) || std::floor(duration) != duration || duration < 1 || duration > maxDuration)
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
    const auto accuracy = GnssCmdBuilder::BASE_ACCURACY_METERS;
    if (!std::isfinite(lat) || !std::isfinite(lon) || !std::isfinite(alt) || std::abs(lat) > 90 || std::abs(lon) > 180 || alt < -12000 || alt > 100000)
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

    if (const String expectedMode = restoreFixed ? "base" : "survey_in";
        readback["state"] != "ok" || String(readback["mode_kind"] | "") != expectedMode)
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
    double lat = 0.0;
    double lon = 0.0;
    double height = 0.0;
    if (detected == GnssCmdBuilder::GnssSensorType::Ublox)
    {
        lat = configNumber(position["lat"], NAN);
        lon = configNumber(position["lon"], NAN);
        height = configNumber(position["alt"], NAN);
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

void BackendAgent::reconcileBaseStartupReadback()
{
    // Only retry delayed position confirmation, never command or persistence errors.
    if (baseStartupState_ != "error" || baseStartupError_ != "Receiver has not confirmed the saved fixed position")
        return;

    DynamicJsonDocument config(CONFIG_DOCUMENT_SIZE);
    if (deserializeJson(config, baseConfig_) != DeserializationError::Ok || config["base_setup_method"] != "FIXED_LLA")
        return;
    JsonObjectConst base = config.as<JsonObjectConst>();
    JsonObjectConst coords = base["coords"].as<JsonObjectConst>();
    if (coords.isNull())
        coords = base;
    StartupPosition expected;
    expected.latitude = configNumber(coords["lat"], NAN);
    expected.longitude = configNumber(coords["lon"], NAN);
    expected.altitude = configNumber(coords["alt"], NAN);
    const auto chip = GnssCmdBuilder::sensorTypeFromString(sensorType_);
    if (chip == GnssCmdBuilder::GnssSensorType::Invalid || !std::isfinite(expected.latitude)
        || !std::isfinite(expected.longitude) || !std::isfinite(expected.altitude))
        return;
    const String reference = base["altitude_reference"] | "LEGACY";
    if (chip == GnssCmdBuilder::GnssSensorType::Unicore && reference != "ELLIPSOID" && reference != "LEGACY")
        return;
    expected.ellipsoid = chip == GnssCmdBuilder::GnssSensorType::Ublox || reference == "ELLIPSOID";
    if (String error; !verifyStartupReadback(chip, true, expected, error))
        return;
    baseStartupState_ = "fixed_restored";
    baseStartupError_.clear();
    markStatusDirty();
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
    if (deserializeJson(config, baseConfig_) != DeserializationError::Ok || !config.is<JsonObject>())
        return fail("Saved Base configuration is invalid");
    if (stationLock_.all)
    {
        baseStartupState_ = "locked";
        markStatusDirty();
        return true;
    }
    JsonObject base = config.as<JsonObject>();
    base["base_setup_method"] = "AUTO_CORS";
    base["auto_cors_source_mode"] = "nearest";
    base["mode"] = "BASE";
    base.remove("coords");
    // Do not restore a snapshot from a previous boot after a failed new run.
    base.remove("auto_base_previous_config");
    if (!base["gnss_options"].is<JsonObject>())
    {
        JsonObject options = base.createNestedObject("gnss_options");
        options["output_mode"] = "rtcm_only";
        options["msm_level"] = "both";
    }
    if (config.overflowed())
        return fail("Auto Base startup configuration exceeds memory capacity");
    baseConfig_.clear();
    serializeJson(config, baseConfig_);
    if (!saveStatePreferences())
        return fail("Could not save Auto Base startup mode");
    baseStartupState_ = "awaiting_auto_base";
    baseStartupError_.clear();
    markStatusDirty();
    return true;
}

void BackendAgent::startBootAutoBaseWhenReady()
{
    if (baseStartupState_ != "awaiting_auto_base" || stationLock_.all || !licenseValid_ || workflowActive())
        return;
    if (isGsmConnection() ? !modem.isGprsConnected() : WiFi.status() != WL_CONNECTED)
        return;
    DynamicJsonDocument request(CONFIG_DOCUMENT_SIZE);
    request["source_mode"] = "nearest";
    request["auto_apply"] = true;
    request["startup_auto"] = true;
    request["startup_boot_id"] = statusBootId_;
    request["enable_itrf_vn2000_transform"] = false;
    request["timeout"] = 3600;
    request["samples"] = 60;
    String error;
    String detail;
    baseStartupState_ = "auto_base_running";
    if (!executeAutoBaseCommand(request.as<JsonObject>(), error, detail))
    {
        baseStartupState_ = "error";
        baseStartupError_ = error;
        markStatusDirty();
    }
}
