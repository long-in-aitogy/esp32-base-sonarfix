#include "functions/backend/Backend_Agent.h"
#include "functions/backend/Backend_Agent_Internal.h"
#include "Prog_Config.h"
#include "functions/ntrip/ntrip_base.h"
#include "functions/ntrip/ntrip_rover.h"
#include "functions/ntrip/RTCM_Receiver.h"
#include "functions/backend/Base_Sample.h"
#include <array>
#include <cmath>
#include <cstring>
#include <limits>
#include <strings.h>
#include <vector>

#include "functions/gnss/Ubx_Reply.h"
#include "functions/gnss/Unicore_Reply.h"
#include <cstdio>
#include <cstdlib>

using namespace BackendAgentInternal;

extern SemaphoreHandle_t tcpStreamMutex;
extern SemaphoreHandle_t rtcmBufferMutex;

namespace
{
    double coordinateNumber(JsonVariantConst value)
    {
        if (value.isNull())
            return NAN;
        if (value.is<const char *>())
        {
            const char *text = value.as<const char *>();
            char *end = nullptr;
            const double number = std::strtod(text, &end);
            return end != text && *end == '\0' && std::isfinite(number) ? number : NAN;
        }
        return value.is<double>() ? value.as<double>() : NAN;
    }
    bool acceptAutoBaseLocationReply(JsonObjectConst response, const String &requestId,
                                     double latitude, double longitude, double altitude,
                                     JsonDocument &location)
    {
        if (response["request_id"].as<String>() != requestId)
            return false;
        JsonObjectConst result = response["location"].as<JsonObjectConst>();
        JsonObjectConst echoed = result["input_coord"].as<JsonObjectConst>();
        const double lat = coordinateNumber(echoed["lat"]);
        const double lon = coordinateNumber(echoed["lon"]);
        const double alt = coordinateNumber(echoed["alt"]);
        if (!std::isfinite(lat) || !std::isfinite(lon) || !std::isfinite(alt)
            || std::abs(lat - latitude) > 1e-9 || std::abs(lon - longitude) > 1e-9
            || std::abs(alt - altitude) > 0.00011)
            return false;
        location.set(result);
        return !location.overflowed();
    }
} // namespace

void BackendAgent::setWorkflowProgress(const String &phase, const uint8_t step,
                                       const uint8_t total, const String &details)
{
    DynamicJsonDocument progress(CONFIG_DOCUMENT_SIZE);
    progress["phase"] = phase;
    progress["step"] = step;
    progress["total_steps"] = total;
    progress["updated_at"] = epochString().toInt();

    if (!details.isEmpty())
    {
        DynamicJsonDocument extra(4096);
        if (deserializeJson(extra, details) == DeserializationError::Ok && extra.is<JsonObject>())
        {
            for (JsonPairConst pair : extra.as<JsonObjectConst>())
            {
                progress[String(pair.key().c_str())] = pair.value();
            }
        }
    }
    autoBaseProgress_.clear();
    serializeJson(progress, autoBaseProgress_);
    markStatusDirty();
}

bool BackendAgent::startWorkflow(const String &kind, const String &payload)
{
    if (workflowTask_ != nullptr)
        return false;
    workflowKind_ = kind;
    workflowPayload_ = payload;
    workflowCancelRequested_ = false;
    const BaseType_t created = xTaskCreatePinnedToCore(
        &BackendAgent::workflowTaskThunk,
        "Backend Workflow",
        12288,
        this,
        1,
        &workflowTask_,
        1);
    if (created != pdPASS)
    {
        workflowKind_ = String();
        workflowPayload_ = String();
        workflowTask_ = nullptr;
        return false;
    }
    return true;
}

void BackendAgent::requestWorkflowStop()
{
    if (workflowTask_ != nullptr)
        workflowCancelRequested_ = true;
}

// FreeRTOS TaskFunction_t requires void*. startWorkflow passes this as the context.
void BackendAgent::workflowTaskThunk(void *parameter)
{
    auto *agent = static_cast<BackendAgent *>(parameter);
    if (agent)
    {
        agent->runWorkflow();
        agent->workflowPayload_ = String();
        agent->workflowKind_ = String();
        agent->workflowCancelRequested_ = false;
        agent->workflowTask_ = nullptr;
    }
    vTaskDelete(nullptr);
}

bool BackendAgent::restartConfiguredNtrip(bool transportLocked)
{
    if (!transportLocked && (!tcpStreamMutex || xSemaphoreTake(tcpStreamMutex, pdMS_TO_TICKS(MUTEX_TIMEOUT_MS * 4)) != pdTRUE))
    {
        return false;
    }
    stopNtripRover();
    setupNTRIP();
    connectNTRIP();
    if (!transportLocked)
        xSemaphoreGive(tcpStreamMutex);
    return true;
}

int BackendAgent::loopNtripRoverLocked()
{
    if (!tcpStreamMutex || xSemaphoreTake(tcpStreamMutex, pdMS_TO_TICKS(MUTEX_TIMEOUT_MS)) != pdTRUE)
    {
        // Contention is not a caster disconnect; let the workflow retry on
        // its next pass without touching a TinyGSM socket concurrently.
        return 200;
    }
    const auto result = loopNtripRover();
    xSemaphoreGive(tcpStreamMutex);
    return result;
}

bool BackendAgent::stopNtripRoverLocked()
{
    if (!tcpStreamMutex || xSemaphoreTake(tcpStreamMutex, pdMS_TO_TICKS(MUTEX_TIMEOUT_MS * 4)) != pdTRUE)
    {
        return false;
    }
    stopNtripRover();
    xSemaphoreGive(tcpStreamMutex);
    return true;
}

bool BackendAgent::waitForUnicoreReply(UnicoreReply &reply, const bool written)
{
    const uint32_t started = millis();
    while (written && millis() - started < 8000UL)
    {
        while (Serial1.available())
        {
            if (reply.feed(static_cast<uint8_t>(Serial1.read())))
                return true;
        }
        vTaskDelay(pdMS_TO_TICKS(5));
    }
    return false;
}

void BackendAgent::handleUnicoreAck(const UnicoreReply &reply, const uint8_t *data,
                                    const size_t length)
{
    Serial.printf("[GNSS][UNICORE] ACK OK: %s\n", reply.line.data());
    if (!std::strcmp(reply.key.data(), "mode"))
    {
        String command;
        command.reserve(length);
        for (size_t i = 0; i < length; ++i)
            command += static_cast<char>(data[i]);
        command.trim();
        command.toLowerCase();
        auto target = 0;
        surveyInMonitoring_ = std::sscanf(command.c_str(), "mode base time %lu", &target) == 1 && target > 0;
        surveyInStartedMs_ = surveyInMonitoring_ ? millis() : 0;
        surveyInTargetSeconds_ = surveyInMonitoring_ ? target : 0;
        if (surveyInMonitoring_)
            surveyInResultPending_ = true;
    }
    if (!std::strcmp(reply.key.data(), "freset") || !std::strcmp(reply.key.data(), "reset"))
        delay(2000);
}

bool BackendAgent::writeUnicoreCommand(const uint8_t *data, size_t length, String &error)
{
    UnicoreReply reply(data, length);
    if (!reply.key[0])
    {
        error = "invalid Unicore ASCII command";
        return false;
    }
    if (!rtcmBufferMutex || xSemaphoreTake(rtcmBufferMutex, pdMS_TO_TICKS(MUTEX_TIMEOUT_MS)) != pdTRUE)
    {
        error = "GNSS command port is busy";
        return false;
    }
    if (!gnssSerialMutex || xSemaphoreTake(gnssSerialMutex, pdMS_TO_TICKS(MUTEX_TIMEOUT_MS)) != pdTRUE)
    {
        xSemaphoreGive(rtcmBufferMutex);
        error = "GNSS reader is busy";
        return false;
    }
    while (Serial1.available())
        Serial1.read();
    const auto written = Serial1.write(data, length) == length;
    Serial1.flush();
    const auto matched = waitForUnicoreReply(reply, written);
    xSemaphoreGive(gnssSerialMutex);
    xSemaphoreGive(rtcmBufferMutex);
    if (!written)
        error = String("Unicore UART write failed: ") + reply.key.data();
    else if (!matched)
        error = String("Unicore response timeout: ") + reply.key.data();
    else if (reply.state != UnicoreReply::State::Ok)
        error = String("Unicore rejected command: ") + reply.line.data();
    else
    {
        handleUnicoreAck(reply, data, length);
        return true;
    }
    Serial.printf("[GNSS][UNICORE][ERROR] %s\n", error.c_str());
    return false;
}

bool BackendAgent::writeGnssCommands(const GnssCmdBuilder::CommandList &commands)
{
    if (commands.empty())
        return false;
    for (const auto &command : commands)
    {
        uint32_t delayMs = 0;
        if (delayMarker(command.data(), command.size(), delayMs))
        {
            delay(delayMs);
            continue;
        }
        if (sensorType_ == "Unicorecomm")
        {
            String error;
            if (!writeUnicoreCommand(command.data(), command.size(), error))
                return false;
            continue;
        }
        if (!rtcmBufferMutex || xSemaphoreTake(rtcmBufferMutex, pdMS_TO_TICKS(MUTEX_TIMEOUT_MS)) != pdTRUE)
            return false;
        const auto written = Serial1.write(command.data(), command.size());
        Serial1.flush();
        xSemaphoreGive(rtcmBufferMutex);
        if (written != command.size())
            return false;
        delay(100);
    }
    return true;
}

bool BackendAgent::exchangeUbloxRoverCommand(const GnssCmdBuilder::Command &command,
                                             const bool poll)
{
    while (Serial1.available())
        Serial1.read();
    if (Serial1.write(command.data(), command.size()) != command.size())
        return false;
    Serial1.flush();
    UbxReply reply;
    const uint32_t started = millis();
    while (millis() - started < 1500UL)
    {
        while (Serial1.available())
        {
            if (!reply.feed(static_cast<uint8_t>(Serial1.read())))
                continue;
            if (poll && reply.frame[2] == 0x06 && reply.frame[3] == 0x71 && reply.length == 48)
            {
                const uint8_t mode = reply.frame[8];
                Serial.printf("[AUTO BASE] UBX-CFG-TMODE3 readback mode=%u (0=Rover)\n", mode);
                return mode == 0;
            }
            if (!poll && reply.length == 10 && reply.frame[2] == 0x05 && (reply.frame[3] == 0x00 || reply.frame[3] == 0x01) && reply.frame[6] == command[2] && reply.frame[7] == command[3])
            {
                Serial.printf("[AUTO BASE] UBX %02X/%02X: %s\n", command[2], command[3],
                              reply.frame[3] == 1 ? "ACK" : "NAK (chip tu choi lenh)");
                return reply.frame[3] == 1;
            }
        }
        vTaskDelay(pdMS_TO_TICKS(5));
    }
    Serial.printf("[AUTO BASE] UBX %02X/%02X: khong co %s tu chip\n",
                  command[2], command[3], poll ? "readback" : "ACK");
    return false;
}

bool BackendAgent::waitForRoverGga(const uint32_t startedMs)
{
    while (millis() - startedMs < 10000UL && !workflowCancelRequested_)
    {
        const auto snapshot = getGnssTelemetrySnapshot();
        if (snapshot.lastGgaMs != 0 && static_cast<int32_t>(snapshot.lastGgaMs - startedMs) > 0)
        {
            Serial.printf("[AUTO BASE] Rover da xac nhan, GGA UART: %s\n", snapshot.lastGga.data());
            return true;
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
    Serial.println("[AUTO BASE][ERROR] Chip o Rover nhung khong co GGA moi trong 10s");
    return false;
}

bool BackendAgent::configureUbloxRover()
{
    if (!rtcmBufferMutex || xSemaphoreTake(rtcmBufferMutex, pdMS_TO_TICKS(MUTEX_TIMEOUT_MS)) != pdTRUE)
        return false;
    if (!gnssSerialMutex || xSemaphoreTake(gnssSerialMutex, pdMS_TO_TICKS(MUTEX_TIMEOUT_MS)) != pdTRUE)
    {
        xSemaphoreGive(rtcmBufferMutex);
        return false;
    }
    for (const auto &command : GnssCmdBuilder::buildRoverCommand(GnssCmdBuilder::GnssSensorType::Ublox))
    {
        // Unsupported optional port keys must not block legacy CFG commands.
        exchangeUbloxRoverCommand(command, false);
    }
    const auto roverConfirmed = exchangeUbloxRoverCommand(
        {0xB5, 0x62, 0x06, 0x71, 0, 0, 0x77, 0x6B}, true);
    xSemaphoreGive(gnssSerialMutex);
    xSemaphoreGive(rtcmBufferMutex);
    if (!roverConfirmed)
    {
        Serial.println("[AUTO BASE][ERROR] Chua xac nhan chip o Rover; dung truoc khi ket noi caster");
        return false;
    }
    return waitForRoverGga(millis());
}

bool BackendAgent::applyRoverMode()
{
    if (sensorType_ != "Ublox" && sensorType_ != "Unicorecomm")
        return false;
    Serial.printf("[AUTO BASE] Gui lenh Rover + GGA UART cho chip %s\n", sensorType_.c_str());
    if (sensorType_ == "Unicorecomm")
    {
        return writeGnssCommands(
            GnssCmdBuilder::buildRoverCommand(GnssCmdBuilder::GnssSensorType::Unicore));
    }
    return configureUbloxRover();
}

bool BackendAgent::applyBaseCoordinates(const double latitude, const double longitude,
                                        const double altitude, JsonObjectConst base)
{
    if (!std::isfinite(latitude) || !std::isfinite(longitude) || !std::isfinite(altitude) || latitude < -90.0 || latitude > 90.0 || longitude < -180.0 || longitude > 180.0)
    {
        return false;
    }
    if (sensorType_ != "Ublox" && sensorType_ != "Unicorecomm")
        return false;
    GnssCmdBuilder::GnssOptions options;
    options.ports = {"UART1"};
    options.outputMode = GnssCmdBuilder::OutputMode::RtcmOnly;
    const JsonObjectConst output = base["gnss_options"];
    const String level = output["msm_level"].isNull() ? "4" : output["msm_level"].as<String>();
    if (level == "7")
        options.msmLevel = GnssCmdBuilder::MsmLevel::Msm7;
    else if (level == "both")
        options.msmLevel = GnssCmdBuilder::MsmLevel::Both;
    const JsonObjectConst systems = output["constellations"];
    options.gps = systems["gps"] | true;
    options.glo = systems["glo"] | true;
    options.gal = systems["gal"] | true;
    options.bds = systems["bds"] | true;
    options.qzss = systems["qzss"] | false;
    options.sbas = systems["sbas"] | false;
    return writeGnssCommands(GnssCmdBuilder::buildBaseFixedLlaCommand(
        latitude, longitude, altitude, GnssCmdBuilder::BASE_ACCURACY_METERS,
        sensorType_ == "Ublox" ? GnssCmdBuilder::GnssSensorType::Ublox
                               : GnssCmdBuilder::GnssSensorType::Unicore,
        options));
}

bool BackendAgent::restoreWorkflowBase(JsonObjectConst base)
{
    using namespace GnssCmdBuilder;
    const auto fail = [&](const String &error)
    {
        baseStartupState_ = "error";
        baseStartupError_ = error;
        markStatusDirty();
        Serial.printf("[AUTO BASE][RESTORE][ERROR] %s\n", error.c_str());
        return false;
    };
    const String method = base["base_setup_method"] | String();
    JsonObjectConst coords = base["coords"].as<JsonObjectConst>();
    if (coords.isNull())
        coords = base;
    const double lat = coordinateNumber(coords["lat"]);
    const double lon = coordinateNumber(coords["lon"]);
    const double alt = coordinateNumber(coords["alt"]);
    if ((method.isEmpty() || method == "AUTO_CORS")
        && !std::isfinite(lat) && !std::isfinite(lon) && !std::isfinite(alt))
    {
        if (!applyRoverMode())
            return fail("cannot restore unconfigured receiver to Rover mode");
        baseStartupState_ = method == "AUTO_CORS" && base["auto_cors_source_mode"] == "nearest"
            ? "awaiting_auto_base" : "awaiting_configuration";
        baseStartupError_.clear();
        markStatusDirty();
        return true;
    }
    const auto chip = GnssCmdBuilder::sensorTypeFromString(sensorType_);
    StartupPosition expected;
    String error;
    if (method == "SURVEY_IN")
    {
        const double duration = base["survey_in_duration"].isNull() ? 120 : coordinateNumber(base["survey_in_duration"]);
        const double accuracy = GnssCmdBuilder::BASE_ACCURACY_METERS;
        const double maxDuration = sensorType_ == "Unicorecomm" ? 3600 : 604800;
        if (!std::isfinite(duration) || duration < 1 || duration > maxDuration || std::floor(duration) != duration
            || !std::isfinite(accuracy) || accuracy < 0.001 || accuracy > 10000)
            return fail("invalid saved Survey-In parameters");
        GnssOptions options;
        options.ports = {"UART1"};
        const JsonObjectConst output = base["gnss_options"];
        options.outputMode = String(output["output_mode"] | "rtcm_only") == "rtcm_only"
            ? OutputMode::RtcmOnly : OutputMode::DiagnosticsRtcm;
        const String level = output["msm_level"].isNull() ? "both" : output["msm_level"].as<String>();
        options.msmLevel = level == "7" ? MsmLevel::Msm7 : level == "4" ? MsmLevel::Msm4 : MsmLevel::Both;
        const JsonObjectConst systems = output["constellations"];
        options.gps = systems["gps"] | true;
        options.glo = systems["glo"] | true;
        options.gal = systems["gal"] | true;
        options.bds = systems["bds"] | true;
        options.qzss = systems["qzss"] | true;
        options.sbas = systems["sbas"] | true;
        if (!writeGnssCommands(buildBaseSurveyInCommand(static_cast<uint32_t>(duration), accuracy, chip, options)))
            return fail("receiver rejected Survey-In restore");
        surveyInResultPending_ = true;
    }
    else
    {
        CommandList commands;
        if (!buildStartupCommands(base, chip, true, commands, expected, error))
            return fail(error);
        if (!writeGnssCommands(commands))
            return fail("receiver rejected Fixed LLA restore");
    }
    if (!refreshReceiverReadback(error)
        || !verifyStartupReadback(chip, method != "SURVEY_IN", expected, error))
        return fail(error);
    baseStartupState_ = "configured";
    baseStartupError_.clear();
    markStatusDirty();
    Serial.printf("[AUTO BASE][RESTORE] Previous %s mode confirmed\n", method.c_str());
    return true;
}

void BackendAgent::runWorkflow()
{
    DynamicJsonDocument document(COMMAND_DOCUMENT_SIZE);
    if (deserializeJson(document, workflowPayload_) != DeserializationError::Ok || !document.is<JsonObject>())
    {
        setAgentState(normalAgentState());
        setWorkflowProgress("failed", 0, 4, R"({"reason":"invalid workflow payload"})");
        saveStatePreferences();
        return;
    }

    const JsonObject payload = document.as<JsonObject>();
    const auto kind = workflowKind_;
    if (kind == "auto_base")
    {
        runAutoBaseWorkflow(payload);
    }
    else if (kind == "reference_check")
    {
        runReferenceCheckWorkflow(payload);
    }
    else
    {
        setAgentState(normalAgentState());
        setWorkflowProgress("failed", 0, 4, R"({"reason":"unknown workflow"})");
        saveStatePreferences();
    }
}

bool BackendAgent::prepareAutoBaseConfig(JsonObject payload, String &host, uint16_t &port,
                                         String &username, String &password, String &mountpoint,
                                         uint8_t &ntripVersion, uint32_t &timeoutSeconds,
                                         uint8_t &fixedStreakRequired)
{
    host = payload["ip"] | String();
    host.trim();
    const int requestedPort = payload["port"] | 0;
    port = requestedPort > 0 && requestedPort <= 65535 ? static_cast<uint16_t>(requestedPort) : 0;
    username = payload["user"] | String();
    password = payload["password"] | String();
    mountpoint = payload["mountpoint"] | String();
    ntripVersion = static_cast<uint8_t>(payload["ntrip_version"] | 1);
    timeoutSeconds = constrain(
        static_cast<uint32_t>(payload["timeout"] | 3600UL), 30UL, 86400UL);
    fixedStreakRequired = static_cast<uint8_t>(constrain(
        static_cast<int>(payload["fixed_streak_seconds"] | 5), 1, 60));
    return !host.isEmpty() && !username.isEmpty() && !password.isEmpty() && !mountpoint.isEmpty() && port != 0;
}

bool BackendAgent::startAutoBaseRover(const String &host, const uint16_t port,
                                      const String &username, const String &password,
                                      const String &mountpoint, const uint8_t ntripVersion, String &error,
                                      String *selectedMountpoint)
{
    if (!tcpStreamMutex || xSemaphoreTake(tcpStreamMutex, pdMS_TO_TICKS(MUTEX_TIMEOUT_MS)) != pdTRUE)
    {
        error = "network transport is busy";
        return false;
    }
    stopNtrip();
    const auto started = startNtripRover(host, port, username, password, mountpoint, ntripVersion,
                                         selectedMountpoint, selectedMountpoint ? serialNumber_ : String());
    if (!started)
        error = ntripRoverLastError();
    xSemaphoreGive(tcpStreamMutex);
    return started;
}

bool BackendAgent::waitForAutoBaseFix(const uint32_t timeoutSeconds,
                                      const uint8_t fixedStreakRequired, bool &cancelled,
                                      String &failureReason, const String &sourceMountpoint)
{
    const uint32_t waitStartedMs = millis();
    uint32_t nextSecondMs = waitStartedMs;
    uint8_t fixedStreak = 0;
    while (millis() - waitStartedMs < timeoutSeconds * 1000UL)
    {
        if (workflowCancelRequested_)
        {
            cancelled = true;
            failureReason = "cancelled by user";
            return false;
        }
        if (loopNtripRoverLocked() == 504)
        {
            failureReason = ntripRoverLastError();
            return false;
        }
        const uint32_t now = millis();
        if (static_cast<int32_t>(now - nextSecondMs) >= 0)
        {
            nextSecondMs = now + 1000UL;
            const GnssTelemetrySnapshot snapshot = getGnssTelemetrySnapshot();
            const auto usable = freshRtkSample(now, snapshot.lastGgaMs, snapshot.fixStatus.data());
            fixedStreak = usable ? static_cast<uint8_t>(fixedStreak + 1) : 0;
            const auto fixed = fixedStreak >= fixedStreakRequired;
            DynamicJsonDocument details(1024);
            details["source_mountpoint"] = sourceMountpoint;
            details["timeout"] = timeoutSeconds;
            details["elapsed"] = (now - waitStartedMs) / 1000UL;
            details["fix_status"] = snapshot.fixStatus.data();
            details["fixed_streak"] = fixedStreak;
            details["fixed_streak_required"] = fixedStreakRequired;
            String serialized;
            serializeJson(details, serialized);
            setWorkflowProgress("wait_fix", 2, 4, serialized);
            if (fixed)
                return true;
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
    failureReason = "RTK fix timeout";
    return false;
}

bool BackendAgent::collectAutoBaseSamples(const int configuredSamples,
                                          std::vector<double> &latitudes,
                                          std::vector<double> &longitudes,
                                          std::vector<double> &altitudes,
                                          bool &cancelled, String &failureReason,
                                          const String &sourceMountpoint)
{
    constexpr uint16_t samplesNeeded = 60;
    constexpr uint32_t averagingSeconds = 60;
    latitudes.reserve(samplesNeeded);
    longitudes.reserve(samplesNeeded);
    altitudes.reserve(samplesNeeded);
    const uint32_t averageStartedMs = millis();
    uint32_t lastSampleGgaMs = 0;
    uint32_t nextSecondMs = averageStartedMs;
    while (millis() - averageStartedMs < averagingSeconds * 1000UL && latitudes.size() < samplesNeeded)
    {
        if (workflowCancelRequested_)
        {
            cancelled = true;
            failureReason = "cancelled by user";
            return false;
        }
        if (loopNtripRoverLocked() == 504)
        {
            failureReason = ntripRoverLastError();
            return false;
        }
        const uint32_t now = millis();
        if (static_cast<int32_t>(now - nextSecondMs) >= 0)
        {
            nextSecondMs = now + 1000UL;
            const GnssTelemetrySnapshot snapshot = getGnssTelemetrySnapshot();
            const auto usable = freshRtkSample(now, snapshot.lastGgaMs, snapshot.fixStatus.data());
            if (usable && snapshot.lastGgaMs != lastSampleGgaMs && std::isfinite(snapshot.latitude) && std::isfinite(snapshot.longitude) && std::isfinite(snapshot.altitude) && snapshot.latitude >= -90.0 && snapshot.latitude <= 90.0 && snapshot.longitude >= -180.0 && snapshot.longitude <= 180.0)
            {
                lastSampleGgaMs = snapshot.lastGgaMs;
                latitudes.push_back(snapshot.latitude);
                longitudes.push_back(snapshot.longitude);
                altitudes.push_back(snapshot.altitude);
            }
            DynamicJsonDocument details(1200);
            details["source_mountpoint"] = sourceMountpoint;
            details["samples_collected"] = latitudes.size();
            details["samples_target"] = samplesNeeded;
            details["averaging_seconds"] = averagingSeconds;
            details["elapsed"] = (now - averageStartedMs) / 1000UL;
            details["fix_status"] = snapshot.fixStatus.data();
            if (configuredSamples != samplesNeeded)
                details["requested_samples_overridden"] = configuredSamples;
            if (usable)
            {
                JsonObject latest = details.createNestedObject("latest_coord");
                latest["lat"] = snapshot.latitude;
                latest["lon"] = snapshot.longitude;
                latest["alt"] = snapshot.altitude;
            }
            String serialized;
            serializeJson(details, serialized);
            setWorkflowProgress("averaging", 3, 4, serialized);
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
    if (latitudes.size() < 15)
    {
        failureReason = "insufficient valid RTK samples";
        return false;
    }
    return true;
}

String BackendAgent::buildAutoBaseResult(
    const double finalLatitude, const double finalLongitude, const double finalAltitude,
    const double rawLatitude, const double rawLongitude, const double rawAltitude,
    const bool transformed, const bool transportRestored, const size_t sampleCount,
    const String &projectionSource, const String &provinceCode, const String &provinceName,
    const double centralMeridianDeg, const double scale, JsonObjectConst report)
{
    DynamicJsonDocument completed(CONFIG_DOCUMENT_SIZE);
    completed["averaged_coord"]["lat"] = finalLatitude;
    completed["averaged_coord"]["lon"] = finalLongitude;
    completed["averaged_coord"]["alt"] = finalAltitude;
    completed["raw_itrf_coord"]["lat"] = rawLatitude;
    completed["raw_itrf_coord"]["lon"] = rawLongitude;
    completed["raw_itrf_coord"]["alt"] = rawAltitude;
    if (report["output_coord"].is<JsonObjectConst>())
        completed["averaged_coord"].set(report["output_coord"]);
    completed["raw_coord"].set(report["input_coord"]);
    completed["calculated_coord"].set(report["calculated_coord"]);
    completed["sample_count"] = sampleCount;
    completed["fixed_samples_only"] = true;
    completed["transform_applied"] = transformed;
    completed["configured_ntrip_restarted"] = transportRestored;
    completed["projection_source"] = projectionSource;
    completed["province_code"] = provinceCode;
    completed["province_name"] = provinceName;
    completed["central_meridian_deg"] = centralMeridianDeg;
    completed["k0"] = scale;
    completed["conversion_report"].set(report);
    const String mountpoint = report["source"]["mountpoint"] | String();
    if (completed.overflowed())
        return String();
    String serialized;
    serializeJson(completed, serialized);
    DynamicJsonDocument checked(CONFIG_DOCUMENT_SIZE), progress(CONFIG_DOCUMENT_SIZE);
    if (deserializeJson(checked, serialized) != DeserializationError::Ok)
        return String();
    checked["source_mountpoint"] = mountpoint;
    checked["auto_applied"] = true;
    checked["receiver_write_completed"] = true;
    progress["phase"] = String("ready_for_review");
    progress["step"] = 4;
    progress["total_steps"] = 4;
    progress["updated_at"] = 0;
    for (JsonPairConst pair : checked.as<JsonObjectConst>())
        progress[String(pair.key().c_str())] = pair.value();
    if (checked.overflowed() || progress.overflowed())
        return String();
    return serialized;
}

bool BackendAgent::completeAutoBaseSetup(
    JsonObject payload, const std::vector<double> &latitudes,
    const std::vector<double> &longitudes, const std::vector<double> &altitudes,
    String &resultJson, String &failureReason, const String &sourceMountpoint)
{
    auto rawLatitude = 0.0;
    auto rawLongitude = 0.0;
    auto rawAltitude = 0.0;
    for (size_t index = 0; index < latitudes.size(); ++index)
    {
        rawLatitude += latitudes[index];
        rawLongitude += longitudes[index];
        rawAltitude += altitudes[index];
    }
    rawLatitude /= latitudes.size();
    rawLongitude /= longitudes.size();
    rawAltitude /= altitudes.size();

    double centralMeridianDeg = 0.0;
    double scale = 0.0;
    String provinceName;
    String provinceCode;
    String host = payload["ip"] | String();
    host.trim();
    const bool vngeonet = strcasecmp(host.c_str(), "vngeonet.vn") == 0
        || strcasecmp(host.c_str(), "vngeonet.vn.") == 0 || host == "14.238.1.125";
    const bool requestedTransform = vngeonet && (payload["enable_itrf_vn2000_transform"] | true);
    const char *projectionSource = "not_used";
    bool transformed = false;
    Vn2000Datum datum;
    DynamicJsonDocument location(2048);
    double projectedHeight = rawAltitude;
    ProjectedPosition result{rawLatitude, rawLongitude, rawAltitude};
    if (requestedTransform)
    {
        if (!tcpStreamMutex || xSemaphoreTake(tcpStreamMutex, pdMS_TO_TICKS(MUTEX_TIMEOUT_MS * 4)) != pdTRUE)
        {
            failureReason = "cannot acquire rover transport for datum readback";
            return false;
        }
        datum = ntripRoverDatum();
        xSemaphoreGive(tcpStreamMutex);
        if (!datum.has1021)
        {
            failureReason = "missing RTCM 1021 from this CORS session";
            return false;
        }
        if (datum.has1025)
            projectionSource = "rtcm1025";
        else if (!payload["l0_deg"].isNull() && !payload["k0"].isNull())
        {
            datum.centralMeridianDeg = coordinateNumber(payload["l0_deg"]);
            datum.scale = coordinateNumber(payload["k0"]);
            projectionSource = "manual";
        }
        else
        {
            if (!autoBaseLocationQueue_)
            {
                failureReason = "location reply queue could not be allocated";
                return false;
            }
            if (!stopNtripRoverLocked())
            {
                failureReason = "cannot stop rover transport for location lookup";
                return false;
            }
            xQueueReset(autoBaseLocationQueue_);
            const String requestId = statusBootId_ + ":" + String(millis());
            StaticJsonDocument<384> requestDoc;
            JsonObject request = requestDoc.createNestedObject("location_request");
            request["request_id"] = requestId;
            char value[32];
            snprintf(value, sizeof(value), "%.17g", rawLatitude); request["lat"] = String(value);
            snprintf(value, sizeof(value), "%.17g", rawLongitude); request["lon"] = String(value);
            snprintf(value, sizeof(value), "%.17g", rawAltitude); request["alt"] = String(value);
            String requestJson;
            serializeJson(requestDoc, requestJson);
            setWorkflowProgress("resolving_location", 4, 4, requestJson);
            DynamicJsonDocument received(2048);
            AutoBaseLocationReply reply{};
            const uint32_t started = millis();
            bool located = false;
            while (!workflowCancelRequested_ && millis() - started < 30000UL)
            {
                if (xQueueReceive(autoBaseLocationQueue_, &reply, pdMS_TO_TICKS(50)) == pdTRUE
                    && deserializeJson(received, static_cast<const char *>(reply.json)) == DeserializationError::Ok
                    && acceptAutoBaseLocationReply(received.as<JsonObjectConst>(), requestId,
                                                   rawLatitude, rawLongitude, rawAltitude, location))
                {
                    located = true;
                    break;
                }
            }
            if (!located || workflowCancelRequested_)
            {
                failureReason = workflowCancelRequested_ ? "cancelled by user" : "backend location ACK timed out or did not match sampled LLH";
                return false;
            }
            datum.centralMeridianDeg = coordinateNumber(location["l0_deg"]);
            datum.scale = coordinateNumber(location["k0"]);
            if (!std::isfinite(datum.centralMeridianDeg) || !std::isfinite(datum.scale))
            {
                failureReason = "province projection unresolved; RTCM 1025 or a unique server region is required";
                return false;
            }
            provinceCode = location["province_code"] | String();
            provinceName = location["province_name"] | String();
            projectionSource = "server_catalog";
        }
        for (const char *key : {"resN", "resE", "resHS"})
        {
            const double value = payload[key].isNull() ? 0 : coordinateNumber(payload[key]);
            if (!std::isfinite(value))
            {
                failureReason = "invalid CORS shift";
                return false;
            }
            if (!std::strcmp(key, "resN")) datum.resN = value;
            else if (!std::strcmp(key, "resE")) datum.resE = value;
            else datum.resHS = value;
        }
        Vn2000Result converted;
        if (!transformVn2000(rawLatitude, rawLongitude, rawAltitude, datum, converted))
        {
            failureReason = "VN2000 conversion failed; no candidate coordinates were installed";
            return false;
        }
        result = {converted.latitude, converted.longitude, converted.altitude, converted.north, converted.east};
        projectedHeight = converted.h;
        centralMeridianDeg = datum.centralMeridianDeg;
        scale = datum.scale;
        transformed = true;
    }
    if (!std::isfinite(result.latitude) || !std::isfinite(result.longitude) || !std::isfinite(result.altitude)
        || std::abs(result.latitude) > 90.0 || std::abs(result.longitude) > 180.0
        || result.altitude < -12000.0 || result.altitude > 100000.0)
    {
        failureReason = "Auto Base result coordinates are invalid";
        return false;
    }
    DynamicJsonDocument report(CONFIG_DOCUMENT_SIZE);
    const auto numberText = [](double number)
    {
        char text[32];
        snprintf(text, sizeof(text), "%.17g", number);
        return String(text);
    };
    report["version"] = 1;
    report["input_coord"]["lat"] = numberText(rawLatitude);
    report["input_coord"]["lon"] = numberText(rawLongitude);
    report["input_coord"]["alt"] = numberText(rawAltitude);
    report["calculated_coord"]["lat"] = numberText(result.latitude);
    report["calculated_coord"]["lon"] = numberText(result.longitude);
    report["calculated_coord"]["alt"] = numberText(result.altitude);
    const auto receiverCoordinate = [&](double value, bool altitude)
    {
        if (sensorType_ == "Ublox")
        {
            const double scale = altitude ? 100.0 : 10000000.0;
            const double scaled = value * scale;
            const auto whole = static_cast<int32_t>(scaled);
            const auto highPrecision = static_cast<int8_t>((scaled - whole) * 100);
            return String((whole + highPrecision / 100.0) / scale, altitude ? 4 : 9);
        }
        if (altitude)
            return String(value, 4);
        double scaled = value * 1e10;
        const double integer = std::round(scaled);
        if (std::abs(scaled - integer) <= 4 * std::numeric_limits<double>::epsilon() * std::fmax(1.0, std::abs(scaled)))
            scaled = integer;
        return String(std::trunc(scaled) / 1e10, 10);
    };
    report["output_coord"]["lat"] = receiverCoordinate(result.latitude, false);
    report["output_coord"]["lon"] = receiverCoordinate(result.longitude, false);
    report["output_coord"]["alt"] = receiverCoordinate(result.altitude, true);
    report["source"]["host"] = host;
    report["source"]["port"] = payload["port"];
    report["source"]["mountpoint"] = sourceMountpoint;
    if (!String(payload["source_name"] | "").isEmpty()) report["source"]["station_name"] = payload["source_name"];
    if (!String(payload["source_serial"] | "").isEmpty()) report["source"]["station_serial"] = payload["source_serial"];
    if (!payload["source_distance_m"].isNull()) report["source"]["distance_m"] = payload["source_distance_m"];
    if (payload["source_mode"] == "nearest")
        report["source"]["requested_mountpoint"] = payload["mountpoint"];
    report["input_reference"] = "receiver_reported";
    report["output_reference"] = transformed ? "local_llh" : "receiver_reported";
    report["altitude_reference"] = "ELLIPSOID";
    report["transform_requested"] = requestedTransform;
    report["transform_applied"] = transformed;
    report["receiver_write_completed"] = false;
    report["auto_applied"] = false;
    report["reason"] = transformed ? "applied" : "disabled";
    report["sample_count"] = latitudes.size();
    report["processor"] = "esp32";
    report["province_code"] = provinceCode;
    report["province_name"] = provinceName;
    report["location"].set(location.as<JsonObjectConst>());
    report["projection_source"] = projectionSource;
    report["central_meridian_deg"] = numberText(centralMeridianDeg);
    report["k0"] = numberText(scale);
    if (transformed && std::abs(scale - 0.9999) < 1e-9)
        report["zone_width_deg"] = 3;
    else if (transformed && std::abs(scale - 0.9996) < 1e-9)
        report["zone_width_deg"] = 6;
    if (vngeonet && transformed)
    {
        report["zone_width_source"] = "inferred_from_k0";
        report["parameter_source"] = "rtcm1021";
        report["residual_source"] = datum.has1023 ? "rtcm1023" : "none";
        report["rtcm1025_used"] = datum.has1025;
        if (datum.has1025)
        {
            JsonObject projection = report.createNestedObject("rtcm1025");
            projection["raw_l0"] = String(static_cast<long long>(datum.projectionLongitudeRaw));
            projection["raw_k0"] = datum.projectionScaleRaw;
            projection["projection_type"] = datum.projectionType;
            projection["l0_deg"] = numberText(datum.centralMeridianDeg);
            projection["k0"] = numberText(datum.scale);
            projection["false_easting"] = numberText(datum.falseEasting);
            projection["false_northing"] = numberText(datum.falseNorthing);
            projection["frame_hex"] = datum.projectionFrameHex;
            projection["frame_bytes"] = datum.projectionFrameBytes;
            projection["frame_truncated"] = datum.projectionFrameBytes > 32;
        }
        report["received_messages"]["1021"] = datum.count1021;
        report["received_messages"]["1023"] = datum.count1023;
        report["received_messages"]["1025"] = datum.count1025;
        report["projected_coord"]["north"] = numberText(result.northing);
        report["projected_coord"]["east"] = numberText(result.easting);
        report["projected_coord"]["h"] = numberText(projectedHeight);
        JsonObject parameters = report.createNestedObject("parameters");
        parameters["dX"] = numberText(datum.dX); parameters["dY"] = numberText(datum.dY); parameters["dZ"] = numberText(datum.dZ);
        parameters["rX"] = numberText(datum.rX); parameters["rY"] = numberText(datum.rY); parameters["rZ"] = numberText(datum.rZ);
        parameters["kT"] = numberText(datum.kT);
        parameters["resB"] = numberText(datum.resB); parameters["resL"] = numberText(datum.resL); parameters["resH"] = numberText(datum.resH);
        parameters["resN"] = numberText(datum.resN); parameters["resE"] = numberText(datum.resE); parameters["resHS"] = numberText(datum.resHS);
    }
    else
        report["parameter_source"] = transformed ? "legacy_fixed" : "not_used";
    if (report.overflowed())
    {
        failureReason = "Auto Base report exceeds memory capacity";
        return false;
    }
    resultJson = buildAutoBaseResult(
        result.latitude, result.longitude, result.altitude, rawLatitude, rawLongitude, rawAltitude,
        transformed, false, latitudes.size(), projectionSource,
        provinceCode, provinceName, centralMeridianDeg, scale, report.as<JsonObjectConst>());
    if (resultJson.isEmpty())
    {
        failureReason = "Auto Base result exceeds memory capacity";
        return false;
    }
    if (!(payload["auto_apply"] | false))
        return true;
    resultJson.clear();

    setAgentState("auto_setup_base");
    DynamicJsonDocument baseProgress(2048);
    baseProgress["averaged_coord"]["lat"] = result.latitude;
    baseProgress["averaged_coord"]["lon"] = result.longitude;
    baseProgress["averaged_coord"]["alt"] = result.altitude;
    baseProgress["sample_count"] = latitudes.size();
    baseProgress["transform_applied"] = transformed;
    baseProgress["projection_source"] = projectionSource;
    baseProgress["province_code"] = provinceCode;
    baseProgress["province_name"] = provinceName;
    baseProgress["central_meridian_deg"] = centralMeridianDeg;
    baseProgress["k0"] = scale;
    String baseProgressJson;
    serializeJson(baseProgress, baseProgressJson);
    setWorkflowProgress("set_base", 4, 4, baseProgressJson);

    DynamicJsonDocument baseConfig(CONFIG_DOCUMENT_SIZE);
    if (deserializeJson(baseConfig, baseConfig_) != DeserializationError::Ok || !baseConfig.is<JsonObject>())
    {
        failureReason = "cannot read previous Base configuration";
        return false;
    }
    bool removedOldData = false;
    for (const char *key : {"auto_base_previous_config", "coords", "auto_base_raw_itrf_llh", "conversion_report"})
    {
        if (baseConfig.containsKey(key))
        {
            baseConfig.remove(key);
            removedOldData = true;
        }
    }
    if (removedOldData && !baseConfig.garbageCollect())
    {
        failureReason = "cannot allocate Auto Base configuration";
        return false;
    }
    JsonObject coordinates = baseConfig.createNestedObject("coords");
    coordinates["lat"] = result.latitude;
    coordinates["lon"] = result.longitude;
    coordinates["alt"] = result.altitude;
    coordinates["accuracy"] = GnssCmdBuilder::BASE_ACCURACY_METERS;
    coordinates["altitude_reference"] = "ELLIPSOID";
    baseConfig["altitude_reference"] = "ELLIPSOID";
    baseConfig["accuracy"] = GnssCmdBuilder::BASE_ACCURACY_METERS;
    if (!baseConfig["survey_in_accuracy"].isUnbound())
        baseConfig["survey_in_accuracy"] = GnssCmdBuilder::BASE_ACCURACY_METERS;
    baseConfig["base_setup_method"] = "FIXED_LLA";
    baseConfig["auto_cors_source_mode"] = "nearest";
    baseConfig["coordinate_source"] = "AUTO_CORS";
    baseConfig["mode"] = "BASE";
    if (!baseConfig["gnss_options"].is<JsonObject>())
        baseConfig.createNestedObject("gnss_options");
    JsonObject options = baseConfig["gnss_options"].as<JsonObject>();
    options["output_mode"] = "rtcm_only";
    if (options["msm_level"].isNull())
        options["msm_level"] = "4";
    if (!options["constellations"].is<JsonObject>())
        options.createNestedObject("constellations");
    JsonObject constellations = options["constellations"].as<JsonObject>();
    if (constellations["qzss"].isNull())
        constellations["qzss"] = false;
    if (constellations["sbas"].isNull())
        constellations["sbas"] = false;
    baseConfig["auto_configured"] = true;
    baseConfig["fixed_samples_only"] = true;
    baseConfig["itrf_vn2000_transform_applied"] = transformed;
    baseConfig["central_meridian_deg"] = centralMeridianDeg;
    baseConfig["k0"] = scale;
    baseConfig["projection_source"] = projectionSource;
    baseConfig["province_code"] = provinceCode;
    baseConfig["province_name"] = provinceName;
    baseConfig["vn2000_northing"] = result.northing;
    baseConfig["vn2000_easting"] = result.easting;
    JsonObject raw = baseConfig.createNestedObject("auto_base_raw_itrf_llh");
    raw["lat"] = rawLatitude;
    raw["lon"] = rawLongitude;
    raw["alt"] = rawAltitude;
    baseConfig["conversion_report"].set(report.as<JsonObjectConst>());
    if (baseConfig.overflowed())
    {
        failureReason = "Auto Base configuration exceeds memory capacity";
        return false;
    }
    if (!stopNtripRoverLocked())
    {
        failureReason = "cannot acquire transport lock to stop CORS rover session";
        return false;
    }
    if (!restoreWorkflowBase(baseConfig.as<JsonObjectConst>()))
    {
        failureReason = "receiver did not confirm automatically measured Fixed LLA";
        return false;
    }

    report["receiver_write_completed"] = true;
    report["auto_applied"] = true;
    baseConfig["conversion_report"]["receiver_write_completed"] = true;
    baseConfig["conversion_report"]["auto_applied"] = true;
    const String previousConfig = baseConfig_;
    baseConfig_.clear();
    serializeJson(baseConfig, baseConfig_);
    if (!saveStatePreferences())
    {
        baseConfig_ = previousConfig;
        failureReason = "could not save automatically applied Fixed LLA";
        return false;
    }
    const auto transportRestored = restartConfiguredNtrip();
    if (!transportRestored)
    {
        baseConfig_ = previousConfig;
        failureReason = saveStatePreferences()
            ? "could not restore configured NTRIP after applying Fixed LLA"
            : "could not save previous Base configuration after NTRIP restore failed";
        return false;
    }
    publishConfigState("base_config_state");
    setAgentState(normalAgentState());
    resultJson = buildAutoBaseResult(
        result.latitude, result.longitude, result.altitude, rawLatitude, rawLongitude, rawAltitude,
        transformed, transportRestored, latitudes.size(), projectionSource,
        provinceCode, provinceName, centralMeridianDeg, scale, report.as<JsonObjectConst>());
    if (resultJson.isEmpty())
    {
        failureReason = "cannot allocate Auto Base result";
        return false;
    }
    Serial.printf("[AUTO BASE] KET QUA: THANH CONG; samples=%u; lat=%.10f; lon=%.10f; alt=%.4f\n",
                  static_cast<unsigned>(latitudes.size()), result.latitude, result.longitude,
                  result.altitude);
    return true;
}

bool BackendAgent::runAutoBaseWorkflow(JsonObject payload)
{
    String host;
    uint16_t port = 0;
    String username;
    String password;
    String mountpoint;
    uint8_t ntripVersion = 0;
    uint32_t timeoutSeconds = 0;
    uint8_t fixedStreakRequired = 0;
    const auto validConfig = prepareAutoBaseConfig(
        payload, host, port, username, password, mountpoint, ntripVersion,
        timeoutSeconds, fixedStreakRequired);

    if (!validConfig)
    {
        setAgentState(normalAgentState());
        setWorkflowProgress("failed", 0, 4, R"({"reason":"missing or invalid CORS connection fields"})");
        saveStatePreferences();
        return false;
    }

    const bool autoNearest = payload["source_mode"] == "nearest";
    String selectedMountpoint;
    DynamicJsonDocument previousBase(CONFIG_DOCUMENT_SIZE);
    deserializeJson(previousBase, baseConfig_);
    const JsonObjectConst savedPrevious = previousBase["auto_base_previous_config"].as<JsonObjectConst>();
    const bool hasSavedPrevious = !savedPrevious.isNull();
    if (hasSavedPrevious)
    {
        DynamicJsonDocument snapshot(CONFIG_DOCUMENT_SIZE);
        snapshot.set(savedPrevious);
        previousBase.set(snapshot.as<JsonObjectConst>());
    }
    // Startup may use a different duration from the saved UI preference.
    if (previousBase.size() == 0 && surveyInTargetSeconds_ > 0)
        previousBase["base_setup_method"] = "SURVEY_IN";
    if (previousBase["base_setup_method"] == "SURVEY_IN" && surveyInTargetSeconds_ > 0)
        previousBase["survey_in_duration"] = surveyInTargetSeconds_;

    auto finish = [&](const bool success, const bool cancelled, const String &reason)
    {
        const bool roverStopped = stopNtripRoverLocked();
        const bool baseRestored = roverStopped && restoreWorkflowBase(previousBase.as<JsonObjectConst>());
        const bool transportRestored = baseRestored && restartConfiguredNtrip();
        bool cleanupSucceeded = baseRestored && transportRestored;
        if (cleanupSucceeded && hasSavedPrevious)
        {
            const String pendingConfig = baseConfig_;
            baseConfig_.clear();
            serializeJson(previousBase, baseConfig_);
            if (saveStatePreferences())
                publishConfigState("base_config_state");
            else
            {
                baseConfig_ = pendingConfig;
                cleanupSucceeded = false;
            }
        }
        if (cancelled && cleanupSucceeded && previousBase["base_setup_method"] == "AUTO_CORS"
            && previousBase["auto_cors_source_mode"] == "nearest")
        {
            JsonObjectConst coords = previousBase["coords"].as<JsonObjectConst>();
            if (coords.isNull())
                coords = previousBase.as<JsonObjectConst>();
            if (!std::isfinite(coordinateNumber(coords["lat"]))
                || !std::isfinite(coordinateNumber(coords["lon"]))
                || !std::isfinite(coordinateNumber(coords["alt"])))
            {
                baseStartupState_ = "awaiting_configuration";
                markStatusDirty();
            }
        }
        setAgentState(normalAgentState());
        DynamicJsonDocument details(1024);
        if (!selectedMountpoint.isEmpty())
            details["source_mountpoint"] = selectedMountpoint;
        if (!reason.isEmpty())
            details["reason"] = reason;
        if (!cleanupSucceeded)
            details["cleanup_error"] = "could not safely restore base/NTRIP state";
        String serialized;
        serializeJson(details, serialized);
        const char *unfinishedStage = cancelled && cleanupSucceeded ? "stopped" : "failed";
        const char *unfinishedResult = cancelled && cleanupSucceeded ? "DA DUNG" : "THAT BAI";
        setWorkflowProgress(success && cleanupSucceeded ? "completed" : unfinishedStage, success && cleanupSucceeded ? 4 : 2, 4, serialized);
        Serial.printf("[AUTO BASE] KET QUA: %s; %s\n", success && cleanupSucceeded ? "THANH CONG" : unfinishedResult, reason.c_str());
        saveStatePreferences();
    };

    setAgentState("auto_setup_rover");
    setWorkflowProgress("set_rover", 1, 4);
    if (!applyRoverMode())
    {
        finish(false, false, "cannot configure GNSS rover mode");
        return false;
    }

    if (autoNearest)
    {
        setWorkflowProgress("wait_gga", 1, 4);
        const uint32_t started = millis();
        bool hasPosition = false;
        while (!workflowCancelRequested_ && millis() - started < timeoutSeconds * 1000UL)
        {
            const auto position = getGnssTelemetrySnapshot();
            if (position.lastGgaMs != 0 && millis() - position.lastGgaMs < 3000UL
                && std::isfinite(position.latitude) && std::abs(position.latitude) <= 90
                && std::isfinite(position.longitude) && std::abs(position.longitude) <= 180
                && (position.latitude != 0 || position.longitude != 0))
            {
                hasPosition = true;
                break;
            }
            vTaskDelay(pdMS_TO_TICKS(100));
        }
        if (!hasPosition || workflowCancelRequested_)
        {
            finish(false, workflowCancelRequested_, "no valid GGA position for AutoNearest");
            return false;
        }
    }

    String failureReason;
    if (!startAutoBaseRover(host, port, username, password, mountpoint, ntripVersion, failureReason,
                            autoNearest ? &selectedMountpoint : nullptr))
    {
        if (autoNearest && failureReason == "ERROR - NO STATION WITHIN 20 KM" && !workflowCancelRequested_)
        {
            DynamicJsonDocument survey(CONFIG_DOCUMENT_SIZE);
            survey.set(previousBase.as<JsonObjectConst>());
            survey["base_setup_method"] = "SURVEY_IN";
            survey["accuracy"] = GnssCmdBuilder::BASE_ACCURACY_METERS;
            survey["survey_in_accuracy"] = GnssCmdBuilder::BASE_ACCURACY_METERS;
            survey.remove("coords");
            survey.remove("coordinate_source");
            survey.remove("conversion_report");
            if (restoreWorkflowBase(survey.as<JsonObjectConst>()) && restartConfiguredNtrip())
            {
                const String oldConfig = baseConfig_;
                baseConfig_.clear();
                serializeJson(survey, baseConfig_);
                if (saveStatePreferences())
                {
                    setAgentState(normalAgentState());
                    setWorkflowProgress("completed", 4, 4,
                        R"({"mode":"survey_in","auto_applied":true,"receiver_write_completed":true,"reason":"no_fixed_station_within_20_km"})");
                    saveStatePreferences();
                    publishConfigState("base_config_state");
                    return true;
                }
                baseConfig_ = oldConfig;
                finish(false, false, "cannot save Survey-In fallback");
                return false;
            }
            finish(false, false, "cannot start Survey-In fallback");
            return false;
        }
        finish(false, workflowCancelRequested_, failureReason);
        return false;
    }
    const String sourceMountpoint = autoNearest ? selectedMountpoint : mountpoint;

    setAgentState("auto_setup_wait_fix");
    setWorkflowProgress("wait_fix", 2, 4);
    auto cancelled = false;
    if (!waitForAutoBaseFix(timeoutSeconds, fixedStreakRequired, cancelled, failureReason, sourceMountpoint))
    {
        finish(false, cancelled, failureReason);
        return false;
    }

    setAgentState("auto_setup_averaging");
    const auto configuredSamples = payload["samples"] | 60;
    setWorkflowProgress("averaging", 3, 4);
    std::vector<double> latitudes;
    std::vector<double> longitudes;
    std::vector<double> altitudes;
    if (!collectAutoBaseSamples(configuredSamples, latitudes, longitudes, altitudes,
                                cancelled, failureReason, sourceMountpoint))
    {
        finish(false, cancelled, failureReason);
        return false;
    }

    String resultJson;
    if (!completeAutoBaseSetup(payload, latitudes, longitudes, altitudes,
                               resultJson, failureReason, sourceMountpoint))
    {
        finish(false, workflowCancelRequested_, failureReason);
        return false;
    }
    const bool autoApply = payload["auto_apply"] | false;
    if (!autoApply)
    {
        const bool stopped = stopNtripRoverLocked();
        const bool restored = stopped && restoreWorkflowBase(previousBase.as<JsonObjectConst>());
        if (!restored || !restartConfiguredNtrip())
        {
            finish(false, false, "cannot restore previous Base/NTRIP state after sampling");
            return false;
        }
        setAgentState(normalAgentState());
    }
    DynamicJsonDocument result(CONFIG_DOCUMENT_SIZE);
    if (deserializeJson(result, resultJson) == DeserializationError::Ok)
    {
        result["source_mountpoint"] = sourceMountpoint;
        result["auto_applied"] = autoApply;
        result["receiver_write_completed"] = autoApply;
        result["configured_ntrip_restarted"] = true;
        resultJson.clear();
        serializeJson(result, resultJson);
    }
    setWorkflowProgress(autoApply ? "completed" : "ready_for_review", 4, 4, resultJson);
    saveStatePreferences();
    return true;
}

bool BackendAgent::prepareReferenceCheckConfig(
    JsonObject payload, JsonObject &reference, double &referenceLatitude,
    double &referenceLongitude, double &referenceAltitude, double &restoreLatitude,
    double &restoreLongitude, double &restoreAltitude, String &host, uint16_t &port,
    String &username, String &password, String &mountpoint, uint32_t &timeoutSeconds,
    uint16_t &requestedSamples)
{
    reference = payload["reference_coords"].as<JsonObject>();
    DynamicJsonDocument storedBase(CONFIG_DOCUMENT_SIZE);
    const auto baseParsed = deserializeJson(storedBase, baseConfig_) == DeserializationError::Ok && storedBase.is<JsonObject>();
    JsonObject storedBaseObject = storedBase.as<JsonObject>();
    JsonObject storedCoordinates = storedBaseObject["coords"].as<JsonObject>();
    if (storedCoordinates.isNull())
        storedCoordinates = storedBaseObject;

    referenceLatitude = reference["lat"] | NAN;
    referenceLongitude = reference["lon"] | NAN;
    referenceAltitude = reference["alt"] | NAN;
    restoreLatitude = storedCoordinates["lat"] | NAN;
    restoreLongitude = storedCoordinates["lon"] | NAN;
    restoreAltitude = storedCoordinates["alt"] | NAN;
    host = payload["ip"] | String();
    host.trim();
    const int requestedPort = payload["port"] | 0;
    port = requestedPort > 0 && requestedPort <= 65535 ? static_cast<uint16_t>(requestedPort) : 0;
    username = payload["user"] | String();
    password = payload["password"] | String();
    mountpoint = payload["mountpoint"] | String();
    timeoutSeconds = constrain(
        static_cast<uint32_t>(payload["timeout"] | 300UL), 30UL, 86400UL);
    requestedSamples = static_cast<uint16_t>(constrain(
        static_cast<int>(payload["samples"] | 60), 5, 120));

    return baseParsed && !reference.isNull() && std::isfinite(referenceLatitude) && std::isfinite(referenceLongitude) && std::isfinite(referenceAltitude) && referenceLatitude >= -90.0 && referenceLatitude <= 90.0 && referenceLongitude >= -180.0 && referenceLongitude <= 180.0 && (storedBaseObject["base_setup_method"] == "SURVEY_IN" || (std::isfinite(restoreLatitude) && std::isfinite(restoreLongitude) && std::isfinite(restoreAltitude))) && !host.isEmpty() && !username.isEmpty() && !password.isEmpty() && !mountpoint.isEmpty() && port != 0;
}

bool BackendAgent::startReferenceRover(const String &host, const uint16_t port,
                                              const String &username, const String &password,
                                              const String &mountpoint, String &error)
{
    if (!tcpStreamMutex || xSemaphoreTake(tcpStreamMutex, pdMS_TO_TICKS(MUTEX_TIMEOUT_MS)) != pdTRUE)
    {
        error = "network transport is busy";
        return false;
    }
    stopNtrip();
    const auto started = startNtripRover(host, port, username, password, mountpoint, 1);
    if (!started)
        error = ntripRoverLastError();
    xSemaphoreGive(tcpStreamMutex);
    return started;
}

bool BackendAgent::waitForReferenceFix(const uint32_t timeoutSeconds, String &failureReason)
{
    const uint32_t waitStartedMs = millis();
    uint32_t nextSecondMs = waitStartedMs;
    while (millis() - waitStartedMs < timeoutSeconds * 1000UL)
    {
        if (workflowCancelRequested_)
        {
            failureReason = "cancelled by user";
            return false;
        }
        if (loopNtripRoverLocked() == 504)
        {
            failureReason = ntripRoverLastError();
            return false;
        }
        const uint32_t now = millis();
        if (static_cast<int32_t>(now - nextSecondMs) >= 0)
        {
            nextSecondMs = now + 1000UL;
            const GnssTelemetrySnapshot snapshot = getGnssTelemetrySnapshot();
            const auto fixed = freshRtkSample(now, snapshot.lastGgaMs, snapshot.fixStatus.data());
            DynamicJsonDocument details(512);
            details["fix_status"] = snapshot.fixStatus.data();
            details["elapsed"] = (now - waitStartedMs) / 1000UL;
            String serialized;
            serializeJson(details, serialized);
            setWorkflowProgress("reference_check_wait_fix", 2, 4, serialized);
            if (fixed)
                return true;
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
    failureReason = "RTK fix timeout";
    return false;
}

bool BackendAgent::collectReferenceSamples(const uint16_t requestedSamples,
                                           std::vector<double> &latitudes,
                                           std::vector<double> &longitudes,
                                           std::vector<double> &altitudes,
                                           String &failureReason)
{
    latitudes.reserve(requestedSamples);
    longitudes.reserve(requestedSamples);
    altitudes.reserve(requestedSamples);
    const uint32_t averageStartedMs = millis();
    uint32_t nextSecondMs = averageStartedMs;
    const uint32_t averagingSeconds = requestedSamples > 60U ? requestedSamples : 60U;
    while (millis() - averageStartedMs < averagingSeconds * 1000UL && latitudes.size() < requestedSamples)
    {
        if (workflowCancelRequested_)
        {
            failureReason = "cancelled by user";
            return false;
        }
        if (loopNtripRoverLocked() == 504)
        {
            failureReason = ntripRoverLastError();
            return false;
        }
        const uint32_t now = millis();
        if (static_cast<int32_t>(now - nextSecondMs) >= 0)
        {
            nextSecondMs = now + 1000UL;
            const GnssTelemetrySnapshot snapshot = getGnssTelemetrySnapshot();
            const auto usable = freshRtkSample(now, snapshot.lastGgaMs, snapshot.fixStatus.data());
            if (usable && std::isfinite(snapshot.latitude) && std::isfinite(snapshot.longitude) && std::isfinite(snapshot.altitude) && snapshot.latitude >= -90.0 && snapshot.latitude <= 90.0 && snapshot.longitude >= -180.0 && snapshot.longitude <= 180.0)
            {
                latitudes.push_back(snapshot.latitude);
                longitudes.push_back(snapshot.longitude);
                altitudes.push_back(snapshot.altitude);
            }
            DynamicJsonDocument details(768);
            details["samples_collected"] = latitudes.size();
            details["samples_target"] = requestedSamples;
            details["fix_status"] = snapshot.fixStatus.data();
            String serialized;
            serializeJson(details, serialized);
            setWorkflowProgress("reference_check_averaging", 3, 4, serialized);
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
    if (latitudes.size() < 5)
    {
        failureReason = "insufficient valid reference samples";
        return false;
    }
    return true;
}

String BackendAgent::buildReferenceCheckResult(JsonObject reference, const double measuredLatitude,
                                               const double measuredLongitude,
                                               const double measuredAltitude,
                                               const size_t sampleCount)
{
    const auto meanLatitudeRad = (measuredLatitude + (reference["lat"] | NAN)) * 3.14159265358979323846 / 360.0;
    DynamicJsonDocument result(2048);
    result["reference_coord"]["lat"] = reference["lat"];
    result["reference_coord"]["lon"] = reference["lon"];
    result["reference_coord"]["alt"] = reference["alt"];
    result["measured_coord"]["lat"] = measuredLatitude;
    result["measured_coord"]["lon"] = measuredLongitude;
    result["measured_coord"]["alt"] = measuredAltitude;
    result["delta_n_m"] = (measuredLatitude - (reference["lat"] | NAN)) * 3.14159265358979323846 / 180.0 * 6378137.0;
    result["delta_e_m"] = (measuredLongitude - (reference["lon"] | NAN)) * 3.14159265358979323846 / 180.0 * 6378137.0 * cos(meanLatitudeRad);
    result["delta_u_m"] = measuredAltitude - (reference["alt"] | NAN);
    result["sample_count"] = sampleCount;
    String resultJson;
    serializeJson(result, resultJson);
    return resultJson;
}

bool BackendAgent::runReferenceCheckWorkflow(JsonObject payload)
{
    JsonObject reference;
    double referenceLatitude = NAN;
    double referenceLongitude = NAN;
    double referenceAltitude = NAN;
    double restoreLatitude = NAN;
    double restoreLongitude = NAN;
    double restoreAltitude = NAN;
    String host;
    uint16_t port = 0;
    String username;
    String password;
    String mountpoint;
    uint32_t timeoutSeconds = 0;
    uint16_t requestedSamples = 0;
    const auto validConfig = prepareReferenceCheckConfig(
        payload, reference, referenceLatitude, referenceLongitude, referenceAltitude,
        restoreLatitude, restoreLongitude, restoreAltitude, host, port, username, password,
        mountpoint, timeoutSeconds, requestedSamples);

    if (!validConfig)
    {
        setAgentState(normalAgentState());
        setWorkflowProgress("reference_check_failed", 0, 4, R"({"reason":"missing or invalid reference/CORS configuration"})");
        saveStatePreferences();
        return false;
    }

    DynamicJsonDocument storedBase(CONFIG_DOCUMENT_SIZE);
    deserializeJson(storedBase, baseConfig_);
    if (storedBase.size() == 0 && surveyInTargetSeconds_ > 0)
        storedBase["base_setup_method"] = "SURVEY_IN";
    if (storedBase["base_setup_method"] == "SURVEY_IN" && surveyInTargetSeconds_ > 0)
        storedBase["survey_in_duration"] = surveyInTargetSeconds_;

    auto cleanup = [&]()
    {
        if (!stopNtripRoverLocked())
            return false;
        const bool baseRestored = restoreWorkflowBase(storedBase.as<JsonObjectConst>());
        const bool transportRestored = baseRestored && restartConfiguredNtrip();
        return baseRestored && transportRestored;
    };
    auto finish = [&](const bool success, const bool cancelled, const String &reason)
    {
        const auto cleanupSucceeded = cleanup();
        const auto completed = success && cleanupSucceeded;
        const auto stopped = cancelled && cleanupSucceeded;
        setAgentState(normalAgentState());
        DynamicJsonDocument details(1024);
        if (!reason.isEmpty())
            details["reason"] = reason;
        if (!cleanupSucceeded)
            details["cleanup_error"] = "could not safely restore base/NTRIP state";
        String serialized;
        serializeJson(details, serialized);
        const char *stage = stopped ? "stopped" : "reference_check_failed";
        if (completed)
            stage = "reference_check_completed";
        setWorkflowProgress(stage, 4, 4, serialized);
        saveStatePreferences();
    };

    setAgentState("reference_check_rover");
    setWorkflowProgress("reference_check_set_rover", 1, 4);
    if (!applyRoverMode())
    {
        finish(false, false, "cannot configure GNSS rover mode");
        return false;
    }

    String failureReason;
    if (!startReferenceRover(host, port, username, password, mountpoint, failureReason))
    {
        finish(false, false, failureReason);
        return false;
    }

    setAgentState("reference_check_wait_fix");
    setWorkflowProgress("reference_check_wait_fix", 2, 4);
    if (!waitForReferenceFix(timeoutSeconds, failureReason))
    {
        finish(false, failureReason == "cancelled by user",
               failureReason);
        return false;
    }

    setAgentState("reference_check_averaging");
    setWorkflowProgress("reference_check_averaging", 3, 4);
    std::vector<double> latitudes;
    std::vector<double> longitudes;
    std::vector<double> altitudes;
    if (!collectReferenceSamples(requestedSamples, latitudes, longitudes, altitudes,
                                 failureReason))
    {
        finish(false, failureReason == "cancelled by user",
               failureReason);
        return false;
    }

    auto measuredLatitude = 0.0;
    auto measuredLongitude = 0.0;
    auto measuredAltitude = 0.0;
    for (size_t index = 0; index < latitudes.size(); ++index)
    {
        measuredLatitude += latitudes[index];
        measuredLongitude += longitudes[index];
        measuredAltitude += altitudes[index];
    }
    measuredLatitude /= latitudes.size();
    measuredLongitude /= longitudes.size();
    measuredAltitude /= altitudes.size();
    if (!stopNtripRoverLocked())
    {
        finish(false, false, "cannot acquire transport lock to stop CORS reference session");
        return false;
    }

    const auto resultJson = buildReferenceCheckResult(
        reference, measuredLatitude, measuredLongitude, measuredAltitude, latitudes.size());

    if (!cleanup())
    {
        setAgentState(normalAgentState());
        setWorkflowProgress("reference_check_failed", 4, 4,
                            R"({"reason":"could not safely restore base/NTRIP state"})");
        saveStatePreferences();
        return false;
    }
    setAgentState(normalAgentState());
    setWorkflowProgress("reference_check_completed", 4, 4, resultJson);
    saveStatePreferences();
    return true;
}
