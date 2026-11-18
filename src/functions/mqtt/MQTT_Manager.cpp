#include "functions/mqtt/MQTT_Manager.h"
#include "Top_Lvl_Config.h"
#include "Prog_Config.h"
#include "functions/backend/Backend_Agent.h"
#include "functions/backend/cmd_handler.h"
#include "functions/mqtt/MqttWrite.h"
#include <Preferences.h>
#include <cstring>
#include "helper.h"

// ================= ĐỊNH NGHĨA CÁC ĐỐI TƯỢNG CẦN CHO KẾT NỐI =================
#include "hardware/Wifi_handler.h"
#include "hardware/Sim_handler.h"

namespace
{
  WiFiClient &wifiMqttClient()
  {
    static WiFiClient client;
    return client;
  }
}

namespace
{
  class MqttGsmClient : public Client
  {
  public:
    MqttGsmClient(TinyGsm &modem, uint8_t mux) : inner_(modem, mux) {}
    using Print::write;

    int connect(IPAddress ip, uint16_t port) override { return inner_.connect(ip, port); }
    int connect(const char *host, uint16_t port) override { return inner_.connect(host, port); }
    int connect(const char *host, uint16_t port, int timeout_s) { return inner_.connect(host, port, timeout_s); }
    size_t write(uint8_t value) override { return inner_.write(value); }
    size_t write(const uint8_t *data, size_t size) override
    {
      const auto sent = writeMqttChunks(data, size, [this](const uint8_t *part, size_t count)
                                        { return inner_.write(part, count); });
      if (sent != size)
      {
        Serial.printf("[MQTT][ERROR] Modem short write: %u/%u bytes; reconnect required\n",
                      static_cast<unsigned>(sent), static_cast<unsigned>(size));
        // The broker may have received a packet prefix. Discard this TCP stream
        // so the next CONNECT starts a fresh MQTT frame boundary.
        inner_.stop();
      }
      return sent;
    }
    int available() override { return inner_.available(); }
    int read() override { return inner_.read(); }
    int read(uint8_t *buf, size_t size) override { return inner_.read(buf, size); }
    int peek() override { return inner_.peek(); }
    void flush() override { inner_.flush(); }
    void stop() override { inner_.stop(); }
    uint8_t connected() override { return inner_.connected(); }
    explicit operator bool() override { return static_cast<bool>(inner_); }

  private:
    TinyGsmClient inner_;
  };

  MqttGsmClient &gsmMqttClient()
  {
    static MqttGsmClient client(getModem(), 1);
    return client;
  }
  MqttGsmClient &gsmProbeClient()
  {
    static MqttGsmClient client(getModem(), 4);
    return client;
  }
  WiFiClient &wifiProbeClient()
  {
    static WiFiClient client;
    return client;
  }
}
PubSubClient &mqttClient()
{
  static PubSubClient client(wifiMqttClient());
  return client;
}

void initializeMqttGsmClients()
{
  (void)gsmMqttClient();
  (void)gsmProbeClient();
}


namespace
{
  String &mqttServerHost()
  {
    static String serverHost;
    return serverHost;
  }

  uint32_t &lastMqttConnectAttemptMs()
  {
    static uint32_t ms = 0;
    return ms;
  }
}

Client &activeMqttClient()
{
  return isWifiConnection() ? static_cast<Client &>(wifiMqttClient())
                            : static_cast<Client &>(gsmMqttClient());
}

// ================= ĐỊNH NGHĨA HÀM =================

/** @brief Implements mqttCallback. */
void mqttCallback(char *topic, byte *payload, unsigned int length)
{
  if (!topic || !payload || length == 0)
    return;
  backendAgent().onMqttMessage(topic, payload, length);

  // Dispatch plain-text ATG commands separately from JSON device commands.
  if (strcmp(topic, TOPIC_SUB_CMD) == 0)
  {
    if (backendAgent().isLocked() || length > 1024 || memchr(payload, '\0', length))
    {
      Serial.println("[MQTT DOWNLINK] Rejected locked device or invalid legacy command.");
      return;
    }
    Serial.printf("[MQTT DOWNLINK] Nhan lenh legacy (%u bytes).\n", length);
    String cmd;
    cmd.reserve(length);
    for (unsigned int i = 0; i < length; ++i)
      cmd += static_cast<char>(payload[i]);

    // Phân tích lệnh ATG để cấu hình ESP32, kết nối hoặc receiver GNSS.
    std::vector<String> cmdWords = splitCommand(cmd);
    cmd_action_t action = handleCommand(cmdWords);
    if (action == cmd_action_t::CMD_ACTION_ESP_RESTART)
    {
      Serial.println("[MQTT DOWNLINK] Yeu cau ESP32 khoi dong lai.");
      shutdownTcpTransportBeforeRestart();
      ESP.restart();
    }
  }
}

/** @brief Implements probeMqttTransport. */
bool probeMqttTransport(bool useGsm)
{
  appPrefs().begin("myPrefs", true);
  auto host = appPrefs().getString("MQTT_SERVER", String(MQTT_SERVER));
  if (host.equalsIgnoreCase("aitogy.asia"))
    host = MQTT_SERVER;
  const uint16_t port = appPrefs().getUShort("MQTT_PORT", MQTT_PORT);
  const auto user = appPrefs().getString("MQTT_USER", String(MQTT_USER));
  const auto password = appPrefs().getString("MQTT_PASS", String(MQTT_PASS));
  appPrefs().end();

  Client &transport = useGsm ? static_cast<Client &>(gsmProbeClient())
                             : static_cast<Client &>(wifiProbeClient());
  PubSubClient probe(transport);
  probe.setServer(host.c_str(), port);
  probe.setSocketTimeout(3);
  if (!probe.setBufferSize(1024))
    return false;
  // TinyGSM connect timeout is seconds; WiFiClient uses milliseconds.
  const auto tcpReady = useGsm ? gsmProbeClient().connect(host.c_str(), port, 5)
                               : wifiProbeClient().connect(host.c_str(), port, 3000);
  // No LWT, publish or subscribe: this probe cannot change station status.
  const auto clientId = "net-probe-" + backendAgent().serial();
  const auto reachable = tcpReady && probe.connect(clientId.c_str(), user.c_str(), password.c_str());
  if (reachable)
    probe.disconnect();
  transport.stop();
  return reachable;
}

/** @brief Implements setupMQTT. */
int setupMQTT()
{
  mqttClient().setClient(activeMqttClient());
  if (!mqttClient().setBufferSize(16384))
  {
    Serial.println("[MQTT][ERROR] Cannot allocate 16384-byte MQTT buffer");
    return -1;
  }
  appPrefs().begin("myPrefs", false);
  mqttServerHost() = appPrefs().getString("MQTT_SERVER", String(MQTT_SERVER));
  if (mqttServerHost().equalsIgnoreCase("aitogy.asia"))
  {
    // Replace the retired aitogy.asia broker value; retain other stored hosts.
    mqttServerHost() = MQTT_SERVER;
    appPrefs().putString("MQTT_SERVER", mqttServerHost());
  }
  uint16_t mqttServerPort = appPrefs().getUShort("MQTT_PORT", MQTT_PORT);
  appPrefs().end();
  mqttClient().setServer(mqttServerHost().c_str(), mqttServerPort);
  mqttClient().setCallback(mqttCallback);
  return 0;
}

/** @brief Implements connectMQTT. */
int connectMQTT()
{
  if (!mqttClient().connected())
  {
    if (lastMqttConnectAttemptMs() != 0 && millis() - lastMqttConnectAttemptMs() < 5000UL)
    {
      return -1;
    }
    lastMqttConnectAttemptMs() = millis();
    Serial.println("\n[MQTT] Dang ket noi Broker...");
    auto clientId = "agent-" + backendAgent().serial() + "-" + String(random(0xffff), HEX);
    appPrefs().begin("myPrefs", false);
    auto mqttUser = appPrefs().getString("MQTT_USER", String(MQTT_USER));
    auto mqttPass = appPrefs().getString("MQTT_PASS", String(MQTT_PASS));
    const auto topicSubCmd = appPrefs().getString("TPC_SUB_CMD", String(TOPIC_SUB_CMD));
    appPrefs().end();
    const auto statusTopic = String("pi/devices/") + backendAgent().serial() + "/status";
    const auto lwtPayload = backendAgent().lwtPayload();
    if (mqttClient().connect(clientId.c_str(), mqttUser.c_str(), mqttPass.c_str(),
                     statusTopic.c_str(), 1, true, lwtPayload.c_str()))
    {
      Serial.println("[MQTT] Da ket noi thanh cong!");
      const auto commandTopic = String("pi/devices/") + backendAgent().serial() + "/command";
      const auto commandsTopic = String("pi/devices/") + backendAgent().serial() + "/commands";
      const auto legacyCommandTopic = String("pi/device/") + backendAgent().serial() + "/command";
      const auto commandSubSent = mqttClient().subscribe(commandTopic.c_str(), 1);
      const auto commandsSubSent = mqttClient().subscribe(commandsTopic.c_str(), 1);
      const auto legacySubSent = mqttClient().subscribe(legacyCommandTopic.c_str(), 1);
      const auto oldSubSent = mqttClient().subscribe(topicSubCmd.c_str());
      mqttClient().subscribe((String("pi/devices/") + backendAgent().serial() + "/control_ack").c_str(), 1);
      Serial.printf("[MQTT] SUBSCRIBE command=%s, commands=%s, legacy=%s, old=%s\n",
                    commandSubSent ? "OK" : "LOI", commandsSubSent ? "OK" : "LOI",
                    legacySubSent ? "OK" : "LOI", oldSubSent ? "OK" : "LOI");
      backendAgent().onMqttConnected();
      return 0;
    }
    else
    {
      Serial.print("[MQTT] Loi rc=");
      Serial.print(mqttClient().state());
      Serial.println(" -> Thu lai sau 5s");
      backendAgent().onMqttDisconnected();
      return -1;
    }
  }
  return 0;
}

/** @brief Implements publishHealth. */
int publishHealth(const String &payload)
{
  if (payload.isEmpty())
    return -1;

  // Publish to the configured health topic under the shared transport mutex.

  if (tcpStreamMutex() != nullptr && xSemaphoreTake(tcpStreamMutex(), pdMS_TO_TICKS(MUTEX_TIMEOUT_MS)))
  {
    // TinyGsmClient::connected() can consume modem UART responses too.
    if (!mqttClient().connected())
    {
      xSemaphoreGive(tcpStreamMutex());
      return -1;
    }
    appPrefs().begin("myPrefs", false);
    auto topicPubHealth = appPrefs().getString("TPC_HEALTH", String(TOPIC_PUB_HEALTH));
    appPrefs().end();
    auto ok = mqttClient().publish(topicPubHealth.c_str(), payload.c_str());
    xSemaphoreGive(tcpStreamMutex());
    if (ok)
    {
#if PROGRAM_DEBUG
      Serial.print("[MQTT] Da gui thong tin suc khoe len topic: ");
      Serial.println(topicPubHealth);
#endif
      return 0;
    }
#if PROGRAM_DEBUG
    Serial.println("[MQTT] publishHealth that bai, kich thuoc payload: " + String(payload.length()));
#endif
    return -1;
  }
#if PROGRAM_DEBUG
  Serial.println("[MQTT] publishHealth: khong lay duoc tcpStreamMutex");
#endif
  return -1;
}

/** @brief Implements isMqttConnected. */
bool isMqttConnected()
{
  return mqttClient().connected();
}
