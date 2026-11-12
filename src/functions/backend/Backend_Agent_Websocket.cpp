#include "functions/backend/Backend_Agent_Websocket.h"
#include "functions/backend/Backend_Agent.h"
#include "functions/backend/Backend_Agent_Codec.h"
#include "functions/backend/Websocket_Protocol.h"

#include <mbedtls/sha1.h>
#include <mbedtls/base64.h>

#include <array>
#include <cstddef>
#include <cstring>
#if !defined(NATIVE_BUILD)
#include <esp_random.h>
#endif

namespace
{
    uint8_t maskByte(uint8_t value, uint8_t mask)
    {
        return std::to_integer<uint8_t>(std::byte{value} ^ std::byte{mask});
    }

    String websocketNonce()
    {
        std::array<uint8_t, 16> nonce = {};
        for (size_t i = 0; i < nonce.size(); i += sizeof(uint32_t))
        {
#if !defined(NATIVE_BUILD)
            const uint32_t randomValue = esp_random();
#else
            const uint32_t randomValue = static_cast<uint32_t>(random(0x7FFFFFFF)) ^ micros();
#endif
            memcpy(nonce.data() + i, &randomValue, sizeof(randomValue));
        }
        return BackendAgentInternal::encodeBase64(nonce.data(), nonce.size());
    }
} // namespace

BackendAgentWebsocket::BackendAgentWebsocket(BackendAgent *owner) : owner_(owner) {}

void BackendAgentWebsocket::begin(const String &host, uint16_t port, const String &path, Client &client)
{
    host_ = host;
    port_ = port;
    path_ = path;
    client_ = &client;
    nextAttemptMs_ = 0;
}

void BackendAgentWebsocket::loop()
{
    if (!client_)
    {
        return;
    }
    if (!connected_)
    {
        if (static_cast<int32_t>(millis() - nextAttemptMs_) < 0)
        {
            return;
        }
        connectNow();
        return;
    }

    if (!client_->connected())
    {
        disconnect(false);
        return;
    }

    if (millis() - lastPingMs_ >= 30000UL)
    {
        static constexpr std::array<uint8_t, 2> ping = {'p', 'i'};
        sendControl(0x9, ping.data(), ping.size());
        lastPingMs_ = millis();
    }

    std::array<uint8_t, 256> chunk;
    while (client_->available() > 0)
    {
        const auto count = client_->read(chunk.data(), chunk.size());
        if (count <= 0)
        {
            break;
        }
        if (rx_.size() + static_cast<size_t>(count) > 32768)
        {
            disconnect(false);
            return;
        }
        rx_.insert(rx_.end(), chunk.begin(), chunk.begin() + count);
    }
    parseFrames();
}

bool BackendAgentWebsocket::connected() const { return connected_; }

void BackendAgentWebsocket::disconnect(bool permanent)
{
    if (client_)
    {
        client_->stop();
    }
    std::vector<uint8_t>().swap(rx_);
    connected_ = false;
    nextAttemptMs_ = millis() + (permanent ? 60000UL : 10000UL);
    if (owner_)
    {
        owner_->websocketConnected_ = false;
    }
}

bool BackendAgentWebsocket::sendText(const String &text)
{
    if (!connected_ || !client_ || !client_->connected())
    {
        return false;
    }

    const size_t length = text.length();
    std::array<uint8_t, 10> header = {};
    auto headerLength = 2;
    header[0] = 0x81; // FIN + text frame
    if (length < 126)
    {
        header[1] = static_cast<uint8_t>(0x80 | length);
    }
    else if (length <= 0xFFFF)
    {
        header[1] = 0x80 | 126;
        header[2] = static_cast<uint8_t>((length >> 8) & 0xFF);
        header[3] = static_cast<uint8_t>(length & 0xFF);
        headerLength = 4;
    }
    else
    {
        header[1] = 0x80 | 127;
        for (uint8_t i = 0; i < 8; ++i)
        {
            header[2 + i] = static_cast<uint8_t>((static_cast<uint64_t>(length) >> (56 - (i * 8))) & 0xFF);
        }
        headerLength = 10;
    }

#if !defined(NATIVE_BUILD)
    const uint32_t mask = esp_random();
#else
    const uint32_t mask = static_cast<uint32_t>(random(0x7FFFFFFF)) ^ micros();
#endif
    const std::array<uint8_t, 4> maskBytes = {
        static_cast<uint8_t>((mask >> 24) & 0xFF),
        static_cast<uint8_t>((mask >> 16) & 0xFF),
        static_cast<uint8_t>((mask >> 8) & 0xFF),
        static_cast<uint8_t>(mask & 0xFF),
    };

    if (client_->write(header.data(), headerLength) != headerLength || client_->write(maskBytes.data(), maskBytes.size()) != maskBytes.size())
    {
        disconnect(false);
        return false;
    }

    std::array<uint8_t, 256> maskedChunk = {};
    for (size_t offset = 0; offset < length; offset += maskedChunk.size())
    {
        const auto chunkLength = min(maskedChunk.size(), length - offset);
        for (size_t i = 0; i < chunkLength; ++i)
        {
            maskedChunk[i] = maskByte(static_cast<uint8_t>(text[offset + i]), maskBytes[(offset + i) % maskBytes.size()]);
        }
        if (client_->write(maskedChunk.data(), chunkLength) != chunkLength)
        {
            disconnect(false);
            return false;
        }
    }
    return true;
}

void BackendAgentWebsocket::connectNow()
{
    nextAttemptMs_ = millis() + 10000UL;
    client_->stop();
    client_->setTimeout(3000);
    if (!client_->connect(host_.c_str(), port_))
    {
        return;
    }

    // RFC6455 requires this header to decode to exactly 16 random bytes.
    const auto key = websocketNonce();
    client_->print(String("GET ") + path_ + " HTTP/1.1\r\n" + "Host: " + host_ + ":" + String(port_) + "\r\n" + "Upgrade: websocket\r\n" + "Connection: Upgrade\r\n" + "Sec-WebSocket-Key: " + key + "\r\n" + "Sec-WebSocket-Version: 13\r\n\r\n");

    String response;
    const uint32_t started = millis();
    while (millis() - started < 5000UL && response.length() < 4096)
    {
        while (client_->available() > 0 && response.length() < 4096
               && !response.endsWith("\r\n\r\n"))
        {
            const int byte = client_->read();
            if (byte < 0)
                break;
            response += static_cast<char>(byte);
        }
        if (response.endsWith("\r\n\r\n"))
        {
            break;
        }
        delay(1);
    }

    const String challenge = key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
    std::array<unsigned char, 20> digest{};
    std::array<unsigned char, 32> encoded{};
    size_t encodedLength = 0;
    const bool valid = mbedtls_sha1_ret(reinterpret_cast<const unsigned char *>(challenge.c_str()),
                                        challenge.length(), digest.data()) == 0
        && mbedtls_base64_encode(encoded.data(), encoded.size(), &encodedLength, digest.data(), digest.size()) == 0
        && WebsocketProtocol::validUpgrade(std::string(response.c_str(), response.length()),
                                           std::string(reinterpret_cast<const char *>(encoded.data()), encodedLength));
    if (!valid)
    {
        client_->stop();
        return;
    }
    connected_ = true;
    nextAttemptMs_ = millis() + 10000UL;
    lastPingMs_ = millis();
    if (owner_)
    {
        owner_->websocketConnected_ = true;
        Serial.println("[BACKEND][WS] WebSocket da ket noi.");
        owner_->publishStatus(true);
    }
}

bool BackendAgentWebsocket::readFrame(uint8_t &opcode, String &payload)
{
    const std::byte first{rx_[0]};
    const std::byte second{rx_[1]};
    const bool masked = (second & std::byte{0x80}) != std::byte{};
    uint64_t payloadLength = std::to_integer<uint8_t>(second & std::byte{0x7F});
    const uint8_t lengthCode = static_cast<uint8_t>(payloadLength);
    size_t headerLength = 2;

    if (payloadLength == 126)
    {
        if (rx_.size() < 4)
            return false;
        payloadLength = (static_cast<uint64_t>(rx_[2]) << 8) | rx_[3];
        headerLength = 4;
    }
    else if (payloadLength == 127)
    {
        if (rx_.size() < 10)
            return false;
        payloadLength = 0;
        for (uint8_t i = 0; i < 8; ++i)
            payloadLength = (payloadLength << 8) | rx_[2 + i];
        headerLength = 10;
    }

    opcode = std::to_integer<uint8_t>(first & std::byte{0x0F});
    // No extensions or fragmentation were negotiated; server frames are unmasked.
    if (masked || (first & std::byte{0x70}) != std::byte{} || (first & std::byte{0x80}) == std::byte{}
        || (opcode != 1 && opcode != 2 && opcode != 8 && opcode != 9 && opcode != 10)
        || (opcode >= 8 && (payloadLength > 125 || (opcode == 8 && payloadLength == 1)))
        || (lengthCode == 126 && payloadLength < 126)
        || (lengthCode == 127 && payloadLength < 65536)
        || payloadLength > 32768)
    {
        disconnect(false);
        return false;
    }
    if (rx_.size() < headerLength + payloadLength)
        return false;

    payload.reserve(static_cast<size_t>(payloadLength));
    for (size_t i = 0; i < payloadLength; ++i)
        payload += static_cast<char>(rx_[headerLength + i]);
    rx_.erase(rx_.begin(), rx_.begin() + headerLength + payloadLength);
    return true;
}

void BackendAgentWebsocket::parseFrames()
{
    while (rx_.size() >= 2 && connected_)
    {
        uint8_t opcode = 0;
        String payload;
        if (!readFrame(opcode, payload))
            return;
        if (opcode == 0x8)
        {
            sendControl(0x8, nullptr, 0);
            disconnect(false);
            return;
        }
        if (opcode == 0x9)
        {
            sendControl(0xA, reinterpret_cast<const uint8_t *>(payload.c_str()), payload.length());
        }
        else if (opcode == 0x1 && owner_)
        {
            owner_->handleWebsocketText(payload);
        }
    }
    if (rx_.empty() && rx_.capacity() > 4096)
        std::vector<uint8_t>().swap(rx_);
}

void BackendAgentWebsocket::sendControl(uint8_t opcode, const uint8_t *payload, size_t length)
{
    if (!connected_ || !client_ || length > 125 || (length && !payload))
        return;
#if !defined(NATIVE_BUILD)
    const uint32_t mask = esp_random();
#else
    const uint32_t mask = static_cast<uint32_t>(random(0x7FFFFFFF)) ^ micros();
#endif
    const std::array<uint8_t, 4> maskBytes = {
        static_cast<uint8_t>((mask >> 24) & 0xFF),
        static_cast<uint8_t>((mask >> 16) & 0xFF),
        static_cast<uint8_t>((mask >> 8) & 0xFF),
        static_cast<uint8_t>(mask & 0xFF),
    };
    const std::array<uint8_t, 2> header = {
        static_cast<uint8_t>(0x80 | opcode),
        static_cast<uint8_t>(0x80 | length),
    };
    if (client_->write(header.data(), header.size()) != header.size() ||
        client_->write(maskBytes.data(), maskBytes.size()) != maskBytes.size())
    {
        disconnect(false);
        return;
    }
    if (payload && length > 0)
    {
        for (size_t i = 0; i < length; ++i)
        {
            const uint8_t byte = maskByte(payload[i], maskBytes[i % maskBytes.size()]);
            if (client_->write(&byte, 1) != 1)
            {
                disconnect(false);
                return;
            }
        }
    }
}
