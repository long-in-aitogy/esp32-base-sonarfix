#include "hardware/Connection_type.h"
#include "Prog_Config.h"

ConnectionType &activeConnectionType()
{
    static ConnectionType type = ConnectionType::GSM;
    return type;
}

/** @brief Implements loadConnectionTypeFromPrefs. */
void loadConnectionTypeFromPrefs()
{
    const auto configuredType = appPrefs().getString("CONNECTION_TYPE", CONNECTION_PREFERENCE);

    if (configuredType.equalsIgnoreCase("WIFI"))
    {
        activeConnectionType() = ConnectionType::WIFI;
        return;
    }

    if (!configuredType.equalsIgnoreCase("4G"))
    {
        Serial.println("[SETUP][WARN] CONNECTION_TYPE khong hop le: " + configuredType + ". Su dung 4G.");
    }
    activeConnectionType() = ConnectionType::GSM;
}
