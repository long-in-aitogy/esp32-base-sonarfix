#include "Prog_Config.h"
#include "hardware/Wifi_handler.h"
#include "hardware/Wifi_Credentials.h"
#include "functions/backend/Storage_Status.h"
#include <Preferences.h>
#include <ArduinoJson.h>
#include <nvs.h>
#include <functional>
#include <memory>

static bool connectWifi(const String &ssid, const String &password, const std::function<bool()> &validateConnection) {
    if (!validWifiSsid(ssid) || !validWifiPassword(password)) return false;
    WiFi.disconnect(false, false);
    WiFi.begin(ssid.c_str(), password.c_str());
    const uint32_t started = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - started < 6000UL) delay(100);
    if (WiFi.status() == WL_CONNECTED && (!validateConnection || validateConnection())) {
        Serial.println("[WIFI] Ket noi thanh cong! IP: " + WiFi.localIP().toString());
        return true;
    }
    WiFi.disconnect(false, false);
    return false;
}

static bool tryLegacyWifi(const std::function<bool()> &validateConnection) {
    // Upgrade only: select a working old profile before retiring the list.
    String profiles;
    nvs_handle_t legacy;
    if (nvs_open("wifi_config", NVS_READONLY, &legacy) == ESP_OK) {
        size_t length = 0;
        if (nvs_get_str(legacy, "profiles", nullptr, &length) == ESP_OK && length > 0 && length <= 3072) {
            auto value = std::make_unique<char[]>(length);
            if (nvs_get_str(legacy, "profiles", value.get(), &length) == ESP_OK) profiles = value.get();
        }
        nvs_close(legacy);
    }
    if (profiles.isEmpty()) return false;
    DynamicJsonDocument doc(3072);
    if (!deserializeJson(doc, profiles) == DeserializationError::Ok || !doc.is<JsonArray>()) return false;

    for (JsonObjectConst profile : doc.as<JsonArrayConst>()) {
        const String ssid = profile["ssid"] | "";
        const String password = profile["password"] | "";
        if (connectWifi(ssid, password, validateConnection)) {
            if (!saveMigratedWifi(ssid, password))
                Serial.println("[WIFI] Mang dang hoat dong; chua luu xong chuyen doi NVS.");
            return true;
        }
    }
    return false;
}

bool setupWiFi(const std::function<bool()> &validateConnection) {
    WiFi.persistent(false);
    WiFi.mode(WIFI_STA);
    if (tryLegacyWifi(validateConnection)) return true;
    Preferences store;
    if (!store.begin("myPrefs", true)) return false;
    const String ssid = store.getString("WIFI_SSID", WIFI_SSID);
    const String password = store.getString("WIFI_PASS", WIFI_PASSWORD);
    const bool savedCredentials = store.isKey("WIFI_SSID") && store.isKey("WIFI_PASS");
    store.end();
    const bool connected = connectWifi(ssid, password, validateConnection);
    if (connected && !savedCredentials && !saveMigratedWifi(ssid, password))
        Serial.println("[WIFI] Da ket noi; LOI luu cau hinh vao NVS.");
    if (!connected) Serial.println("[WIFI] Khong ket noi duoc mang da cau hinh.");
    return connected;
}
