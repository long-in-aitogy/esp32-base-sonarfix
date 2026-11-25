#include "Prog_Config.h"
#include "hardware/Sim_handler.h"

#ifdef DUMP_AT_COMMANDS
#include <StreamDebugger.h>
#endif

TinyGsm &getModem()
{
#ifdef DUMP_AT_COMMANDS
    static StreamDebugger debugger(SerialAT, SerialMon);
    static TinyGsm modem(debugger);
#else
    static TinyGsm modem(SerialAT);
#endif
    return modem;
}

/** @brief Implements startSIM. */
bool startSIM()
{

    auto retrys = 1;

    digitalWrite(LED_PIN, HIGH);
    pinMode(MODEM_DC_PIN, OUTPUT);
    digitalWrite(MODEM_DC_PIN, HIGH);
    delay(1000);
    digitalWrite(MODEM_DC_PIN, LOW);
    SerialMon.println("[GSM] Doi modem SIM/GSM khoi dong (khoang 8 giay)...");
    delay(8000);
    digitalWrite(LED_PIN, LOW);

    SerialMon.println("[GSM] Khoi tao modem... So lan thu: " + String(retrys));

#ifndef NATIVE_BUILD
    getModem().init();
#endif

    auto modemInfo = getModem().getModemInfo();
    while (modemInfo.isEmpty())
    {
        if (retrys > 10)
        {
            SerialMon.println("[GSM] Lay thong tin modem that bai sau nhieu lan thu ! Khoi dong modem that bai !");
            return false;
        }
        SerialMon.println("[GSM] Lay thong tin modem that bai ! So lan thu: " + String(retrys));
        delay(1000);
#ifndef NATIVE_BUILD
        getModem().restart();
#endif
        modemInfo = getModem().getModemInfo();
        retrys++;
    }
    SerialMon.print("[GSM] Khoi dong modem thanh cong.Thong tin modem: ");
    SerialMon.println(modemInfo);
    digitalWrite(LED_PIN, LOW);

    delay(3000);
    return true;
}
/** @brief Implements connectGSM. */
bool connectGSM(uint8_t maxAttempts)
{
    uint8_t retries = 0;
    while (retries < maxAttempts)
    {
        retries++;
        auto simOperator = getModem().getProvider();
        SerialMon.println("[GSM] Nha mang GSM: " + simOperator);
        appPrefs().begin("myPrefs", true);
        String apn = appPrefs().getString("APN", String(APN));
        auto gprsUser = appPrefs().getString("GPRS_USER", String(GPRS_USER));
        auto gprsPass = appPrefs().getString("GPRS_PASS", String(GPRS_PASS));
        appPrefs().end();
        if (apn.isEmpty() || apn.equalsIgnoreCase("auto"))
        {
            if (simOperator.indexOf("VIETTEL") >= 0)
                apn = "v-internet";
            else if (simOperator.indexOf("MOBIFONE") >= 0)
                apn = "m-wap";
            else if (simOperator.indexOf("VINAPHONE") >= 0)
                apn = "m3-world";
            else
                apn = "v-internet";
        }

        SerialMon.println("[GSM] Dang ket noi mang GSM...");
        if (getModem().isNetworkConnected())
        {
            SerialMon.println("[GSM] Mang GSM da ket noi.");
            if (getModem().gprsConnect(apn.c_str(), gprsUser.c_str(), gprsPass.c_str()) && getModem().isGprsConnected())
            {
                SerialMon.println("[GSM] GPRS da ket noi.");
                return true;
            }
            else
            {
                SerialMon.println("[GSM] GPRS chua ket noi.");
            }
        }
        SerialMon.println("[GSM] Chua ket noi duoc mang GSM ngay lap tuc. Dang doi...");
        if (getModem().waitForNetwork(30000))
        {
            delay(1000);
            SerialMon.println("[GSM] Mang GSM da ket noi.");
            if (getModem().gprsConnect(apn.c_str(), gprsUser.c_str(), gprsPass.c_str()) && getModem().isGprsConnected())
            {
                SerialMon.println("[GSM] GPRS da ket noi.");
                return true;
            }
            else
            {
                SerialMon.println("[GSM] GPRS chua ket noi.");
            }
        }
        SerialMon.println("[GSM] Ket noi khong thanh cong, lan thu " + String(retries) + "...");
        delay(5000);
    }
    SerialMon.println("[GSM] Ket noi mang GSM that bai sau " + String(retries) + " lan thu. Ket thuc ket noi !");
    return false;
}
