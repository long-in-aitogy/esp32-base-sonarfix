#include "functions/backend/Backend_Agent.h"
#include "functions/backend/Backend_Agent_Internal.h"
#include "functions/gnss/Unicore_Readback.h"
#include "functions/gnss/Unicore_Config_Verification.h"
#include "Prog_Config.h"
#include "functions/gnss/Ublox_Readback.h"
#include "functions/gnss/Ubx_Config_Verification.h"
#include <algorithm>
#include <array>
#include <cinttypes>
#include <cstdio>
#include <cstring>

using namespace BackendAgentInternal;

namespace {
bool readUnicoreExpectations(JsonObjectConst payload, std::array<double, 3> &wanted,
                             uint8_t &selectedPort, String &error) {
    const JsonArrayConst expectedLogs = payload["logs"].as<JsonArrayConst>();
    const String reference = payload["altitude_reference"] | "LEGACY";
    size_t coordinate = 0;
    for (const char *key : {"lat", "lon", "alt"}) {
        const JsonVariantConst input = payload["coords"][key];
        double value = NAN;
        if (input.is<const char *>()) {
            const char *text = input.as<const char *>();
            char *end = nullptr;
            value = std::strtod(text, &end);
            if (end == text || *end) value = NAN;
        } else if (!input.is<bool>() && input.is<double>()) {
            value = input.as<double>();
        }
        if (!std::isfinite(value)) {
            error = "Invalid Unicore verification coordinates"; return false;
        }
        wanted[coordinate++] = value;
    }
    if (std::abs(wanted[0]) > 90 || std::abs(wanted[1]) > 180 || wanted[2] < -12000 || wanted[2] > 100000
        || (reference != "LEGACY" && reference != "ELLIPSOID")
        || expectedLogs.isNull() || !expectedLogs.size() || expectedLogs.size() > 64) {
        error = "Invalid Unicore verification expectation"; return false;
    }
    if (const String requestedPort = payload["port"] | "CURRENT"; requestedPort != "CURRENT") {
        if (requestedPort != "COM1" && requestedPort != "COM2" && requestedPort != "COM3") {
            error = "Invalid Unicore comparison port"; return false;
        }
        selectedPort = requestedPort[3] - '0';
    }
    for (JsonVariantConst item : expectedLogs) {
        const char *name = item.as<const char *>();
        if (!name || strnlen(name, 24) == 24 || !UnicoreConfigVerification::validLogName(name, 24)) {
            error = "Invalid Unicore output name"; return false;
        }
    }
    return true;
}
bool containsExpectedLog(JsonArrayConst expectedLogs, const char *name) {
    for (JsonVariantConst item : expectedLogs)
        if (std::strcmp(item.as<const char *>(), name) == 0) return true;
    return false;
}
void appendObservedUnicoreLogs(JsonArray observedLogs, const std::vector<UnicoreConfigVerification::Log> &logs) {
    for (const auto &log : logs) {
        JsonObject observed = observedLogs.createNestedObject();
        observed["port"] = String("COM") + String(log.port);
        observed["name"] = log.name.data();
        if (log.period > 0) observed["period"] = log.period;
        else observed["period"] = nullptr;
    }
}
void compareUnicoreLogs(JsonObject groups, JsonArrayConst expectedLogs,
                        const std::vector<UnicoreConfigVerification::Log> &logs, uint8_t comparePort) {
    for (JsonVariantConst item : expectedLogs) {
        const char *name = item.as<const char *>();
        JsonObject group = groups[std::strncmp(name, "RTCM", 4) == 0 ? "rtcm" : "diagnostics"];
        group["checked"] = group["checked"].as<unsigned>() + 1;
        const bool matches = std::any_of(logs.begin(), logs.end(), [&](const auto &log) {
            return log.port == comparePort && std::strcmp(name, log.name.data()) == 0
                && std::abs(log.period - 1) <= 1e-6;
        });
        if (!matches) group["mismatched"] = group["mismatched"].as<unsigned>() + 1;
    }
    for (const auto &log : logs) {
        if (log.port != comparePort || log.period == 0) continue;
        const bool expected = containsExpectedLog(expectedLogs, log.name.data());
        if (!expected) {
            JsonObject group = groups[std::strncmp(log.name.data(), "RTCM", 4) ? "diagnostics" : "rtcm"];
            group["checked"] = group["checked"].as<unsigned>() + 1;
            group["mismatched"] = group["mismatched"].as<unsigned>() + 1;
        }
    }
    for (const char *name : {"diagnostics", "rtcm"})
        if (groups[name]["checked"].as<unsigned>() == 0) groups[name]["checked"] = 1;
}
void verifyUnicorePosition(JsonObject result, JsonObject groups, JsonObject actualPosition,
                           const std::array<double, 3> &wanted) {
    String mode;
    String modeError;
    bool positionRead = UnicoreReadback::readMode(mode, modeError);
    if (positionRead) actualPosition["mode"] = mode;
    if (positionRead && String(UnicoreReadback::modeKind(mode)) != "base") {
        groups["fixed"]["checked"] = 1;
        groups["fixed"]["mismatched"] = 1;
    } else if (positionRead) {
        double lat = 0;
        double lon = 0;
        double alt = 0;
        positionRead = UnicoreConfigVerification::parseFixedMode(mode.c_str(), lat, lon, alt);
        if (positionRead) {
            JsonObject positionDetails = actualPosition.createNestedObject("self_position");
            positionDetails["lat"] = lat;
            positionDetails["lon"] = lon;
            positionDetails["alt"] = alt;
            actualPosition["coordinate_source"] = "MODE";
            const bool matches = std::abs(lat - wanted[0]) <= 1e-9
                && std::abs(lon - wanted[1]) <= 1e-9
                && std::abs(alt - wanted[2]) <= 0.0001;
            groups["fixed"]["checked"] = 1;
            groups["fixed"]["mismatched"] = matches ? 0 : 1;
        } else {
            modeError = "Unicore MODE has no valid Fixed LLA coordinates";
        }
    }
    if (!positionRead) { groups["fixed"]["unread"] = 1; result["mode_error"] = modeError; }
}
} // namespace

bool BackendAgent::verifyUnicoreConfig(JsonObjectConst payload, const String &commandId, String &error) {
    gnssVerification_.clear();
    const JsonArrayConst expectedLogs = payload["logs"].as<JsonArrayConst>();
    std::array<double, 3> wanted{};
    uint8_t selectedPort = 0;
    if (!readUnicoreExpectations(payload, wanted, selectedPort, error)) return false;
    DynamicJsonDocument result(VERIFICATION_DOCUMENT_SIZE);
    result["command_id"] = commandId;
    JsonObject details = result.createNestedObject("details");
    details["kind"] = "Unicorecomm";
    details["expected_logs"].set(expectedLogs);
    JsonArray comparedPorts = details.createNestedArray("compare_ports");
    JsonObject fixedDetails = details.createNestedObject("fixed");
    JsonObject expectedPosition = fixedDetails.createNestedObject("expected");
    expectedPosition["mode"] = "Fixed";
    expectedPosition["self_position"].set(payload["coords"]);
    JsonObject actualPosition = fixedDetails.createNestedObject("actual");
    JsonObject groups = result.createNestedObject("groups");
    for (const char *name : {"fixed", "diagnostics", "rtcm"}) {
        JsonObject group = groups.createNestedObject(name);
        group["checked"] = 0; group["mismatched"] = 0; group["unread"] = 0;
    }
    verifyUnicorePosition(result.as<JsonObject>(), groups, actualPosition, wanted);
    String rawLogs;
    String outputError;
    std::vector<UnicoreConfigVerification::Log> logs;
    bool logsRead = UnicoreReadback::readLogList(rawLogs, outputError)
        && UnicoreConfigVerification::parseLogs(rawLogs.c_str(), rawLogs.length(), logs);
    if (!logsRead && outputError.isEmpty())
        outputError = "Unicore UNILOGLIST response is malformed";
    details["logs_state"] = logsRead ? "ok" : "unread";
    JsonArray observedLogs = details.createNestedArray("logs");
    if (logsRead) appendObservedUnicoreLogs(observedLogs, logs);
    const uint8_t configuredPort = selectedPort ? selectedPort : GNSS_UNICORE_PORT;
    const uint8_t comparePort = logsRead ? UnicoreConfigVerification::comparisonPort(configuredPort, logs) : 0;
    if (comparePort) {
        comparedPorts.add(String("COM") + String(comparePort));
        const bool hasConfiguredPort = GNSS_UNICORE_PORT >= 1 && GNSS_UNICORE_PORT <= 3;
        const char *automaticSource = hasConfiguredPort ? "firmware_config" : "log_list_unique";
        details["port_source"] = selectedPort ? "user_selection" : automaticSource;
    } else if (logsRead) {
        logsRead = false;
        result["note"] = logs.empty()
            ? "Danh sách bản tin UM trống; chưa xác định cổng để đối chiếu."
            : "UM có bản tin trên nhiều cổng COM; cần khai báo cổng nối GNSS để đối chiếu.";
    }
    if (logsRead) {
        compareUnicoreLogs(groups, expectedLogs, logs, comparePort);
    } else {
        groups["diagnostics"]["unread"] = 1;
        groups["rtcm"]["unread"] = 1;
        result["output_error"] = outputError;
    }
    bool mismatch = false;
    bool unread = false;
    for (JsonPair group : groups) {
        mismatch |= group.value()["mismatched"].as<unsigned>() > 0;
        unread |= group.value()["unread"].as<unsigned>() > 0;
    }
    const char *state = "match";
    if (unread) state = "unread";
    else if (mismatch) state = "mismatch";
    result["state"] = state;
    if (result.overflowed()) { error = "GNSS verification result overflow"; return false; }
    serializeJson(result, gnssVerification_);
    gnssVerificationMs_ = millis(); markStatusDirty();
    return true;
}


namespace
{
void describeTmode(JsonObject object, const uint8_t *raw) {
    const char *mode = "Rover";
    if (raw[2] == 2) mode = "Fixed";
    else if (raw[2] == 1) mode = "Survey-In";
    object["mode"] = mode;
    object["coordinate_type"] = raw[3] & 1 ? "LLA" : "ECEF";
    object["accuracy_m"] = UbxBaseStatus::u32(raw + 20) * 0.0001;
    UbxBaseStatus status;
    if (status.tmode(raw, 40) && status.hasPosition) {
        JsonObject position = object.createNestedObject("self_position");
        std::array<char, 32> value{};
        snprintf(value.data(), value.size(), "%.11f", status.latitude); position["lat"] = value.data();
        snprintf(value.data(), value.size(), "%.11f", status.longitude); position["lon"] = value.data();
        snprintf(value.data(), value.size(), "%.4f", status.height); position["alt"] = value.data();
    }
}
int ubxPortIndex(const String &name) {
    static constexpr std::array<const char *, 5> names = {"I2C", "UART1", "UART2", "USB", "SPI"};
    for (size_t i = 0; i < names.size(); ++i)
        if (name == names[i]) return static_cast<int>(i);
    return -1;
}
int appendUbxPortValues(JsonObject port, int portIndex, const uint8_t *records,
                        const uint8_t *observed, size_t count) {
    JsonArray values = port.createNestedArray("values");
    int enabled = -1;
    for (size_t i = 0; i < count; ++i) {
        values.add(observed[i]);
        if (UbxBaseStatus::u32(records + i * 5) == UbxConfigVerification::enabledKey(portIndex)) {
            port["enabled"] = observed[i];
            enabled = observed[i];
        }
    }
    return enabled;
}
bool matchUbxOutputValues(const uint8_t *expected, size_t expectedLength,
                          const uint8_t *actual, size_t actualLength,
                          const uint8_t *observed, uint8_t *values) {
    bool allFound = true;
    for (size_t i = 0; i < expectedLength; i += 5) {
        bool found = false;
        for (size_t j = 0; j < actualLength; j += 5) {
            if (UbxBaseStatus::u32(expected + i) != UbxBaseStatus::u32(actual + j)) continue;
            values[i / 5] = observed[j / 5];
            found = true;
            break;
        }
        if (!found) allFound = false;
    }
    return allFound;
}
void compareUbxOutputGroups(JsonObject groups, const uint8_t *expected, size_t length,
                            const uint8_t *values, bool outputRead) {
    for (size_t i = 0; i < length; i += 5) {
        const uint32_t key = UbxBaseStatus::u32(expected + i);
        const char *name = key >= 0x209102BD ? "rtcm" : "diagnostics";
        if (key >> 28 == 1) name = "protocols";
        JsonObject group = groups[name];
        const char *count = outputRead ? "checked" : "unread";
        group[count] = group[count].as<unsigned>() + 1;
        if (outputRead && values[i / 5] != expected[i + 4])
            group["mismatched"] = group["mismatched"].as<unsigned>() + 1;
    }
}

}

bool BackendAgent::verifyGnssConfig(JsonObjectConst payload, const String &commandId, String &error) {
    gnssVerification_.clear();
    std::array<uint8_t, 40> expectedMode{};
    std::array<uint8_t, UbxConfigVerification::MAX_KEYS * 5> expectedOutput{};
    const size_t modeLength = decodeBase64(payload["tmode_b64"] | "", expectedMode.data(), expectedMode.size());
    const size_t outputLength = decodeBase64(payload["output_b64"] | "", expectedOutput.data(), expectedOutput.size());
    if (modeLength != 40 || expectedMode[2] != 2 || expectedMode[3] != 1
        || !UbxConfigVerification::validExpected(expectedOutput.data(), outputLength)) {
        error = "Invalid GNSS verification expectation";
        return false;
    }
    // The receiver is always configured with a 5 m Fixed LLA accuracy.
    const auto accuracy = static_cast<uint32_t>(GnssCmdBuilder::BASE_ACCURACY_METERS * 10000);
    for (size_t i = 0; i < 4; ++i)
        expectedMode[20 + i] = static_cast<uint8_t>(accuracy >> (8 * i));
    std::array<uint8_t, 40> actualMode{};
    std::array<uint8_t, UbxConfigVerification::MAX_KEYS> values{};
    String modeError;
    String outputError;
    const bool modeRead = UbloxReadback::readTmode(actualMode.data(), modeError);
    const JsonObjectConst inspection = payload["readback"].as<JsonObjectConst>();
    bool interfaceRead = false;
    uint8_t interfaceEnabled = 0;
    bool outputRead = inspection.isNull()
        && UbloxReadback::readOutputValues(expectedOutput.data(), outputLength, values.data(), outputError);
    DynamicJsonDocument result(VERIFICATION_DOCUMENT_SIZE);
    result["command_id"] = commandId;
    JsonObject details = result.createNestedObject("details");
    details["kind"] = "Ublox";
    JsonObject fixedDetails = details.createNestedObject("fixed");
    describeTmode(fixedDetails.createNestedObject("expected"), expectedMode.data());
    if (modeRead) describeTmode(fixedDetails.createNestedObject("actual"), actualMode.data());
    if (!inspection.isNull()) {
        const JsonArrayConst fields = inspection["fields"].as<JsonArrayConst>();
        const JsonArrayConst ports = inspection["ports"].as<JsonArrayConst>();
        if (fields.size() < 3 || fields.size() > UbxConfigVerification::MAX_KEYS || ports.size() != 5) {
            error = "Invalid GNSS readback catalogue"; return false;
        }
        details["fields"].set(fields);
        details["expected"].set(inspection["expected"]);
        details.createNestedArray("compare_ports").add("UART1");
        JsonArray observedPorts = details.createNestedArray("ports");
        unsigned seen = 0;
        for (JsonObjectConst request : ports) {
            const String name = request["name"] | "";
            const int portIndex = ubxPortIndex(name);
            if (portIndex < 0 || (seen & (1U << portIndex))) { error = "Invalid GNSS readback port"; return false; }
            seen |= 1U << portIndex;
            std::array<uint8_t, UbxConfigVerification::MAX_KEYS * 5> records{};
            std::array<uint8_t, UbxConfigVerification::MAX_KEYS> observed{};
            const size_t length = decodeBase64(request["output_b64"] | "", records.data(), records.size());
            if (length != fields.size() * 5 || !UbxConfigVerification::validExpected(records.data(), length)) {
                error = "Invalid GNSS readback keys"; return false;
            }
            String readError;
            const bool read = UbloxReadback::readOutputValues(records.data(), length, observed.data(), readError);
            JsonObject port = observedPorts.createNestedObject();
            port["name"] = name;
            port["state"] = read ? "ok" : "unread";
            if (read) {
                const int enabled = appendUbxPortValues(port, portIndex, records.data(), observed.data(), fields.size());
                if (portIndex == 1 && enabled >= 0) {
                    interfaceRead = true;
                    interfaceEnabled = static_cast<uint8_t>(enabled);
                }
            } else port["error"] = readError;
            if (portIndex == 1 || portIndex == 2) {
                uint32_t baud = 0;
                String baudError;
                if (UbloxReadback::readBaud(portIndex, baud, baudError)) port["baud"] = baud;
                else port["baud"] = nullptr;
            }
            if (name == "UART1") {
                // Match by key, never by the ordering of a catalogue supplied over the wire.
                outputRead = read && matchUbxOutputValues(
                    expectedOutput.data(), outputLength, records.data(), length, observed.data(), values.data());
                if (!outputRead) outputError = readError.length() ? readError : "Missing UART1 readback keys";
            }
        }
    }
    JsonObject groups = result.createNestedObject("groups");
    JsonObject fixed = groups.createNestedObject("fixed");
    fixed["checked"] = modeRead ? 1 : 0;
    fixed["mismatched"] = modeRead && !UbxConfigVerification::fixedMatches(expectedMode.data(), actualMode.data(), 40) ? 1 : 0;
    fixed["unread"] = modeRead ? 0 : 1;
    for (const char *name : {"protocols", "diagnostics", "rtcm"}) {
        JsonObject group = groups.createNestedObject(name);
        group["checked"] = 0; group["mismatched"] = 0; group["unread"] = 0;
    }
    compareUbxOutputGroups(groups, expectedOutput.data(), outputLength, values.data(), outputRead);
    if (!inspection.isNull()) {
        JsonObject protocols = groups["protocols"];
        const char *count = interfaceRead ? "checked" : "unread";
        protocols[count] = protocols[count].as<unsigned>() + 1;
        if (interfaceRead && interfaceEnabled != 1) protocols["mismatched"] = protocols["mismatched"].as<unsigned>() + 1;
    }
    bool mismatch = false;
    bool unread = false;
    for (JsonPair group : groups) {
        mismatch |= group.value()["mismatched"].as<unsigned>() > 0;
        unread |= group.value()["unread"].as<unsigned>() > 0 || !group.value()["checked"].as<unsigned>();
    }
    const char *state = "match";
    if (unread) state = "unread";
    else if (mismatch) state = "mismatch";
    result["state"] = state;
    if (!modeRead) result["mode_error"] = modeError;
    if (!outputRead) result["output_error"] = outputError;
    if (result.overflowed()) { error = "GNSS verification result overflow"; return false; }
    serializeJson(result, gnssVerification_);
    gnssVerificationMs_ = millis();
    markStatusDirty();
    return true; // Command completion is separate from match/mismatch/unread.
}

void BackendAgent::saveSurveyResult(JsonObjectConst bestPosition, const String &mode)
{
    if (!surveyInMonitoring_ || !surveyInReadbackReady_ || !surveyInReadbackHasPosition_ || (!surveyInResultPending_ && surveyInResult_.length() > 2))
        return;
    DynamicJsonDocument savedSurvey(1536);
    savedSurvey["chip"] = sensorType_;
    savedSurvey["bestpos"].set(bestPosition);
    savedSurvey["mode_raw"] = mode;
    savedSurvey["recorded_at"] = epochString().toInt();
    surveyInResult_.clear();
    serializeJson(savedSurvey, surveyInResult_);
    surveyInResultPending_ = !saveStatePreferences();
}

bool BackendAgent::refreshUbloxReadback(String &error)
{
    UbxBaseStatus status;
    const auto success = UbloxReadback::readBaseStatus(status, error);
    DynamicJsonDocument doc(1536);
    doc["state"] = success ? "ok" : "error";
    doc["chip"] = "Ublox";
    doc["revision"] = ++receiverBaseReadbackRevision_;
    doc["query"] = "CFG-TMODE3 / NAV-SVIN";

    const char *kind = "rover";
    if (status.mode == 1)
        kind = "survey_in";
    else if (status.mode == 2)
        kind = "base";

    const char *mode = "Rover (CFG-TMODE3)";
    if (status.mode == 1)
        mode = "Survey-In (NAV-SVIN)";
    else if (status.mode == 2)
        mode = "Fixed LLA (CFG-TMODE3)";

    doc["mode_kind"] = success ? kind : "unknown";
    doc["mode_raw"] = mode;

    surveyInReadbackHasPosition_ = success && status.hasPosition;
    surveyInReadbackReady_ = success && status.valid && !status.active && status.hasPosition;
    if (!success)
    {
        Serial.printf("[GNSS][READBACK][ERROR] UBX: %s\n", error.c_str());
        doc["error"] = error;
    }
    else
    {
        logUbloxReadback(status);
        updateUbloxSurveyState(status);
        doc["elapsed_seconds"] = status.duration;
        doc["observations"] = status.observations;
        doc["mean_accuracy_m"] = status.accuracy;
        doc["active"] = status.active;
        appendUbloxPosition(doc, status, mode);
    }
    receiverBaseReadback_.clear();
    serializeJson(doc, receiverBaseReadback_);
    reconcileBaseStartupReadback();
    receiverBaseReadbackMs_ = millis();
    markStatusDirty();
    return success;
}

void BackendAgent::updateUbloxSurveyState(const UbxBaseStatus &status)
{
    surveyInMonitoring_ = status.mode == 1;
    if (surveyInMonitoring_)
        surveyInTargetSeconds_ = status.targetSeconds;
}

void BackendAgent::logUbloxReadback(const UbxBaseStatus &status)
{
    if (status.mode == 1)
    {
        Serial.printf("[GNSS][READBACK] UBX Survey-In elapsed=%lus/%lus observations=%lu accuracy=%.3fm active=%u valid=%u\n",
                      static_cast<unsigned long>(status.duration),
                      static_cast<unsigned long>(status.targetSeconds),
                      static_cast<unsigned long>(status.observations), status.accuracy,
                      static_cast<unsigned int>(status.active), static_cast<unsigned int>(status.valid));
        return;
    }
    Serial.printf("[GNSS][READBACK] UBX mode=%s; position=%s\n",
                  status.mode == 2 ? "Fixed" : "Rover",
                  status.hasPosition ? "valid" : "unavailable");
}

void BackendAgent::appendUbloxPosition(JsonDocument &doc,
                                       const UbxBaseStatus &status, const String &mode)
{
    JsonObject position = doc["bestpos"].to<JsonObject>();
    position["state"] = status.hasPosition ? "ok" : "unavailable";
    if (!status.hasPosition)
        return;
    position["message"] = "UBX";
    position["position_type"] = surveyInReadbackReady_ ? "FIXEDPOS" : "SURVEY-IN-ESTIMATE";
    position["datum"] = "WGS84";
    position["altitude_reference"] = "ELLIPSOID";
    std::array<char, 32> value{};
    snprintf(value.data(), value.size(), "%.11f", status.latitude);
    position["lat"] = String(value.data());
    snprintf(value.data(), value.size(), "%.11f", status.longitude);
    position["lon"] = String(value.data());
    snprintf(value.data(), value.size(), "%.4f", status.height);
    position["alt"] = String(value.data());
    if (surveyInReadbackReady_)
        saveSurveyResult(position, mode);
}

bool BackendAgent::refreshUnicoreReadback(String &error)
{
    unicoreQualityMs_ = 0;
    String mode;
    const auto success = UnicoreReadback::readMode(mode, error);
    DynamicJsonDocument readbackDoc(1024);
    readbackDoc["state"] = success ? "ok" : "error";
    readbackDoc["chip"] = "Unicorecomm";
    readbackDoc["revision"] = ++receiverBaseReadbackRevision_;
    readbackDoc["mode_raw"] = mode;
    const char *modeKind = success ? UnicoreReadback::modeKind(mode) : "unknown";
    readbackDoc["mode_kind"] = modeKind;
    readbackDoc["query"] = "MODE";
    if (success)
    {
        if (std::strcmp(modeKind, "survey_in") == 0)
        {
            if (!surveyInMonitoring_)
            {
                surveyInMonitoring_ = true;
                surveyInStartedMs_ = 0;
                surveyInTargetSeconds_ = 0;
            }
            uint32_t target = 0;
            if (std::sscanf(mode.c_str(), "MODE BASE TIME %" SCNu32, &target) == 1)
                surveyInTargetSeconds_ = target;
        }
        else
        {
            surveyInMonitoring_ = false;
        }
        JsonObject bestPosition = readbackDoc["bestpos"].to<JsonObject>();
        String positionError;
        if (!UnicoreReadback::readBestPosition(bestPosition, positionError))
        {
            surveyInReadbackHasPosition_ = false;
            bestPosition["state"] = "unavailable";
            bestPosition["error"] = positionError;
        }
        else
        {
            surveyInReadbackHasPosition_ = true;
            if (!bestPosition["horizontal_sigma_m"].isNull())
            {
                unicoreHorizontalSigma_ = bestPosition["horizontal_sigma_m"].as<float>();
                unicoreQualityMs_ = millis();
            }
            surveyInReadbackReady_ = String(bestPosition["position_type"] | "") == "FIXEDPOS";
        }
        saveSurveyResult(bestPosition, mode);
    }
    else
    {
        surveyInReadbackHasPosition_ = false;
        readbackDoc["error"] = error;
    }
    receiverBaseReadback_.clear();
    serializeJson(readbackDoc, receiverBaseReadback_);
    reconcileBaseStartupReadback();
    receiverBaseReadbackMs_ = millis();
    markStatusDirty();
    return success;
}

bool BackendAgent::refreshReceiverReadback(String &error)
{
    lastReceiverPollMs_ = millis();
    surveyInReadbackReady_ = false;
    surveyInReadbackHasPosition_ = false;
    if (sensorType_ == "Ublox")
        return refreshUbloxReadback(error);
    return refreshUnicoreReadback(error);
}

void BackendAgent::pollGnssStatus()
{
    if ((sensorType_ != "Unicorecomm" && sensorType_ != "Ublox") || workflowActive() || stationLock_.all)
        return;
    const uint32_t now = millis();
    if ((lastReceiverPollMs_ == 0 && now >= 5000UL) || (lastReceiverPollMs_ != 0 && now - lastReceiverPollMs_ >= 30000UL))
    {
        String error;
        refreshReceiverReadback(error);
        if (sensorType_ == "Ublox")
        {
            UbxNavigation navigation;
            if (UbloxReadback::readNavigation(navigation, error))
            {
                navigation_ = navigation;
                navigationMs_ = millis();
                markStatusDirty();
            }
            if (versionReadback_.isEmpty())
            {
                versionReadbackError_.clear();
                error.clear();
                if (!UbloxReadback::readVersion(versionReadback_, error))
                    versionReadbackError_ = error;
                receiverInfoMs_ = millis();
                markStatusDirty();
            }
            String satellites;
            if (UbloxReadback::readSatellites(satellites, error))
            {
                satelliteReadback_ = satellites;
                satelliteReadbackMs_ = millis();
                markStatusDirty();
            }
            UbxDop dop;
            if (UbloxReadback::readDop(dop, error))
            {
                dop_ = dop;
                dopMs_ = millis();
                markStatusDirty();
            }
        }
    }

    // MODE/BESTNAV are read-only receiver logs; do not request NMEA output.
}
