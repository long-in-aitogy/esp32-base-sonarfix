#include "functions/backend/Backend_Agent_Websocket.h"
#include "functions/backend/Backend_Agent_Codec.h"
#include "functions/backend/Websocket_Protocol.h"
#include <mbedtls/sha1.h>
#include <mbedtls/base64.h>
#include "functions/backend/Backend_Agent.h"

#include <cstring>
#if !defined(NATIVE_BUILD)
#include <esp_random.h>
#endif

namespace {
String websocketNonce() {
    uint8_t nonce[16] = {};
    for (size_t i = 0; i < sizeof(nonce); i += sizeof(uint32_t)) {
#if !defined(NATIVE_BUILD)
        const uint32_t randomValue = esp_random();
#else
        const uint32_t randomValue = static_cast<uint32_t>(random(0x7FFFFFFF)) ^ micros();
#endif
        memcpy(nonce + i, &randomValue, sizeof(randomValue));
    }
    return BackendAgentInternal::encodeBase64(nonce, sizeof(nonce));
}
} // namespace

BackendAgentWebsocket::BackendAgentWebsocket(BackendAgent *owner) : owner_(owner) {}

void BackendAgentWebsocket::begin(const String &host, uint16_t port, const String &path, Client &client) {
    host_ = host;
    port_ = port;
    path_ = path;
    client_ = &client;
    nextAttemptMs_ = 0;
}

void BackendAgentWebsocket::loop() {
    if (!client_) {
        return;
    }
    if (!connected_) {
        if (static_cast<int32_t>(millis() - nextAttemptMs_) < 0) {
            return;
        }
        connectNow();
        return;
    }

    if (!client_->connected()) {
        disconnect(false);
        return;
    }

    if (millis() - lastPingMs_ >= 30000UL) {
        static constexpr uint8_t ping[] = {'p', 'i'};
        sendControl(0x9, ping, sizeof(ping));
        lastPingMs_ = millis();
    }

    uint8_t chunk[256];
    while (client_->available() > 0) {
        const int count = client_->read(chunk, sizeof(chunk));
        if (count <= 0) {
            break;
        }
        if (rx_.size() + static_cast<size_t>(count) > 32768) {
            disconnect(false);
            return;
        }
        rx_.insert(rx_.end(), chunk, chunk + count);
    }
    parseFrames();
}

bool BackendAgentWebsocket::connected() const { return connected_; }

void BackendAgentWebsocket::disconnect(bool permanent) {
    if (client_) {
        client_->stop();
    }
    std::vector<uint8_t>().swap(rx_);
    connected_ = false;
    nextAttemptMs_ = millis() + (permanent ? 60000UL : 10000UL);
    if (owner_) {
        owner_->websocketConnected_ = false;
    }
}

bool BackendAgentWebsocket::sendText(const String &text) {
    if (!connected_ || !client_ || !client_->connected()) {
        return false;
    }

    const size_t length = text.length();
    uint8_t header[10] = {};
    size_t headerLength = 2;
    header[0] = 0x81; // FIN + text frame
    if (length < 126) {
        header[1] = static_cast<uint8_t>(0x80 | length);
    } else if (length <= 0xFFFF) {
        header[1] = 0x80 | 126;
        header[2] = static_cast<uint8_t>((length >> 8) & 0xFF);
        header[3] = static_cast<uint8_t>(length & 0xFF);
        headerLength = 4;
    } else {
        header[1] = 0x80 | 127;
        for (uint8_t i = 0; i < 8; ++i) {
            header[2 + i] = static_cast<uint8_t>((static_cast<uint64_t>(length) >> (56 - (i * 8))) & 0xFF);
        }
        headerLength = 10;
    }

#if !defined(NATIVE_BUILD)
    const uint32_t mask = esp_random();
#else
    const uint32_t mask = static_cast<uint32_t>(random(0x7FFFFFFF)) ^ micros();
#endif
    const uint8_t maskBytes[4] = {
        static_cast<uint8_t>((mask >> 24) & 0xFF),
        static_cast<uint8_t>((mask >> 16) & 0xFF),
        static_cast<uint8_t>((mask >> 8) & 0xFF),
        static_cast<uint8_t>(mask & 0xFF),
    };

    if (client_->write(header, headerLength) != headerLength
        || client_->write(maskBytes, sizeof(maskBytes)) != sizeof(maskBytes)) {
        disconnect(false);
        return false;
    }

    uint8_t maskedChunk[256] = {};
    for (size_t offset = 0; offset < length; offset += sizeof(maskedChunk)) {
        const size_t chunkLength = min(sizeof(maskedChunk), length - offset);
        for (size_t i = 0; i < chunkLength; ++i) {
            maskedChunk[i] = static_cast<uint8_t>(text[offset + i])
                ^ maskBytes[(offset + i) & 3];
        }
        if (client_->write(maskedChunk, chunkLength) != chunkLength) {
            disconnect(false);
            return false;
        }
    }
    return true;
}

void BackendAgentWebsocket::connectNow() {
    nextAttemptMs_ = millis() + 10000UL;
    client_->stop();
    client_->setTimeout(3000);
    if (!client_->connect(host_.c_str(), port_)) {
        return;
    }

    // RFC6455 requires this header to decode to exactly 16 random bytes.
    const String key = websocketNonce();
    client_->print(String("GET ") + path_ + " HTTP/1.1\r\n"
                   + "Host: " + host_ + ":" + String(port_) + "\r\n"
                   + "Upgrade: websocket\r\n"
                   + "Connection: Upgrade\r\n"
                   + "Sec-WebSocket-Key: " + key + "\r\n"
                   + "Sec-WebSocket-Version: 13\r\n\r\n");

    String response;
    const uint32_t started = millis();
    while (millis() - started < 5000UL && response.length() < 4096) {
        while (client_->available() > 0 && response.length() < 4096) {
            const int byte = client_->read();
            if (byte < 0) break;
            response += static_cast<char>(byte);
            if (response.endsWith("\r\n\r\n")) {
                break;
            }
        }
        if (response.endsWith("\r\n\r\n")) {
            break;
        }
        delay(1);
    }

    const String challenge = key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
    unsigned char digest[20], encoded[32];
    size_t encodedLength = 0;
    const bool valid = mbedtls_sha1_ret(reinterpret_cast<const unsigned char *>(challenge.c_str()),
                                      challenge.length(), digest) == 0
        && mbedtls_base64_encode(encoded, sizeof(encoded), &encodedLength, digest, sizeof(digest)) == 0
        && WebsocketProtocol::validUpgrade(std::string(response.c_str(), response.length()),
                                          std::string(reinterpret_cast<char *>(encoded), encodedLength));
    if (!valid) {
        client_->stop();
        return;
    }
    connected_ = true;
    nextAttemptMs_ = millis() + 10000UL;
    lastPingMs_ = millis();
    if (owner_) {
        owner_->websocketConnected_ = true;
        Serial.println("[BACKEND][WS] WebSocket da ket noi.");
        owner_->publishStatus(true);
    }
}

bool BackendAgentWebsocket::readFrame(uint8_t &opcode, String &payload) {
    const uint8_t first = rx_[0];
    const uint8_t second = rx_[1];
    const bool masked = (second & 0x80) != 0;
    uint64_t payloadLength = second & 0x7F;
    size_t headerLength = 2;

    if (payloadLength == 126) {
        if (rx_.size() < 4) return false;
        payloadLength = (static_cast<uint64_t>(rx_[2]) << 8) | rx_[3];
        headerLength = 4;
    } else if (payloadLength == 127) {
        if (rx_.size() < 10) return false;
        payloadLength = 0;
        for (uint8_t i = 0; i < 8; ++i) {
            payloadLength = (payloadLength << 8) | rx_[2 + i];
        }
        headerLength = 10;
    }

    opcode = first & 0x0F;
    // Reject unsupported fragmentation instead of dispatching partial commands.
    // Server frames must be unmasked and carry no unnegotiated RSV flags.
    if (masked || (first & 0x70) || !(first & 0x80)
        || (opcode != 1 && opcode != 2 && opcode != 8 && opcode != 9 && opcode != 10)
        || (opcode >= 8 && (payloadLength > 125 || (opcode == 8 && payloadLength == 1)))
        || ((second & 0x7F) == 126 && payloadLength < 126)
        || ((second & 0x7F) == 127 && payloadLength < 65536)) {
        disconnect(false);
        return false;
    }
    if (payloadLength > 32768) {
        disconnect(false);
        return false;
    }
    if (rx_.size() < headerLength + payloadLength) return false;

    payload.reserve(static_cast<size_t>(payloadLength));
    const size_t payloadOffset = headerLength;
    for (size_t i = 0; i < payloadLength; ++i) {
        uint8_t byte = rx_[payloadOffset + i];
        payload += static_cast<char>(byte);
    }
    rx_.erase(rx_.begin(), rx_.begin() + payloadOffset + payloadLength);

    return true;
}

void BackendAgentWebsocket::parseFrames() {
    while (rx_.size() >= 2 && connected_) {
        uint8_t opcode = 0;
        String payload;
        if (!readFrame(opcode, payload)) return;

        if (opcode == 0x8) {
            sendControl(0x8, nullptr, 0);
            disconnect(false);
            return;
        }
        if (opcode == 0x9) {
            sendControl(0xA, reinterpret_cast<const uint8_t *>(payload.c_str()), payload.length());
        } else if (opcode == 0x1 && owner_) {
            owner_->handleWebsocketText(payload);
        }
    }
    if (rx_.empty() && rx_.capacity() > 4096) std::vector<uint8_t>().swap(rx_);
}

void BackendAgentWebsocket::sendControl(uint8_t opcode, const uint8_t *payload, size_t length) {
    if (!connected_ || !client_ || length > 125) return;
#if !defined(NATIVE_BUILD)
    const uint32_t mask = esp_random();
#else
    const uint32_t mask = static_cast<uint32_t>(random(0x7FFFFFFF)) ^ micros();
#endif
    const uint8_t maskBytes[4] = {
        static_cast<uint8_t>((mask >> 24) & 0xFF),
        static_cast<uint8_t>((mask >> 16) & 0xFF),
        static_cast<uint8_t>((mask >> 8) & 0xFF),
        static_cast<uint8_t>(mask & 0xFF),
    };
    const uint8_t header[2] = {
        static_cast<uint8_t>(0x80 | opcode),
        static_cast<uint8_t>(0x80 | length),
    };
    client_->write(header, sizeof(header));
    client_->write(maskBytes, sizeof(maskBytes));
    if (payload && length > 0) {
        for (size_t i = 0; i < length; ++i) {
            const uint8_t byte = payload[i] ^ maskBytes[i & 3];
            client_->write(&byte, 1);
        }
    }
}
