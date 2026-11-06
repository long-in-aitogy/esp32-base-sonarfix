#pragma once
#define HOST_READBACK_TEST
#include "../Arduino.h"
#include <deque>
#include <vector>
#include <cstring>

// Virtual UART and clock: compile the complete receiver readback implementations.
inline uint32_t hostMillis = 0;
inline uint32_t millis() { return hostMillis; }
using SemaphoreHandle_t = void *;
inline SemaphoreHandle_t rtcmBufferMutex = reinterpret_cast<void *>(1);
inline SemaphoreHandle_t gnssSerialMutex = reinterpret_cast<void *>(2);
inline SemaphoreHandle_t deniedLock = nullptr;
inline unsigned acquiredLocks = 0, releasedLocks = 0;
inline constexpr unsigned pdTRUE = 1;
inline unsigned pdMS_TO_TICKS(unsigned value) { return value; }
inline unsigned xSemaphoreTake(SemaphoreHandle_t lock, unsigned) {
    if (lock == deniedLock) return 0;
    ++acquiredLocks; return pdTRUE;
}
inline void xSemaphoreGive(SemaphoreHandle_t) { ++releasedLocks; }
inline void vTaskDelay(unsigned value) { hostMillis += value; }
inline std::vector<uint8_t> bufferedQueryBytes;
inline void bufferGnssQueryByte(uint8_t value) { bufferedQueryBytes.push_back(value); }
struct ReadbackSerial {
    std::deque<uint8_t> input;
    std::deque<std::vector<uint8_t>> replies;
    std::vector<std::vector<uint8_t>> writes;
    bool shortWrite = false;
    unsigned baudRate() const { return 115200; }
    int available() const { return static_cast<int>(input.size()); }
    int read() { const auto value = input.front(); input.pop_front(); return value; }
    size_t write(const uint8_t *data, size_t length) {
        writes.emplace_back(data, data + length);
        if (length > 2 && !replies.empty()) {
            input.insert(input.end(), replies.front().begin(), replies.front().end());
            replies.pop_front();
        }
        return shortWrite ? length - 1 : length;
    }
    void flush() {}
};
inline ReadbackSerial Serial1;
