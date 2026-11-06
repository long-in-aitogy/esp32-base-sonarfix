#include "functions/backend/Backend_Agent.h"
#include "functions/backend/Backend_Agent_Internal.h"
#include "functions/gnss/Ublox_Readback.h"
#include "functions/gnss/Unicore_Readback.h"
#include "functions/gnss/Unicore_Config_Verification.h"
#include <cmath>
#include <cstdlib>
#include <cstdio>
#include <cstring>

using namespace BackendAgentInternal;

namespace {
constexpr uint32_t AUTO_SURVEY_IN_SECONDS = 120;

double configNumber(JsonVariantConst value, double fallback) {
    if (value.isNull()) return fallback;
    if (value.is<bool>()) return NAN;
    if (value.is<const char *>()) {
        const char *text = value.as<const char *>();
        char *end = nullptr;
        const double number = std::strtod(text, &end);
        return end != text && *end == '\0' && std::isfinite(number) ? number : double(NAN);
    }
    return value.is<double>() ? value.as<double>() : double(NAN);
}

bool confirmSavedFixedPosition(JsonObjectConst base, JsonObjectConst readback, bool ublox, String &error) {
    const auto reject = [&](const char *message) { error = message; return false; };
    if (readback["state"] != "ok" || readback["mode_kind"] != "base")
        return reject("Receiver mode does not match startup configuration");
    JsonObjectConst coords = base["coords"].as<JsonObjectConst>();
    if (coords.isNull()) coords = base;
    const double fixedLatitude = configNumber(coords["lat"], NAN);
    const double fixedLongitude = configNumber(coords["lon"], NAN);
    const double fixedAltitude = configNumber(coords["alt"], NAN);
    if (!std::isfinite(fixedLatitude) || !std::isfinite(fixedLongitude) || !std::isfinite(fixedAltitude))
        return reject("Saved Fixed LLA coordinates or accuracy are invalid");
    double lat = 0, lon = 0, height = 0;
    if (ublox) {
        const JsonObjectConst position = readback["bestpos"].as<JsonObjectConst>();
        if (position["state"] != "ok" || position["position_type"] != "FIXEDPOS")
            return reject("Receiver has not confirmed the saved fixed position");
        lat = configNumber(position["lat"], NAN);
        lon = configNumber(position["lon"], NAN);
        height = configNumber(position["alt"], NAN);
    } else {
        const String mode = readback["mode_raw"] | String();
        if (!UnicoreConfigVerification::parseFixedMode(mode.c_str(), lat, lon, height))
            return reject("Receiver has not confirmed the saved fixed position");
    }
    if (!std::isfinite(lat) || !std::isfinite(lon) || !std::isfinite(height)
        || std::abs(lat-fixedLatitude) > 1e-8 || std::abs(lon-fixedLongitude) > 1e-8
        || std::abs(height-fixedAltitude) > 0.002)
        return reject("Receiver fixed coordinates do not match the saved coordinates");
    return true;
}
}

bool BackendAgent::initializeBaseAtBoot(GnssCmdBuilder::GnssSensorType detected) {
    using namespace GnssCmdBuilder;
    if (baseStartupAttempted_) return baseStartupState_ != "error";
    if (detected == GnssSensorType::Invalid) {
        sensorType_ = "UNKNOWN";
        baseStartupState_ = "awaiting_receiver";
        markStatusDirty();
        return false;
    }
    baseStartupAttempted_ = true;
    sensorType_ = detected == GnssSensorType::Unicore ? "Unicorecomm" : "Ublox";
    const auto fail = [&](const String &error) {
        baseStartupState_ = "error";
        baseStartupError_ = error;
        Serial.printf("[GNSS][STARTUP][ERROR] %s\n", error.c_str());
        markStatusDirty();
        return false;
    };
    DynamicJsonDocument config(CONFIG_DOCUMENT_SIZE);
    if (deserializeJson(config, baseConfig_.c_str()) != DeserializationError::Ok || !config.is<JsonObject>())
        return fail("Saved Base configuration is invalid");
    JsonObject base = config.as<JsonObject>();
    const bool saved = base.size() > 0;
    const String method = base["base_setup_method"] | String();
    if (saved && method.isEmpty()) return fail("Saved Base mode is missing");
    if (stationLock_.all) {
        baseStartupState_ = "locked";
        markStatusDirty();
        return true;
    }
    if (method == "AUTO_CORS") {
        baseStartupState_ = "preserved";
        markStatusDirty();
        return true;
    }
    if (!method.isEmpty() && method != "FIXED_LLA" && method != "SURVEY_IN")
        return fail("Unsupported saved Base mode");
    const bool replaceFixedWithSurveyIn = method == "FIXED_LLA";
    if (!saved || replaceFixedWithSurveyIn) {
        // A saved Fixed LLA belongs to the previous power session. Start a fresh
        // Survey-In after reboot so stale coordinates are never sent again.
        base["base_setup_method"] = "SURVEY_IN";
        base["survey_in_duration"] = AUTO_SURVEY_IN_SECONDS;
        base["survey_in_accuracy"] = 5;
        base["mode"] = "BASE";
        base.remove("coords");
        base.remove("lat");
        base.remove("lon");
        base.remove("alt");
        base.remove("accuracy");
    }
    // A mode readback cannot prove that the antenna has not moved.
    // Every Survey-In boot sends a fresh survey configuration.
    bool receiverRead = false;
    String queryError;
    receiverRead = readStartupReceiverMode(detected, queryError);
    // Do not guess a mode when a receiver cannot be read reliably.
    if (!receiverRead) return fail(queryError.isEmpty() ? String("Receiver mode could not be read") : queryError);
    if (!saved) {
        JsonObject options = base.createNestedObject("gnss_options");
        options["output_mode"] = "rtcm_only";
        options["msm_level"] = "both";
    }
    GnssOptions options;
    options.ports = {"UART1"};
    const JsonObjectConst output = base["gnss_options"].as<JsonObjectConst>();
    options.outputMode = String(output["output_mode"] | "rtcm_only") == "rtcm_only"
        ? OutputMode::RtcmOnly : OutputMode::DiagnosticsRtcm;
    const String level = output["msm_level"].isNull() ? "both" : output["msm_level"].as<String>();
    options.msmLevel = level == "7" ? MsmLevel::Msm7 : level == "4" ? MsmLevel::Msm4 : MsmLevel::Both;
    const JsonObjectConst systems = output["constellations"].as<JsonObjectConst>();
    options.gps = systems["gps"] | true; options.glo = systems["glo"] | true;
    options.gal = systems["gal"] | true; options.bds = systems["bds"] | true;
    options.qzss = systems["qzss"] | true; options.sbas = systems["sbas"] | true;
    const double duration = AUTO_SURVEY_IN_SECONDS;
    const double accuracy = configNumber(base["survey_in_accuracy"], 5.0);
    const double maxDuration = detected == GnssSensorType::Unicore ? 3600 : 604800;
    if (!std::isfinite(duration) || std::floor(duration) != duration || duration < 1 || duration > maxDuration
        || !std::isfinite(accuracy) || accuracy < 0.001 || accuracy > 10000)
        return fail("Saved Survey-In parameters are invalid");
    surveyInTargetSeconds_ = duration;
    surveyInMonitoring_ = true;
    surveyInResultPending_ = true;
    surveyInResult_ = "{}";
    CommandList commands = buildBaseSurveyInCommand(static_cast<uint32_t>(duration), accuracy, detected, options);
    if (!commands.empty() && !writeGnssCommands(commands)) return fail("Receiver rejected startup configuration");
    if (!saved || replaceFixedWithSurveyIn) {
        baseConfig_.clear(); serializeJson(config, baseConfig_);
    }
    if (!saveStatePreferences()) return fail("Could not save Base configuration");
    baseStartupState_ = "survey_started";
    lastReceiverPollMs_ = 0;
    String error;
    if (!refreshReceiverReadback(error)) return fail(error);
    DynamicJsonDocument readback(2048);
    deserializeJson(readback, receiverBaseReadback_.c_str());
    const String expected = "survey_in";
    if (String(readback["mode_kind"] | "") != expected) return fail("Receiver mode does not match startup configuration");
    Serial.printf("[GNSS][STARTUP] %s; chip=%s\n", baseStartupState_.c_str(), sensorType_.c_str());
    markStatusDirty();
    return true;
}

bool BackendAgent::readStartupReceiverMode(GnssCmdBuilder::GnssSensorType detected, String &error) {
    if (detected == GnssCmdBuilder::GnssSensorType::Unicore) {
        String mode;
        return UnicoreReadback::readMode(mode, error);
    } else {
        UbxBaseStatus status;
        return UbloxReadback::readBaseStatus(status, error);
    }
}

void BackendAgent::reconcileBaseStartupReadback(JsonObjectConst readback) {
    // Only recover a pending position confirmation, never command or persistence failures.
    if (baseStartupState_ != "error"
        || baseStartupError_ != "Receiver has not confirmed the saved fixed position") return;
    DynamicJsonDocument config(CONFIG_DOCUMENT_SIZE);
    if (deserializeJson(config, baseConfig_.c_str()) != DeserializationError::Ok
        || config["base_setup_method"] != "FIXED_LLA") return;
    String error;
    if (!confirmSavedFixedPosition(config.as<JsonObjectConst>(), readback, sensorType_ == "Ublox", error)) return;
    baseStartupState_ = "fixed_restored";
    baseStartupError_.clear();
    markStatusDirty();
}
