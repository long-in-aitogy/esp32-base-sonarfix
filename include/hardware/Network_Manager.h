#pragma once

namespace NetworkManager {
// Blocking boot connection; worker tasks have not started yet.
void connect();
// Performs transport recovery while acquiring the shared transport mutex.
void maintain();
// MQTT task calls these with tcpStreamMutex held.
void checkInternetFallback();
void logStatus();
}
