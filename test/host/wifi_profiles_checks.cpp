#include "hardware/Wifi_Credentials.h"
#include <cassert>
#include <iostream>

int main() {
    assert(validWifiSsid("Hotspot điện thoại"));
    assert(validWifiSsid(String(32, 'a')));
    assert(!validWifiSsid(""));
    assert(!validWifiSsid(String(33, 'a')));
    assert(!validWifiSsid("bad\nssid"));
    assert(!validWifiSsid(String("abc\0def", 7)));
    assert(validWifiPassword("")); // Empty password supports an explicitly configured open network.
    assert(!validWifiPassword("1234567"));
    assert(validWifiPassword("12345678"));
    assert(validWifiPassword(String(63, 'a')));
    assert(!validWifiPassword(String(64, 'a')));
    assert(!validWifiPassword("12345678\n"));
    assert(!validWifiPassword(String("1234\0005678", 9)));
    std::cout << "PASS: Wi-Fi credential lengths, UTF-8 SSID, control/NUL rejection\n";
}
