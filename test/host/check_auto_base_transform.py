"""Check that failed coordinate conversion cannot reach receiver configuration."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
agent = (root / 'src/functions/backend/Backend_Agent.cpp').read_text()
json_bool = agent[agent.index('    bool jsonBool('):agent.index('    String jsonString(')]
workflow = (root / 'src/functions/backend/Backend_Agent_Workflows.cpp').read_text()
begin = workflow.index('bool BackendAgent::completeAutoBaseSetup(')
end = workflow.index('    setAgentState("auto_setup_base");', begin)
method = workflow[begin:end] + '    reachedWrite = true;\n    (void)resultJson;\n    return true;\n}\n'
full_end = workflow.index('\nbool BackendAgent::runAutoBaseWorkflow(', begin)
full_method = workflow[begin:full_end].replace('BackendAgent::completeAutoBaseSetup(', 'BackendAgent::completeAutoBaseSetupFull(', 1)
run_end = workflow.index('\nbool BackendAgent::prepareReferenceCheckConfig(', full_end)
run_method = workflow[full_end:run_end].replace('completeAutoBaseSetup(', 'completeAutoBaseSetupFull(')
sampling = workflow[workflow.index('bool BackendAgent::waitForAutoBaseFix('):workflow.index('String BackendAgent::buildAutoBaseResult(')]
reference_methods = workflow[workflow.index('bool BackendAgent::waitForReferenceFix('):]
auto_config = workflow[workflow.index('bool BackendAgent::prepareAutoBaseConfig('):workflow.index('bool BackendAgent::startAutoBaseRover(')]
reference_config = workflow[workflow.index('bool BackendAgent::prepareReferenceCheckConfig('):workflow.index('bool BackendAgent::startReferenceRover(')]
result_method = workflow[workflow.index('String BackendAgent::buildAutoBaseResult('):begin]
result_method = result_method.replace('BackendAgent::buildAutoBaseResult(', 'BackendAgent::buildRealAutoBaseResult(', 1)
config_start = workflow.index('    DynamicJsonDocument baseConfig(CONFIG_DOCUMENT_SIZE);', begin)
config_end = workflow.index('    setAgentState(normalAgentState());', config_start)
config_update = workflow[config_start:config_end]
projection = (root / 'src/functions/backend/Backend_Agent_Projection.cpp').read_text()
begin = projection.index('bool BackendAgent::transformToVn2000(')
validation = projection[begin:]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include <array>
#include <cassert>
#include <cmath>
#include <cstring>
#include <limits>
#include <vector>
#include <strings.h>
#include "functions/backend/Vn2000_Datum.h"
#include "functions/backend/Base_Sample.h"
#include "functions/gnss/gnss_cmd_builder.h"
#include "functions/gnss/ublox_commands.h"
int tcpStreamMutex = 1; constexpr int MUTEX_TIMEOUT_MS = 1500, pdTRUE = 1;
constexpr size_t CONFIG_DOCUMENT_SIZE = 6144, AUTO_BASE_RESULT_SIZE = 6144, PROGRESS_DOCUMENT_SIZE = 8192;
uint32_t now = 1000;
uint32_t millis() { return now; }
template<class T, class L, class H> T constrain(T value, L low, H high) { return value < low ? T(low) : value > high ? T(high) : value; }
int pdMS_TO_TICKS(int n) { return n; }
void vTaskDelay(int ticks) { now += ticks; }
uint32_t disconnectAt = 0;
bool sourceAvailable = true;
const char *ntripRoverLastError() { return "caster disconnected"; }
struct GnssTelemetrySnapshot {
    uint32_t lastGgaMs; std::array<char, 16> fixStatus; double latitude, longitude, altitude;
};
GnssTelemetrySnapshot getGnssTelemetrySnapshot() { return {now, {"RTK_FIXED"}, 21, 105, 10}; }
uint32_t requestStarted = 0; bool provideLocation = false; int realLocation = 0;
int xQueueReset(int) { requestStarted = now; return 1; }
int xQueueReceive(int, void *out, int timeout) {
    now += timeout;
    if (!provideLocation) return 0;
    // Responses captured from the CORS backend's administrative-boundary resolver.
    if (realLocation == 1) {
        std::snprintf(static_cast<char *>(out), 1536, R"({"request_id":"boot:%u","location":{"input_coord":{"lat":21.08499,"lon":105.78666,"alt":-7.9815},"source":"administrative_boundaries_34","province_code":"01","province_name":"Thành phố Hà Nội","projection_options":[{"region":"Hà Nội","l0_deg":105,"k0":0.9999,"zone_width_deg":3}],"l0_deg":105,"k0":0.9999,"state":"resolved","zone_width_deg":3}})", requestStarted);
    } else if (realLocation == 2) {
        std::snprintf(static_cast<char *>(out), 1536, R"({"request_id":"boot:%u","location":{"input_coord":{"lat":21,"lon":105,"alt":10},"source":"administrative_boundaries_34","province_code":"25","province_name":"Tỉnh Phú Thọ","projection_options":[{"region":"Phú Thọ","l0_deg":104.75,"k0":0.9999,"zone_width_deg":3},{"region":"Vĩnh Phúc","l0_deg":105,"k0":0.9999,"zone_width_deg":3},{"region":"Hoà Bình","l0_deg":106,"k0":0.9999,"zone_width_deg":3}],"l0_deg":null,"k0":null,"state":"projection_ambiguous"}})", requestStarted);
    } else
    std::snprintf(static_cast<char *>(out), 1536, R"({"request_id":"boot:%u","location":{"input_coord":{"lat":21,"lon":105,"alt":10},"l0_deg":105,"k0":0.9999,"province_name":"Hà Nội","projection_options":[{"region":"A","l0_deg":105,"k0":0.9999},{"region":"B","l0_deg":105,"k0":0.9999},{"region":"C","l0_deg":105,"k0":0.9999}]}})", requestStarted);
    provideLocation = false; return 1;
}
bool allowLock = true;
int xSemaphoreTake(int, int) { return allowLock ? 1 : 0; }
void xSemaphoreGive(int) {}
Vn2000Datum sessionDatum;
Vn2000Datum ntripRoverDatum() { return sessionDatum; }
double coordinateNumber(JsonVariantConst v) {
    if (v.isNull()) return NAN;
    if (v.is<const char *>()) { const char *p = v.as<const char *>(); char *end = nullptr; double value = std::strtod(p, &end); return end != p && *end == 0 ? value : NAN; }
    return v.as<double>();
}
bool datumTransformOk = true;
bool transformVn2000(double lat, double lon, double alt, const Vn2000Datum &, Vn2000Result &out) {
    out.latitude = lat; out.longitude = lon; out.altitude = alt; return datumTransformOk;
}
MATCHER_PLACEHOLDER
struct BackendAgent {
    struct AutoBaseLocationReply { char json[1536]; };
    int autoBaseLocationQueue_ = 0;
    String statusBootId_ = "boot";
    bool workflowCancelRequested_ = false;
    uint32_t surveyInTargetSeconds_ = 0;
    String baseStartupState_, phase, phaseDetails;
    void markStatusDirty() {}
    bool stopNtripRoverLocked() { return true; }
    void setWorkflowProgress(const char *value, int, int, const String &details = String()) { phase = value; phaseDetails = details; }
    struct ProjectedPosition { double latitude, longitude, altitude; double northing = 0, easting = 0; };
    bool reachedWrite = false, transformOk = false, failFinalResult = false;
    bool receiverOk = true, saveOk = true, restartOk = true; int conversions = 0;
    String sensorType_ = "Ublox";
    String reportJson;
    String baseConfig_ = R"({"base_setup_method":"SURVEY_IN","survey_in_duration":300})";
    int configWrites = 0;
    bool restoreWorkflowBase(JsonObjectConst) { ++configWrites; return receiverOk; }
    bool saveStatePreferences() { return saveOk; }
    bool restartConfiguredNtrip() { return restartOk; }
    bool applyRoverMode() { return true; }
    int loopNtripRoverLocked() { return disconnectAt && now >= disconnectAt ? 504 : 200; }
    bool prepareAutoBaseConfig(JsonObject, String &, uint16_t &, String &, String &, String &, uint8_t &, uint32_t &, uint8_t &);
    bool startAutoBaseRover(const String &, uint16_t, const String &, const String &, const String &, uint8_t, String &error, String *selected) {
        if (!sourceAvailable) { error = "ERROR - NO STATION WITHIN 20 KM"; return false; }
        if (selected) *selected = "station";
        return true;
    }
    bool prepareReferenceCheckConfig(JsonObject, JsonObject &, double &, double &, double &, double &, double &, double &,
                                     String &, uint16_t &, String &, String &, String &, uint32_t &, uint16_t &);
    bool startReferenceRover(const String &, uint16_t, const String &, const String &, const String &, String &) { return true; }
    void setAgentState(const String &) {}
    String normalAgentState() { return "online"; }
    void publishConfigState(const char *) {}
    bool applyCandidate(String &);
    String buildRealAutoBaseResult(double, double, double, double, double, double, bool, bool, size_t,
                                   const String &, const String &, const String &, double, double, JsonObjectConst);
    String buildAutoBaseResult(double lat, double lon, double alt, double rawLat, double rawLon, double rawAlt,
                               bool transformed, bool restarted, size_t count, const String &source,
                               const String &code, const String &name, double meridian, double scale, JsonObjectConst report) {
        if (restarted && failFinalResult) return String();
        reportJson.clear(); serializeJson(report, reportJson);
        return buildRealAutoBaseResult(lat, lon, alt, rawLat, rawLon, rawAlt, transformed, restarted,
                                       count, source, code, name, meridian, scale, report);
    }
    bool transformToVn2000(double, double, double, double, double, ProjectedPosition &);
    bool transformItrfToVn2000(double, double, double, double, double, ProjectedPosition &) { ++conversions; return transformOk; }
    bool completeAutoBaseSetup(JsonObject, const std::vector<double> &, const std::vector<double> &, const std::vector<double> &, String &, String &, const String &);
    bool completeAutoBaseSetupFull(JsonObject, const std::vector<double> &, const std::vector<double> &, const std::vector<double> &, String &, String &, const String &);
    bool waitForAutoBaseFix(uint32_t, uint8_t, bool &, String &, const String &);
    bool collectAutoBaseSamples(int, std::vector<double> &, std::vector<double> &, std::vector<double> &, bool &, String &, const String &);
    bool runAutoBaseWorkflow(JsonObject);
    bool waitForReferenceFix(uint32_t, String &);
    bool collectReferenceSamples(uint16_t, std::vector<double> &, std::vector<double> &, std::vector<double> &, String &);
    String buildReferenceCheckResult(JsonObject, double, double, double, size_t);
    bool runReferenceCheckWorkflow(JsonObject);
};
'''
matcher = workflow[workflow.index('    bool acceptAutoBaseLocationReply('):workflow.index('} // namespace')]
harness = harness.replace('MATCHER_PLACEHOLDER', matcher)
candidate = r'''
bool BackendAgent::applyCandidate(String &failureReason) {
    ProjectedPosition result{21, 105, 10};
    DynamicJsonDocument report(CONFIG_DOCUMENT_SIZE);
    if (deserializeJson(report, reportJson)) return false;
    const bool transformed=true;
    const double centralMeridianDeg=105, scale=0.9999;
    const char *projectionSource="rtcm1025";
    const String provinceCode="01", provinceName="Hanoi";
''' + config_update + '\n    return true;\n}\n'
checks = r'''
int main() {
    BackendAgent agent; BackendAgent::ProjectedPosition result{21, 105, 10};
    assert(!agent.transformToVn2000(21, 105, 10, NAN, 0.9999, result));
    assert(!agent.transformToVn2000(21, 105, 10, 105, NAN, result));
    assert(agent.conversions == 0);
    DynamicJsonDocument doc(256); JsonObject payload = doc.to<JsonObject>();
    std::vector<double> lat{21}, lon{105}, alt{10}; String resultJson, error;
    payload["enable_itrf_vn2000_transform"] = true;
    payload["ip"] = "other-caster.example";
    assert(agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station"));
    DynamicJsonDocument report(4096);
    assert(!deserializeJson(report, agent.reportJson));
    assert(report["transform_applied"] == false && report["projection_source"] == "not_used");
    assert(report["calculated_coord"]["lat"] == report["input_coord"]["lat"]);
    assert(agent.conversions == 0);
    payload["enable_itrf_vn2000_transform"] = false;
    assert(agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station"));
    assert(!agent.reachedWrite && !resultJson.isEmpty() && agent.conversions == 0);
    std::vector<double> preciseLat{-84.54808557036529}, preciseLon{105}, preciseAlt{650.1759102147155};
    assert(agent.completeAutoBaseSetup(payload, preciseLat, preciseLon, preciseAlt, resultJson, error, "station"));
    report.clear(); assert(!deserializeJson(report, agent.reportJson));
    assert(report["output_coord"]["lat"] == "-84.548085570");
    assert(report["output_coord"]["alt"] == "650.1759");
    payload["ip"] = "VNGEONET.VN";
    assert(agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station"));
    report.clear(); assert(!deserializeJson(report, agent.reportJson));
    assert(report["transform_applied"] == false && report["projection_source"] == "not_used");
    payload["enable_itrf_vn2000_transform"] = "false";
    assert(agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station"));
    report.clear(); assert(!deserializeJson(report, agent.reportJson));
    assert(report["transform_applied"] == false);
    payload["enable_itrf_vn2000_transform"] = "off";
    assert(agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station"));
    payload["enable_itrf_vn2000_transform"] = 0;
    assert(agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station"));
    payload["enable_itrf_vn2000_transform"] = "on";
    assert(!agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station"));
    assert(error == "missing RTCM 1021 from this CORS session");
    payload["enable_itrf_vn2000_transform"] = true;
    assert(!agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station"));
    assert(error == "missing RTCM 1021 from this CORS session");
    sessionDatum.has1021 = true;
    assert(!agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station"));
    assert(error == "location reply queue could not be allocated");
    agent.autoBaseLocationQueue_ = 1;
    assert(!agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station"));
    assert(error == "backend location ACK timed out or did not match sampled LLH");
    agent.workflowCancelRequested_ = true;
    assert(!agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station"));
    assert(error == "cancelled by user");
    agent.workflowCancelRequested_ = false;
    provideLocation = true;
    const bool located = agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station");
    if (!located) std::fprintf(stderr, "location report failure: %s\n", error.c_str());
    assert(located);
    report.clear(); assert(!deserializeJson(report, agent.reportJson));
    assert(report["location"]["province_name"] == "Hà Nội");
    assert(report["location"]["projection_options"][0]["l0_deg"] == 105);
    DynamicJsonDocument resultDoc(AUTO_BASE_RESULT_SIZE);
    assert(!deserializeJson(resultDoc, resultJson));
    assert(resultDoc["conversion_report"]["location"]["province_name"] == "Hà Nội");
    assert(agent.applyCandidate(error));
    DynamicJsonDocument applied(8192);
    assert(!deserializeJson(applied, agent.baseConfig_));
    assert(applied["conversion_report"]["location"]["province_name"] == "Hà Nội");
    assert(applied["conversion_report"]["location"]["projection_options"].size() == 3);
    // Exercise actual CORS replies: a unique projection applies; ambiguous options do not.
    realLocation = 1; provideLocation = true;
    std::vector<double> hanoiLat{21.08499}, hanoiLon{105.78666}, hanoiAlt{-7.9815};
    assert(agent.completeAutoBaseSetup(payload, hanoiLat, hanoiLon, hanoiAlt, resultJson, error, "station"));
    report.clear(); assert(!deserializeJson(report, agent.reportJson));
    assert(report["location"]["province_name"] == "Thành phố Hà Nội");
    assert(report["location"]["projection_options"].size() == 1);
    assert(agent.applyCandidate(error));
    applied.clear(); assert(!deserializeJson(applied, agent.baseConfig_));
    assert(applied["conversion_report"]["location"]["state"] == "resolved");
    realLocation = 2; provideLocation = true; agent.reachedWrite = false;
    assert(!agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station"));
    assert(error == "province projection unresolved; RTCM 1025 or a unique server region is required");
    assert(!agent.reachedWrite);
    realLocation = 0;
    sessionDatum.has1025 = true; sessionDatum.centralMeridianDeg = 105; sessionDatum.scale = 0.9999;
    sessionDatum.projectionLongitudeRaw = 9545454545LL; sessionDatum.projectionFrameBytes = 31;
    std::strcpy(sessionDatum.projectionFrameHex, "d3001940102030405060708090a0b0c0d0e0f00112233445566778899aabb");
    sessionDatum.kT = 1.00000008613; sessionDatum.count1021 = 2;
    datumTransformOk = false;
    assert(!agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station"));
    assert(!agent.reachedWrite && error == "VN2000 conversion failed; no candidate coordinates were installed");
    datumTransformOk = true;
    assert(agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station"));
    report.clear();
    assert(!deserializeJson(report, agent.reportJson));
    assert(report["source"]["mountpoint"] == "station" && report["projection_source"] == "rtcm1025");
    assert(report["parameter_source"] == "rtcm1021" && report["received_messages"]["1021"] == 2);
    assert(report["zone_width_source"] == "inferred_from_k0");
    assert(report["zone_width_deg"] == 3);
    assert(std::abs(coordinateNumber(report["parameters"]["kT"]) - 1.00000008613) < 1e-15);
    assert(report["receiver_write_completed"] == false && report["auto_applied"] == false);
    assert(agent.applyCandidate(error));
    applied.clear();
    assert(!deserializeJson(applied, agent.baseConfig_));
    assert(applied["conversion_report"]["rtcm1025"]["projection_type"] == 0);
    assert(applied["conversion_report"]["rtcm1025"]["raw_l0"] == "9545454545");
    assert(applied["conversion_report"]["rtcm1025"]["frame_bytes"] == 31);
    assert(applied["conversion_report"]["rtcm1025"]["frame_hex"] == sessionDatum.projectionFrameHex);
    assert(applied["conversion_report"]["rtcm1025"]["frame_truncated"] == false);
    assert(applied["conversion_report"]["receiver_write_completed"] == true);
    sessionDatum.scale = 0.9996;
    assert(agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station"));
    report.clear(); assert(!deserializeJson(report, agent.reportJson));
    assert(report["zone_width_deg"] == 6);
    sessionDatum.scale = 0.9998;
    assert(agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station"));
    report.clear(); assert(!deserializeJson(report, agent.reportJson));
    assert(!report.containsKey("zone_width_deg"));
    payload["resN"] = "invalid";
    assert(!agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station"));
    assert(error == "invalid CORS shift");
    payload.remove("resN");
    sessionDatum.has1025 = false;
    payload["l0_deg"] = 105; payload["k0"] = 0.9999;
    assert(agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station"));
    payload["auto_apply"] = true;
    agent.failFinalResult = true; agent.reachedWrite = false;
    assert(!agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station"));
    assert(!agent.reachedWrite && error == "cannot allocate Auto Base result");
    agent.failFinalResult = false;
    assert(agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station"));
    assert(agent.reachedWrite);
    payload["auto_apply"] = false; payload["enable_itrf_vn2000_transform"] = false;
    sessionDatum.has1025 = true; sessionDatum.count1025 = 2; sessionDatum.projectionScaleRaw = 660000000;
    assert(agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station"));
    report.clear(); assert(!deserializeJson(report, agent.reportJson));
    assert(report["transform_applied"] == false && report["rtcm1025_used"] == false);
    assert(report["received_messages"]["1025"] == 2 && report["rtcm1025"]["raw_k0"] == 660000000);
    allowLock = false;
    assert(agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station"));
    payload["enable_itrf_vn2000_transform"] = true;
    assert(!agent.completeAutoBaseSetup(payload, lat, lon, alt, resultJson, error, "station"));
    assert(error == "cannot acquire rover transport for datum readback");
    allowLock = true;
    BackendAgent full;
    DynamicJsonDocument fullRequest(512); fullRequest["ip"] = "other-caster.example"; fullRequest["auto_apply"] = true;
    fullRequest["port"] = 2101; fullRequest["user"] = "user"; fullRequest["password"] = "password"; fullRequest["mountpoint"] = "station";
    const String previous = full.baseConfig_;
    assert(full.completeAutoBaseSetupFull(fullRequest.as<JsonObject>(), lat, lon, alt, resultJson, error, "station"));
    DynamicJsonDocument finalConfig(8192), finalResult(8192);
    assert(!deserializeJson(finalConfig, full.baseConfig_) && !deserializeJson(finalResult, resultJson));
    assert(finalConfig["base_setup_method"] == "FIXED_LLA" && finalConfig["accuracy"] == 5);
    assert(finalResult["conversion_report"]["receiver_write_completed"] == true && finalResult["configured_ntrip_restarted"] == true);
    BackendAgent failResult; failResult.failFinalResult = true;
    assert(!failResult.completeAutoBaseSetupFull(fullRequest.as<JsonObject>(), lat, lon, alt, resultJson, error, "station"));
    assert(failResult.configWrites == 0 && failResult.baseConfig_ == previous && error == "cannot allocate Auto Base result");
    BackendAgent failReadback; failReadback.receiverOk = false;
    assert(!failReadback.completeAutoBaseSetupFull(fullRequest.as<JsonObject>(), lat, lon, alt, resultJson, error, "station"));
    assert(failReadback.baseConfig_ == previous && error == "receiver did not confirm automatically measured Fixed LLA");
    BackendAgent failSave; failSave.saveOk = false;
    assert(!failSave.completeAutoBaseSetupFull(fullRequest.as<JsonObject>(), lat, lon, alt, resultJson, error, "station"));
    assert(failSave.baseConfig_ == previous && error == "could not save automatically applied Fixed LLA");
    BackendAgent failRestart; failRestart.restartOk = false;
    assert(!failRestart.completeAutoBaseSetupFull(fullRequest.as<JsonObject>(), lat, lon, alt, resultJson, error, "station"));
    assert(failRestart.baseConfig_ == previous && error == "could not restore configured NTRIP after applying Fixed LLA");
    now = 1000; disconnectAt = 0;
    BackendAgent workflow; fullRequest["source_mode"] = "nearest";
    assert(workflow.runAutoBaseWorkflow(fullRequest.as<JsonObject>()));
    assert(workflow.phase == "completed" && workflow.configWrites == 1);
    finalConfig.clear(); assert(!deserializeJson(finalConfig, workflow.baseConfig_));
    assert(finalConfig["base_setup_method"] == "FIXED_LLA" && finalConfig["accuracy"] == 5);
    finalResult.clear(); assert(!deserializeJson(finalResult, workflow.phaseDetails));
    assert(finalResult["sample_count"] == 60 && finalResult["source_mountpoint"] == "station");
    now = 1000; sourceAvailable = false; BackendAgent fallback;
    assert(fallback.runAutoBaseWorkflow(fullRequest.as<JsonObject>()));
    finalConfig.clear(); assert(!deserializeJson(finalConfig, fallback.baseConfig_));
    assert(fallback.phase == "completed" && finalConfig["base_setup_method"] == "SURVEY_IN" && finalConfig["accuracy"] == 5);
    sourceAvailable = true;
    fullRequest["port"] = 0; BackendAgent invalidAuto;
    assert(!invalidAuto.runAutoBaseWorkflow(fullRequest.as<JsonObject>()) && invalidAuto.configWrites == 0 && invalidAuto.phase == "failed");
    fullRequest["port"] = 2101;
    now = 1000; disconnectAt = 7000;
    BackendAgent disconnected;
    assert(!disconnected.runAutoBaseWorkflow(fullRequest.as<JsonObject>()));
    assert(disconnected.phase == "failed" && disconnected.baseConfig_ == previous && disconnected.configWrites == 1);
    now = 1000; disconnectAt = 0;
    BackendAgent allocationFailure; allocationFailure.failFinalResult = true;
    assert(!allocationFailure.runAutoBaseWorkflow(fullRequest.as<JsonObject>()));
    assert(allocationFailure.phase == "failed" && allocationFailure.baseConfig_ == previous && allocationFailure.configWrites == 1);
    now = 1000;
    BackendAgent persistenceFailure; persistenceFailure.saveOk = false;
    assert(!persistenceFailure.runAutoBaseWorkflow(fullRequest.as<JsonObject>()));
    assert(persistenceFailure.phase == "failed" && persistenceFailure.baseConfig_ == previous && persistenceFailure.configWrites == 2);
    DynamicJsonDocument referenceRequest(512);
    referenceRequest["reference_coords"]["lat"] = 21;
    referenceRequest["reference_coords"]["lon"] = 105;
    referenceRequest["reference_coords"]["alt"] = 10;
    referenceRequest["ip"] = "other-caster.example"; referenceRequest["port"] = 2101;
    referenceRequest["user"] = "user"; referenceRequest["password"] = "password"; referenceRequest["mountpoint"] = "station";
    referenceRequest["samples"] = 5;
    now = 1000; BackendAgent reference;
    assert(reference.runReferenceCheckWorkflow(referenceRequest.as<JsonObject>()));
    assert(reference.phase == "reference_check_completed" && reference.baseConfig_ == previous && reference.configWrites == 1);
    finalResult.clear(); assert(!deserializeJson(finalResult, reference.phaseDetails));
    assert(finalResult["sample_count"] == 5 && finalResult["delta_n_m"] == 0 && finalResult["delta_e_m"] == 0);
    referenceRequest["reference_coords"]["lat"] = 91; BackendAgent invalidReference;
    assert(!invalidReference.runReferenceCheckWorkflow(referenceRequest.as<JsonObject>()) && invalidReference.configWrites == 0);
    referenceRequest["reference_coords"]["lat"] = 21;
    now = 1000; disconnectAt = 3000; BackendAgent referenceDisconnected;
    assert(!referenceDisconnected.runReferenceCheckWorkflow(referenceRequest.as<JsonObject>()));
    assert(referenceDisconnected.phase == "reference_check_failed" && referenceDisconnected.baseConfig_ == previous && referenceDisconnected.configWrites == 1);
}
'''
with tempfile.TemporaryDirectory(prefix='auto-base-transform-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + json_bool + validation + result_method + method + full_method + auto_config + sampling + run_method + reference_config + reference_methods + candidate + checks)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'), '-I' + str(root / 'include'), '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: Auto Base and reference workflows, sampling, conversion and failure recovery')
