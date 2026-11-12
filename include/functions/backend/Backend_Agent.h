#ifndef BACKEND_AGENT_H
#define BACKEND_AGENT_H

#include <Arduino.h>
#include <ArduinoJson.h>
#include "functions/backend/Station_Lock.h"
#include "functions/gnss/gnss_cmd_builder.h"
#include "functions/gnss/Ubx_Base_Status.h"
#include "functions/gnss/Ubx_Navigation.h"
#include "functions/gnss/Unicore_Reply.h"
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>
#include <freertos/task.h>
#include <array>
#include <memory>
#include <vector>

class BackendAgentWebsocket;
struct GnssTelemetrySnapshot;

// Device agent for backend commands, status, provisioning and base workflows.
// Receiver coordinates come from NMEA or Unicore readback; RTCM is forwarded.
class BackendAgent
{
public:
    BackendAgent();
    ~BackendAgent();
    void begin();
    bool initializeBaseAtBoot(GnssCmdBuilder::GnssSensorType detected);
    void loop();
    bool detectGnssChip(Stream &gnssStream, bool force = false);
    bool applyRoverMode();
    void setDetectedChipIfUnknown(const String &chipType);
    const String &sensorType() const { return sensorType_; }

    void onMqttConnected();
    void onMqttDisconnected();
    void onNetworkChanged();
    void onMqttMessage(const char *topic, const uint8_t *payload, size_t length);

    void enqueueNmea(const uint8_t *data, size_t length);
    void enqueueRtcm(const uint8_t *data, size_t length);

    void publishStatus(bool force = false);
    void setAgentState(const String &state);
    String lwtPayload() const;

    const String &serial() const { return serialNumber_; }
    bool isLocked() const { return stationLock_.locked(); }
    bool isServerLocked(uint8_t serverId) const { return stationLock_.locked(serverId); }
    bool isProvisioned() const { return provisioned_; }
    bool licenseValid() const { return licenseValid_; }
    bool baseStartupConfigured() const
    {
        return baseStartupState_ == "fixed_restored" || baseStartupState_ == "survey_started" || baseStartupState_ == "preserved" || baseStartupState_ == "configured";
    }
    bool mqttConnected() const;
    bool websocketConnected() const;
    bool controlPlaneFailOpen() const { return controlPlaneFailOpen_; }
    bool workflowActive() const { return workflowTask_ != nullptr; }

    String serviceConfigJson() const;
    String baseConfigJson() const;
    String licenseToken() const;

    // Resolve per-server stream activation from service settings and fail-open state.
    static bool effectiveStreamActive(const JsonObjectConst &service,
                                      uint8_t serverId,
                                      bool failOpen);

private:
    String serialNumber_;
    String agentState_ = "initializing";
    String deviceName_;
    String lastCommandResult_ = "{}";
    String autoBaseProgress_ = "{}";
    String baseConfig_ = "{}";
    String serviceConfig_ = "{}";
    String nvsInventory_;
    uint32_t nvsInventoryMs_ = 0;
    String gnssVerification_;
    uint32_t gnssVerificationMs_ = 0;
    String receiverBaseReadback_ = R"({"state":"not_read","chip":"Unicorecomm","mode_kind":"unknown"})";
    String surveyInResult_ = "{}";
    String baseStartupState_ = "pending";
    String baseStartupError_;
    bool baseStartupAttempted_ = false;
    String licenseToken_;
    String sensorType_ = "UNKNOWN";

    bool provisioned_ = false;
    StationLock stationLock_;
    bool licenseValid_ = false;
    bool mqttConnected_ = false;
    bool websocketConnected_ = false;
    bool controlPlaneFailOpen_ = false;
    volatile bool statusDirty_ = false;
    volatile bool workflowCancelRequested_ = false;

    uint32_t lastStatusMs_ = 0;
    uint32_t firmwareSize_ = 0;
    bool statusPublishConfirmed_ = false;
    uint32_t lastChipProbeMs_ = 0;
    uint32_t controlPlaneArmedMs_ = 0;
    uint32_t lastControlCheckMs_ = 0;
    uint32_t lastMqttAckMs_ = 0;
    uint32_t lastWebsocketAckMs_ = 0;
    uint32_t recoveryStartedMs_ = 0;
    int32_t lastMqttAckSequence_ = -1;
    int32_t lastWebsocketAckSequence_ = -1;
    int32_t statusSequence_ = 0;
    int32_t failOpenEntrySequence_ = -1;
    uint32_t receiverBaseReadbackMs_ = 0;
    uint32_t receiverBaseReadbackRevision_ = 0;
    uint32_t lastReceiverPollMs_ = 0;
    String versionReadback_, versionReadbackError_;
    uint32_t receiverInfoMs_ = 0;
    String satelliteReadback_;
    uint32_t satelliteReadbackMs_ = 0;
    UbxNavigation navigation_;
    UbxDop dop_;
    uint32_t navigationMs_ = 0;
    uint32_t dopMs_ = 0;
    float unicoreHorizontalSigma_ = 0;
    uint32_t unicoreQualityMs_ = 0;
    bool surveyInResultPending_ = false;
    bool surveyInReadbackReady_ = false;
    bool surveyInReadbackHasPosition_ = false;
    bool surveyInMonitoring_ = false;
    uint32_t surveyInStartedMs_ = 0;
    uint32_t surveyInTargetSeconds_ = 0;
    String statusBootId_;

    struct AutoBaseLocationReply { char json[1536]; };
    QueueHandle_t autoBaseLocationQueue_ = nullptr;
    QueueHandle_t nmeaQueue_ = nullptr;
    QueueHandle_t rtcmQueue_ = nullptr;
    std::unique_ptr<BackendAgentWebsocket> websocket_;
    TaskHandle_t workflowTask_ = nullptr;
    String workflowKind_;
    String workflowPayload_;

    void loadPreferences();
    bool saveStatePreferences();
    void saveDetectedChip(const char *chipType);
    bool probeUnicore(Stream &stream, String &identityLine);
    bool probeUblox(Stream &stream);
    bool probePassiveUblox(Stream &stream);
    void ensureDefaultServiceConfig();
    String normalAgentState() const;
    void setupWebsocket();
    void refreshWebsocket();
    void loopWebsocket();
    void drainDataQueues();
    void retryUnknownChipProbe();
    void evaluateControlPlaneFailover();
    bool startWorkflow(const String &kind, const String &payload);
    void runWorkflow();
    static void workflowTaskThunk(void *parameter);
    void requestWorkflowStop();
    bool writeGnssCommands(const GnssCmdBuilder::CommandList &commands);
    bool writeUnicoreCommand(const uint8_t *data, size_t length, String &error);
    bool waitForUnicoreReply(UnicoreReply &reply, bool written);
    void handleUnicoreAck(const UnicoreReply &reply, const uint8_t *data, size_t length);
    bool exchangeUbloxRoverCommand(const GnssCmdBuilder::Command &command, bool poll);
    bool configureUbloxRover();
    bool waitForRoverGga(uint32_t startedMs);
    void setWorkflowProgress(const String &phase, uint8_t step, uint8_t total,
                             const String &details = String());
    bool runAutoBaseWorkflow(JsonObject payload);
    bool prepareAutoBaseConfig(JsonObject payload, String &host, uint16_t &port,
                               String &username, String &password, String &mountpoint,
                               uint8_t &ntripVersion, uint32_t &timeoutSeconds,
                               uint8_t &fixedStreakRequired);
    bool startAutoBaseRover(const String &host, uint16_t port, const String &username,
                            const String &password, const String &mountpoint,
                            uint8_t ntripVersion, String &error, String *selectedMountpoint = nullptr);
    bool waitForAutoBaseFix(uint32_t timeoutSeconds, uint8_t fixedStreakRequired,
                            bool &cancelled, String &failureReason, const String &sourceMountpoint);
    bool collectAutoBaseSamples(int configuredSamples, std::vector<double> &latitudes,
                                std::vector<double> &longitudes,
                                std::vector<double> &altitudes, bool &cancelled,
                                String &failureReason, const String &sourceMountpoint);
    bool completeAutoBaseSetup(JsonObject payload, const std::vector<double> &latitudes,
                               const std::vector<double> &longitudes,
                               const std::vector<double> &altitudes,
                               String &resultJson, String &failureReason, const String &sourceMountpoint);
    String buildAutoBaseResult(double finalLatitude, double finalLongitude,
                               double finalAltitude, double rawLatitude,
                               double rawLongitude, double rawAltitude,
                               bool transformed, bool transportRestored,
                               size_t sampleCount, const String &projectionSource,
                               const String &provinceCode, const String &provinceName,
                               double centralMeridianDeg, double scale, JsonObjectConst report);
    bool runReferenceCheckWorkflow(JsonObject payload);
    bool prepareReferenceCheckConfig(JsonObject payload, JsonObject &reference,
                                     double &referenceLatitude, double &referenceLongitude,
                                     double &referenceAltitude, double &restoreLatitude,
                                     double &restoreLongitude, double &restoreAltitude,
                                     String &host, uint16_t &port, String &username,
                                     String &password, String &mountpoint,
                                     uint32_t &timeoutSeconds, uint16_t &requestedSamples);
    bool startReferenceRover(const String &host, uint16_t port, const String &username,
                                    const String &password, const String &mountpoint, String &error);
    bool waitForReferenceFix(uint32_t timeoutSeconds, String &failureReason);
    bool collectReferenceSamples(uint16_t requestedSamples, std::vector<double> &latitudes,
                                 std::vector<double> &longitudes,
                                 std::vector<double> &altitudes, String &failureReason);
    String buildReferenceCheckResult(JsonObject reference, double measuredLatitude,
                                     double measuredLongitude, double measuredAltitude,
                                     size_t sampleCount);
    bool restartConfiguredNtrip(bool transportLocked = false);
    int loopNtripRoverLocked();
    bool stopNtripRoverLocked();
    bool applyBaseCoordinates(double latitude, double longitude, double altitude, JsonObjectConst base);
    bool restoreWorkflowBase(JsonObjectConst base);
    void reconcileBaseStartupReadback();
    bool refreshReceiverReadback(String &error);
    bool refreshUbloxReadback(String &error);
    void updateUbloxSurveyState(const UbxBaseStatus &status);
    void logUbloxReadback(const UbxBaseStatus &status);
    void appendUbloxPosition(JsonDocument &doc, const UbxBaseStatus &status,
                             const String &mode);
    bool refreshUnicoreReadback(String &error);
    struct StartupPosition {
        double latitude = 0.0;
        double longitude = 0.0;
        double altitude = 0.0;
        bool ellipsoid = false;
    };
    bool buildStartupCommands(JsonObjectConst base, GnssCmdBuilder::GnssSensorType detected,
                              bool restoreFixed, GnssCmdBuilder::CommandList &commands,
                              StartupPosition &position, String &error);
    bool verifyStartupReadback(GnssCmdBuilder::GnssSensorType detected, bool restoreFixed,
                               const StartupPosition &expected, String &error);
    void saveSurveyResult(JsonObjectConst bestPosition, const String &mode);
    void pollGnssStatus();
    void startBootAutoBaseWhenReady();
    struct ProjectedPosition {
        double latitude;
        double longitude;
        double altitude;
        double northing = 0.0;
        double easting = 0.0;
        double projectedHeight = 0.0;
    };
    bool transformToVn2000(double latitude, double longitude, double altitude,
                           double centralMeridianDeg, double scale, ProjectedPosition &result);
    static bool transformItrfToVn2000(double latitude, double longitude, double altitude,
                                     double centralMeridianDeg, double scale, ProjectedPosition &result);
    bool getProvinceProjection(const String &code, double &centralMeridianDeg,
                               double &scale, String &name, std::array<double, 3> &meridians) const;
    void markStatusDirty() { statusDirty_ = true; }

    String buildStatusPayload();
    String buildLwtPayload() const;
    String statusForPayload(bool anyStream, bool onDemand) const;
    void appendStatusFields(JsonDocument &doc, const String &status,
                            const GnssTelemetrySnapshot &gnss, uint32_t nowMs,
                            const String &timestamp) const;
    void appendAutoBaseProgress(JsonDocument &doc, const GnssTelemetrySnapshot &gnss,
                                uint32_t nowMs) const;
    void appendSystemInfo(JsonDocument &doc, uint32_t nowMs,
                          const String &timestamp) const;
    void appendStartupInfo(JsonObject system) const;
    JsonObject appendSurveyInfo(JsonObject system, uint32_t nowMs) const;
    void appendReceiverReadback(JsonObject system, JsonObject survey) const;
    void appendResourceInfo(JsonObject system, const String &timestamp) const;
    void appendGnssStatus(JsonDocument &doc, const GnssTelemetrySnapshot &gnss,
                          uint32_t nowMs) const;
    void appendNtripStatus(JsonDocument &doc, const JsonObjectConst &service,
                           bool server1Active, bool server2Active) const;
    void appendTransportStatus(JsonDocument &doc, const GnssTelemetrySnapshot &gnss,
                               uint32_t nowMs, int32_t signal) const;
    String statusTopic() const;
    String rawDataTopic() const;
    String commandTopic() const;
    String controlAckTopic() const;

    void handleWebsocketText(const String &message);
    void handleCommand(const String &source, const String &message);
    void executeCommand(const String &source, const String &command,
                        const String &commandId, JsonDocument &doc,
                        JsonObject payload);
    bool executeLicenseCommand(JsonObject payload, String &error, String &detail,
                               bool &restartAfterCommand);
    bool executeServiceConfigCommand(JsonObject payload, String &error, String &detail);
    bool executeRawCommand(JsonDocument &doc, JsonObject payload,
                           String &error, String &detail);
    bool executeAutoBaseCommand(JsonObject payload, String &error, String &detail);
    bool verifyGnssConfig(JsonObjectConst payload, const String &commandId, String &error);
    bool verifyUnicoreConfig(JsonObjectConst payload, const String &commandId, String &error);
    bool executeReferenceCheckCommand(JsonObject payload, String &error, String &detail);
    bool executeProvinceCommand(JsonObject payload, String &error, String &detail);
    bool executeBasicCommand(const String &command, JsonObject payload,
                             String &error, String &detail);
    bool executeStreamCommand(JsonObject payload, String &error, String &detail);
    bool executeBaseStatusCommand(String &error, String &detail);
    bool executeStopWorkflowCommand(String &error, String &detail);
    void finishCommand(const String &source, const String &command,
                       const String &commandId, bool success,
                       const String &error, const String &detail,
                       bool restartAfterCommand);
    void handleControlAck(const String &source, const String &message, bool retained);
    bool applyLockCommand(JsonObjectConst payload, String &error);
    void recordCommandResult(const String &command, const String &source,
                             const String &status, const String &detail,
                             const String &commandId);
    void publishConfigState(const char *kind);
    bool applyServiceStreamCommand(JsonObject payload, String &error);
    bool executeRawCommands(JsonArray commands, String &error, const String &sensorType = String());
    void publishTextFallback(const String &message);

    friend class BackendAgentWebsocket;
};

extern BackendAgent backendAgent;

// Expose device permissions and fail-open state to network transports.
bool backendDeviceLocked(uint8_t serverId = 0);
bool backendControlPlaneFailOpen();
bool backendDeviceProvisioned();
bool backendLicenseValid();
bool backendBaseStartupConfigured();

#endif // BACKEND_AGENT_H
