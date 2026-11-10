#ifndef PROG_CONFIG_H
#define PROG_CONFIG_H

#include <cstdint>
#include <string_view>
#include "Top_Lvl_Config.h"
#include <Preferences.h>

extern Preferences prefs;
extern SemaphoreHandle_t gnssSerialMutex;

// ================= CẤU HÌNH CHÂN CẮM VÀ TỐC ĐỘ SERIAL =================
#if BOARD_2A53N
inline constexpr int RX_GNSS = 22; // ESP32 RX nối TX của receiver GNSS.
inline constexpr int TX_GNSS = 23; // ESP32 TX nối RX của receiver GNSS.
inline constexpr int LED_PIN = 2;
#elif BOARD_TDM_240X
inline constexpr int RX_GNSS = 18; // ESP32 RX nối TX của receiver GNSS.
inline constexpr int TX_GNSS = 19; // ESP32 TX nối RX của receiver GNSS.
inline constexpr int LED_PIN = 2;
#endif
inline constexpr int GNSS_BAUD = 115200;
// 0: output on the receiver port carrying this command; 1..3: force COM1..3.
inline constexpr uint8_t GNSS_UNICORE_PORT = 0;

// ================= CẤU HÌNH CÁC TASK =================
inline constexpr int MUTEX_TIMEOUT_MS = 1500; // Thời gian tối đa để chờ mutex (ms)

// ================= CẤU HÌNH KẾT NỐI =================
// Giá trị mặc định khi chưa có cấu hình NVS hoặc sau lệnh reset phần tương ứng.
// Sửa header/nạp firmware/reboot không ghi đè cấu hình đã lưu.
// Muốn dùng lại mặc định mới: gửi lệnh xóa/reset cấu hình NVS tương ứng.
// Tài khoản rover chung để ESP32 lấy cải chính trong luồng Auto Base.
inline constexpr char AUTO_BASE_CASTER_HOST[] = "aitogy.click";
inline constexpr uint16_t AUTO_BASE_CASTER_PORT = 2101;
inline constexpr char AUTO_BASE_CASTER_USER[] = "aitogy";
inline constexpr char AUTO_BASE_CASTER_PASSWORD[] = "aitogy";
inline constexpr char AUTO_BASE_CASTER_MOUNTPOINT[] = "test";

inline constexpr char CONNECTION_PREFERENCE[] = "4G"; // "4G" hoặc "WIFI".
static_assert(std::string_view(CONNECTION_PREFERENCE) == "4G" || std::string_view(CONNECTION_PREFERENCE) == "WIFI",
              "CONNECTION_PREFERENCE must be 4G or WIFI");

inline constexpr char WIFI_SSID[] = "";
inline constexpr char WIFI_PASSWORD[] = "";


inline constexpr uint8_t TX_TO_MODEM_RX = 17;
inline constexpr uint8_t RX_TO_MODEM_TX = 16;
inline constexpr uint8_t MODEM_DC_PIN = 15;
inline constexpr uint8_t MODEM_DTR_PIN = 4;

inline constexpr char APN[] = "v-internet"; // APN cụ thể; "auto" để chọn theo nhà mạng
inline constexpr char GPRS_USER[] = "";     // Thường để trống
inline constexpr char GPRS_PASS[] = "";

// ================= CẤU HÌNH NTRIP =================
// Mã trạng thái nền của luồng gửi NTRIP; cộng 4 khi gửi được RTCM.
inline constexpr int NTRIP_MODE = 1;
inline constexpr char NTRIP_CASTER_ADDRESS[] = "aitogy.com.vn";
inline constexpr uint16_t NTRIP_CASTER_PORT = 2101;
inline constexpr char NTRIP_MOUNTPOINT[] = "test_esp";
inline constexpr char NTRIP_AUTH_BASE_STATION[] = "12345";

// ================ CẤU HÌNH MQTT =================

inline constexpr char MQTT_SERVER[] = "aitogy.click";
inline constexpr uint16_t MQTT_PORT = 1883;
inline constexpr char MQTT_USER[] = "mqttUser";
inline constexpr char MQTT_PASS[] = "MqttPassword123$%^";

// Firmware version and backend connection/status defaults.
// Backend host and port can be overridden in Preferences.
inline constexpr char AGENT_VERSION[] = "V2.4.2";
inline constexpr char BACKEND_HOST[] = "base.aitogy.com";
inline constexpr uint16_t BACKEND_WEBSOCKET_PORT = 8000;
inline constexpr uint32_t BACKEND_STATUS_INTERVAL_MS = 5000;
inline constexpr uint32_t BACKEND_CONTROL_STALE_MS = 45000;
inline constexpr uint32_t BACKEND_CONTROL_RECOVERY_MS = 5000;

inline constexpr char TOPIC_SUB_CMD[] = "tdm2402/um980_base_001/cmd";
inline constexpr char TOPIC_PUB_HEALTH[] = "tdm2402/um980_base_001/health";

// ================= CẤU HÌNH KIỂM TRA SỨC KHOẺ =================
const unsigned long HEALTH_INTERVAL = 30000; // chu kỳ gửi thông tin sức khoẻ (ms)

#endif // PROG_CONFIG_H
