#include "functions/backend/Backend_Agent.h"
#include "functions/backend/Backend_Agent_Internal.h"
#include "functions/gnss/Ublox_Readback.h"
#include "functions/gnss/Unicore_Readback.h"
#include "functions/gnss/Unicore_Config_Verification.h"
#include "hardware/Connection_type.h"
#include "hardware/Sim_handler.h"
#include "hardware/Wifi_handler.h"
#include <cmath>
#include <cstdlib>
#include <cstdio>
#include <cstring>

using namespace BackendAgentInternal;

namespace {

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
    if (stationLock_.all) {
        baseStartupState_ = "locked";
        markStatusDirty();
        return true;
    }
    // A power cycle can mean the antenna has moved. Always acquire a fresh
    // position through caster AutoNearest; old Fixed LLA is never a boot policy.
    base["base_setup_method"] = "AUTO_CORS";
    base["auto_cors_source_mode"] = "nearest";
    base["mode"] = "BASE";
    base.remove("coords");
    if (!base["gnss_options"].is<JsonObject>()) {
        JsonObject options = base.createNestedObject("gnss_options");
        options["output_mode"] = "rtcm_only";
        options["msm_level"] = "both";
    }
    baseConfig_.clear();
    serializeJson(config, baseConfig_);
    if (!saveStatePreferences()) return fail("Could not save Auto Base startup mode");
    baseStartupState_ = "awaiting_auto_base";
    baseStartupError_.clear();
    markStatusDirty();
    Serial.printf("[GNSS][STARTUP] awaiting nearest CORS; chip=%s\n", sensorType_.c_str());
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

void BackendAgent::startBootAutoBaseWhenReady() {
    if (baseStartupState_ != "awaiting_auto_base" || stationLock_.all
        || !licenseValid_ || workflowActive()) return;
    // Backend/MQTT availability is unrelated to the direct caster connection.
    if (isGsmConnection() ? !modem.isGprsConnected() : WiFi.status() != WL_CONNECTED) return;
    DynamicJsonDocument request(CONFIG_DOCUMENT_SIZE);
    request["source_mode"] = "nearest";
    request["auto_apply"] = true;
    request["startup_auto"] = true;
    request["startup_boot_id"] = statusBootId_;
    request["enable_itrf_vn2000_transform"] = false;
    request["timeout"] = 3600;
    request["samples"] = 60;
    String error, detail;
    Serial.println("[AUTO BASE][BOOT] Starting local AutoNearest; backend not required.");
    if (!executeAutoBaseCommand(request.as<JsonObject>(), error, detail)) {
        baseStartupState_ = "error";
        baseStartupError_ = error;
        Serial.printf("[AUTO BASE][BOOT][ERROR] %s\n", error.c_str());
        markStatusDirty();
    }
}
