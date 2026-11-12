#include "functions/gnss/gnss_cmd_builder.h"
#include "functions/gnss/ublox_commands.h"
#include "Prog_Config.h"
#include <array>
#include <algorithm>
#include <cstddef>
#include <cstring>

namespace UbloxCommands
{
    using GnssCmdBuilder::Command;
    using GnssCmdBuilder::CommandList;
    using GnssCmdBuilder::GnssOptions;
    using GnssCmdBuilder::MsmLevel;
    using GnssCmdBuilder::OutputMode;

    constexpr std::array<uint8_t, 21> UBLOX_SAVE_CONFIG = {
        0xB5, 0x62, 0x06, 0x09, 0x0D, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFF,
        0xFF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x03, 0x1D, 0xAB};

    struct PortKeys
    {
        uint32_t uart1;
        uint32_t uart2;
        uint32_t usb;
        uint32_t i2c = 0;
        uint32_t spi = 0;
    };
    struct MessageKeys
    {
        const char *name;
        PortKeys keys;
    };

    constexpr std::array<MessageKeys, 16> NMEA_KEYS = {
        {
            {"GGA", {0x209100BB, 0x209100BC, 0x209100BD}},
            {"GSA", {0x209100C0, 0x209100C1, 0x209100C2}},
            {"GSV", {0x209100C5, 0x209100C6, 0x209100C7}},
            {"GST", {0x209100D4, 0x209100D5, 0x209100D6}},
            {"DTM", {0x209100A7, 0x209100A8, 0x209100A9}},
            {"RMC", {0x209100AC, 0x209100AD, 0x209100AE}},
            {"GNS", {0x209100B6, 0x209100B7, 0x209100B8}},
            {"VTG", {0x209100B1, 0x209100B2, 0x209100B3}},
            {"GLL", {0x209100CA, 0x209100CB, 0x209100CC}},
            {"GRS", {0x209100CF, 0x209100D0, 0x209100D1}},
            {"ZDA", {0x209100D9, 0x209100DA, 0x209100DB}},
            {"GBS", {0x209100DE, 0x209100DF, 0x209100E0}},
            {"VLW", {0x209100E8, 0x209100E9, 0x209100EA}},
            {"PUBX00", {0x209100ED, 0x209100EE, 0x209100EF}},
            {"PUBX03", {0x209100F2, 0x209100F3, 0x209100F4}},
            {"PUBX04", {0x209100F7, 0x209100F8, 0x209100F9}},
        }};

    constexpr std::array<PortKeys, 2> NAV_KEYS = {
        {{0x20910007, 0x20910008, 0x20910009}, {0x20910034, 0x20910035, 0x20910036}}};

    constexpr std::array<MessageKeys, 10> RTCM_KEYS = {
        {
            {"1005", {0x209102BE, 0x209102BF, 0x209102C0, 0x209102BD, 0x209102C1}},
            {"1074", {0x2091035F, 0x20910360, 0x20910361, 0x2091035E, 0x20910362}},
            {"1084", {0x20910364, 0x20910365, 0x20910366, 0x20910363, 0x20910367}},
            {"1094", {0x20910369, 0x2091036A, 0x2091036B, 0x20910368, 0x2091036C}},
            {"1124", {0x2091036E, 0x2091036F, 0x20910370, 0x2091036D, 0x20910371}},
            {"1077", {0x209102CD, 0x209102CE, 0x209102CF, 0x209102CC, 0x209102D0}},
            {"1087", {0x209102D2, 0x209102D3, 0x209102D4, 0x209102D1, 0x209102D5}},
            {"1097", {0x20910319, 0x2091031A, 0x2091031B, 0x20910318, 0x2091031C}},
            {"1127", {0x209102D7, 0x209102D8, 0x209102D9, 0x209102D6, 0x209102DA}},
            {"1230", {0x20910304, 0x20910305, 0x20910306, 0x20910303, 0x20910307}},
        }};

/** @brief Implements isValidRtcmPort. */
    inline bool isValidRtcmPort(const String &port)
    {
        return port == "I2C" || port == "UART1" || port == "UART2" ||
               port == "USB" || port == "SPI";
    }

/** @brief Implements keyForPort. */
    uint32_t keyForPort(const PortKeys &keys, const String &port)
    {
        if (port == "UART1")
            return keys.uart1;
        else if (port == "UART2")
            return keys.uart2;
        else if (port == "USB")
            return keys.usb;
        else if (port == "I2C")
            return keys.i2c;
        else if (port == "SPI")
            return keys.spi;
        return 0;
    }

/** @brief Implements appendU32. */
    inline void appendU32(Command &data, uint32_t value)
    {
        for (uint8_t i = 0; i < 4; ++i)
            data.push_back(static_cast<uint8_t>(value >> (8 * i)));
    }

/** @brief Implements writeU32. */
    inline void writeU32(Command &data, size_t index, uint32_t value)
    {
        for (uint8_t i = 0; i < 4; ++i)
            data[index + i] = static_cast<uint8_t>(value >> (8 * i));
    }

/** @brief Implements ubxPacket. */
    Command ubxPacket(uint8_t messageClass, uint8_t messageId, const Command &payload)
    {
        Command result = {0xB5, 0x62, messageClass, messageId,
                          static_cast<uint8_t>(payload.size()), static_cast<uint8_t>(payload.size() >> 8)};
        result.insert(result.end(), payload.begin(), payload.end());
        uint8_t ckA = 0;
        uint8_t ckB = 0;
        for (size_t i = 2; i < result.size(); ++i)
        {
            ckA += result[i];
            ckB += ckA;
        }
        result.push_back(ckA);
        result.push_back(ckB);
        return result;
    }

/** @brief Implements ubxCfgValsetU1. */
    Command ubxCfgValsetU1(const std::vector<std::pair<uint32_t, bool>> &entries)
    {
        Command payload = {0x00, 0x07, 0x00, 0x00};
        for (const auto &[key, value] : entries)
        {
            appendU32(payload, key);
            payload.push_back(value ? 1 : 0);
        }
        return ubxPacket(0x06, 0x8A, payload);
    }

/** @brief Implements ubxCfgMsg. */
    Command ubxCfgMsg(uint8_t messageClass, uint8_t messageId, const std::vector<String> &ports, uint8_t rate)
    {
        Command payload = {messageClass, messageId, 0, 0, 0, 0, 0, 0};
        for (const String &port : ports)
        {
            if (port == "I2C")
                payload[2] = rate;
            else if (port == "UART1")
                payload[3] = rate;
            else if (port == "UART2")
                payload[4] = rate;
            else if (port == "USB")
                payload[5] = rate;
            else if (port == "SPI")
                payload[6] = rate;
        }
        return ubxPacket(0x06, 0x01, payload);
    }

/** @brief Implements isDiagnosticNmea. */
    inline bool isDiagnosticNmea(const char *name)
    {
        return !strcmp(name, "GGA") || !strcmp(name, "GSA") || !strcmp(name, "GSV") || !strcmp(name, "GST");
    }

/** @brief Implements rtcmEnabled. */
    bool rtcmEnabled(const char *message, const GnssOptions &o)
    {
        if (!strcmp(message, "1005"))
            return true;
        const auto msm4 = o.msmLevel == MsmLevel::Msm4 || o.msmLevel == MsmLevel::Both;
        const auto msm7 = o.msmLevel == MsmLevel::Msm7 || o.msmLevel == MsmLevel::Both;
        if (!strcmp(message, "1074"))
            return msm4 && o.gps;
        if (!strcmp(message, "1084"))
            return msm4 && o.glo;
        if (!strcmp(message, "1094"))
            return msm4 && o.gal;
        if (!strcmp(message, "1124"))
            return msm4 && o.bds;
        if (!strcmp(message, "1077"))
            return msm7 && o.gps;
        if (!strcmp(message, "1087"))
            return msm7 && o.glo;
        if (!strcmp(message, "1097"))
            return msm7 && o.gal;
        if (!strcmp(message, "1127"))
            return msm7 && o.bds;
        return !strcmp(message, "1230") && o.glo;
    }

/** @brief Implements buildTmode3Message. */
    Command buildTmode3Message() { return Command({0xB5, 0x62, 0x06, 0x71, 0x28, 0x00, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}); }

/** @brief Implements finishTmode3Checksum. */
    void finishTmode3Checksum(Command &message)
    {
        uint8_t a = 0;
        uint8_t b = 0;
        for (size_t i = 2; i < 46; ++i)
        {
            a += message[i];
            b += a;
        }
        message[46] = a;
        message[47] = b;
    }

/** @brief Implements buildOutputConfigCommand. */
    Command buildOutputConfigCommand(const GnssOptions &options)
    {
        const GnssOptions o = normalizeGnssOptions(options);
        const auto diagnostics = o.outputMode != OutputMode::RtcmOnly;
        std::vector<std::pair<uint32_t, bool>> entries;
        constexpr std::array<PortKeys, 3> protocols = {{
            {0x10740001, 0x10760001, 0x10780001},
            {0x10740002, 0x10760002, 0x10780002},
            {0x10740004, 0x10760004, 0x10780004},
        }};
        for (const String &port : o.ports)
        {
            entries.emplace_back(keyForPort(protocols[0], port), true);
            entries.emplace_back(keyForPort(protocols[1], port), diagnostics);
            entries.emplace_back(keyForPort(protocols[2], port), true);
        }
        for (const auto &message : NMEA_KEYS)
            for (const String &port : o.ports)
                entries.emplace_back(keyForPort(message.keys, port), diagnostics && isDiagnosticNmea(message.name));
        for (const auto &keys : NAV_KEYS)
            for (const String &port : o.ports)
                entries.emplace_back(keyForPort(keys, port), diagnostics);
        for (const auto &message : RTCM_KEYS)
            for (const String &port : o.ports)
                entries.emplace_back(keyForPort(message.keys, port), rtcmEnabled(message.name, o));
        Command command = ubxCfgValsetU1(entries);
        struct MsmId
        {
            bool constellation;
            uint8_t msm4;
            uint8_t msm7;
        };
        const std::array<MsmId, 4> ids = {{
            {o.gps, 0x4A, 0x4D},
            {o.glo, 0x54, 0x57},
            {o.gal, 0x5E, 0x61},
            {o.bds, 0x7C, 0x7F},
        }};
        for (const auto &id : ids)
            for (uint8_t level : {(uint8_t)4, (uint8_t)7})
            {
                const auto enabled = id.constellation && (o.msmLevel == MsmLevel::Both || static_cast<uint8_t>(o.msmLevel) == level);
                Command packet = ubxCfgMsg(0xF5, level == 4 ? id.msm4 : id.msm7, enabled ? o.ports : std::vector<String>{}, enabled ? 1 : 0);
                command.insert(command.end(), packet.begin(), packet.end());
            }
        return command;
    }

/** @brief Implements remapOutputKey. */
    inline uint32_t remapOutputKey(uint32_t key, const PortKeys &ports)
    {
        return key == ports.usb || key == ports.uart2 ? ports.uart1 : key;
    }

/** @brief Implements remapValsetKey. */
    inline uint32_t remapValsetKey(uint32_t key)
    {
        for (const auto &message : NMEA_KEYS)
            key = remapOutputKey(key, message.keys);
        for (const auto &ports : NAV_KEYS)
            key = remapOutputKey(key, ports);
        for (const auto &message : RTCM_KEYS)
            key = remapOutputKey(key, message.keys);
        for (const uint8_t protocol : {1, 2, 4})
        {
            key = remapOutputKey(
                key, {0x10740000U | protocol, 0x10760000U | protocol,
                      0x10780000U | protocol});
        }
        return key;
    }

    size_t valsetValueSize(uint8_t type)
    {
        switch (type)
        {
        case 1: // L
        case 2: // U1/I1/E1
            return 1;
        case 3: // U2/I2/E2
            return 2;
        case 4: // U4/I4/E4/R4
            return 4;
        case 5: // U8/I8/R8
            return 8;
        default:
            return 0;
        }
    }

/** @brief Implements remapValsetEntries. */
    inline bool remapValsetEntries(uint8_t *packet, size_t payloadLength)
    {
        const size_t end = payloadLength + 6;
        bool baseMode = true;
        // Validate the complete sequence before changing any keys or values.
        for (size_t i = 10; i < end;)
        {
            if (end - i < 4)
                return false;
            const uint8_t type = packet[i + 3] >> 4;
            const size_t valueSize = valsetValueSize(type);
            if (valueSize == 0 || end - i < 4 + valueSize)
                return false;
            if (packet[i] == 0x01 && packet[i + 1] == 0x00 && packet[i + 2] == 0x03 && packet[i + 3] == 0x20)
                baseMode = packet[i + 4] != 0;
            i += 4 + valueSize;
        }
        for (size_t i = 10; i < end;)
        {
            uint32_t key = 0;
            for (uint8_t b = 0; b < 4; ++b)
                key |= static_cast<uint32_t>(packet[i + b]) << (8 * b);
            const uint8_t type = packet[i + 3] >> 4;
            const size_t valueSize = valsetValueSize(type);
            if (baseMode && (key == 0x4003000FU || key == 0x40030011U))
            {
                const uint32_t accuracy = static_cast<uint32_t>(GnssCmdBuilder::BASE_ACCURACY_METERS * 10000);
                for (uint8_t b = 0; b < 4; ++b)
                    packet[i + 4 + b] = static_cast<uint8_t>(accuracy >> (8 * b));
            }
            key = remapValsetKey(key);
            for (uint8_t b = 0; b < 4; ++b)
                packet[i + b] = static_cast<uint8_t>(key >> (8 * b));
            i += 4 + valueSize;
        }
        return true;
    }

/** @brief Implements processUbloxPacket. */
    bool processUbloxPacket(uint8_t *packet, size_t remaining)
    {
        const auto payloadLength = std::to_integer<size_t>(static_cast<std::byte>(packet[4])) | (std::to_integer<size_t>(static_cast<std::byte>(packet[5])) << 8);
        if (payloadLength + 8 > remaining)
            return false;
        if (packet[2] == 0x06 && packet[3] == 0x8A && payloadLength >= 4)
        {
            if (!remapValsetEntries(packet, payloadLength))
                return false;
        }
        else if (packet[2] == 0x06 && packet[3] == 0x71 && payloadLength == 40
                 && packet[6] == 0 && (packet[8] == 1 || packet[8] == 2))
        {
            const size_t offset = packet[8] == 1 ? 34 : 26;
            const uint32_t accuracy = static_cast<uint32_t>(GnssCmdBuilder::BASE_ACCURACY_METERS * 10000);
            for (uint8_t i = 0; i < 4; ++i)
                packet[offset + i] = static_cast<uint8_t>(accuracy >> (8 * i));
        }
        else if (packet[2] == 0x06 && packet[3] == 0x01 && payloadLength == 8)
        {
            packet[9] = std::max(packet[9], std::max(packet[10], packet[11]));
            packet[10] = 0;
            packet[11] = 0;
        }
        uint8_t a = 0;
        uint8_t b = 0;
        for (size_t i = 2; i < payloadLength + 6; ++i)
        {
            a += packet[i];
            b += a;
        }
        packet[payloadLength + 6] = a;
        packet[payloadLength + 7] = b;
        return true;
    }

/** @brief Implements routeUbloxOutput. */
    void routeUbloxOutput(uint8_t *data, size_t length)
    {
        auto offset = 0;
        while (offset + 8 <= length && data[offset] == 0xB5 && data[offset + 1] == 0x62)
        {
            if (!processUbloxPacket(data + offset, length - offset))
                return;
            const auto payloadLength = std::to_integer<size_t>(
                                           static_cast<std::byte>(data[offset + 4])) |
                                       (std::to_integer<size_t>(static_cast<std::byte>(data[offset + 5])) << 8);
            offset += payloadLength + 8;
        }
    }

/** @brief Implements buildBaseSurveyInCommand. */
    CommandList buildBaseSurveyInCommand(uint32_t duration, [[maybe_unused]] float accuracy, const GnssOptions &options)
    {
        CommandList commands;
        Command message = buildTmode3Message();
        message[8] = 1;
        writeU32(message, 30, duration);
        writeU32(message, 34, static_cast<uint32_t>(GnssCmdBuilder::BASE_ACCURACY_METERS * 10000));
        finishTmode3Checksum(message);
        commands.push_back(message);
        commands.push_back(buildOutputConfigCommand(options));
        commands.emplace_back(std::begin(UBLOX_SAVE_CONFIG), std::end(UBLOX_SAVE_CONFIG));

        return commands;
    }

/** @brief Implements buildBaseFixedLlaCommand. */
    CommandList buildBaseFixedLlaCommand(double lat, double lon, double alt, [[maybe_unused]] float accuracy, const GnssOptions &options)
    {
        CommandList commands;
        Command message = buildTmode3Message();
        message[8] = 2;
        message[9] = 1;
        const std::array<double, 3> values = {lat * 10000000.0, lon * 10000000.0, alt * 100.0};
        constexpr std::array<size_t, 3> offsets = {10, 14, 18};
        for (uint8_t i = 0; i < 3; ++i)
        {
            const auto whole = static_cast<int32_t>(values[i]);
            writeU32(message, offsets[i], static_cast<uint32_t>(whole));
            message[22 + i] = static_cast<uint8_t>(static_cast<int8_t>((values[i] - whole) * 100));
        }
        const auto accuracyValue = static_cast<uint32_t>(GnssCmdBuilder::BASE_ACCURACY_METERS * 10000);
        writeU32(message, 26, accuracyValue);
        finishTmode3Checksum(message);
        commands.push_back(message);
        commands.push_back(buildOutputConfigCommand(options));
        commands.emplace_back(std::begin(UBLOX_SAVE_CONFIG), std::end(UBLOX_SAVE_CONFIG));

        return commands;
    }

/** @brief Implements buildBaseRtcmOutputCommand. */
    CommandList buildBaseRtcmOutputCommand(const String &message, const String &port, bool enabled)
    {

        auto normalizedMessage = message;
        auto normalizedPort = port;
        normalizedMessage.trim();
        normalizedMessage.toUpperCase();
        normalizedPort.trim();
        normalizedPort.toUpperCase();

        CommandList commands;
        if (!isValidRtcmPort(normalizedPort))
            return commands;

        for (const auto &rtcm : RTCM_KEYS)
        {
            if (normalizedMessage == rtcm.name)
            {
                commands.push_back(ubxCfgValsetU1({{keyForPort(rtcm.keys, normalizedPort), enabled}}));
                commands.emplace_back(std::begin(UBLOX_SAVE_CONFIG), std::end(UBLOX_SAVE_CONFIG));
                return commands;
            }
        }

        return commands;
    }

/** @brief Implements buildBaseAllRtcmOutputCommand. */
    CommandList buildBaseAllRtcmOutputCommand(const String &port, bool enabled)
    {
        auto normalizedPort = port;
        normalizedPort.trim();
        normalizedPort.toUpperCase();

        CommandList commands;
        if (!isValidRtcmPort(normalizedPort))
            return commands;

        std::vector<std::pair<uint32_t, bool>> entries;
        for (const auto &rtcm : RTCM_KEYS)
            entries.emplace_back(keyForPort(rtcm.keys, normalizedPort), enabled);
        commands.push_back(ubxCfgValsetU1(entries));
        commands.emplace_back(std::begin(UBLOX_SAVE_CONFIG), std::end(UBLOX_SAVE_CONFIG));
        return commands;
    }

/** @brief Implements buildRoverCommand. */
    CommandList buildRoverCommand()
    {
        // Enable correction input and GGA/GST output on UART1, UART2 and USB.
        Command mode = buildTmode3Message();
        finishTmode3Checksum(mode);
        GnssOptions options;
        options.ports = {"UART1", "UART2", "USB"};
        // Configure each port separately so a port-specific NAK cannot reject
        // the other port settings or the separately sent TMODE configuration.
        CommandList commands = {ubxCfgValsetU1({{0x20030001, false}}), mode};
        for (uint32_t port = 0; port < 3; ++port)
        {
            const uint32_t input = 0x10730000U + port * 0x20000U;
            const uint32_t output = input + 0x10000U;
            commands.push_back(ubxCfgValsetU1({{input | 1U, true}, {input | 4U, true}, {output | 1U, true}, {output | 2U, true}}));
            commands.push_back(ubxCfgValsetU1({{0x209100BBU + port, true},
                                               {0x209100D4U + port, true}}));
        }
        commands.push_back(ubxCfgMsg(0xF0, 0x00, options.ports, 1));
        commands.push_back(ubxCfgMsg(0xF0, 0x07, options.ports, 1));
        commands.push_back(ubxCfgMsg(0xF5, 0x05, {}, 0));
        commands.emplace_back(std::begin(UBLOX_SAVE_CONFIG), std::end(UBLOX_SAVE_CONFIG));
        return commands;
    }
}
