#pragma once
#include "functions/gnss/Unicore_Log.h"
#include <array>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string_view>
#include <vector>

namespace UnicoreConfigVerification {
struct Log { std::array<char, 24> name{}; uint8_t port = 0; double period = 0; };

// MODE reports the configured Fixed LLA values, in the same units sent by mode base.
inline bool parseFixedMode(const char *mode, double &lat, double &lon, double &alt) {
    if (!mode || std::strncmp(mode, "MODE BASE ", 10) != 0) return false;
    int end = 0;
    if (std::sscanf(mode + 10, "%lf %lf %lf %n", &lat, &lon, &alt, &end) != 3
        || !end || mode[10 + end] != '\0') return false;
    return std::isfinite(lat) && std::isfinite(lon) && std::isfinite(alt)
        && std::abs(lat) <= 90 && std::abs(lon) <= 180 && alt >= -12000 && alt <= 100000;
}

// An unspecified current port can only be resolved from an unambiguous log list.
inline uint8_t comparisonPort(uint8_t configured, const std::vector<Log> &logs) {
    if (configured >= 1 && configured <= 3) return configured;
    uint8_t port = 0;
    for (const auto &log : logs) {
        if (log.port < 1 || log.port > 3 || (port && port != log.port)) return 0;
        port = log.port;
    }
    return port;
}

inline bool parseLogLine(const char *line, Log &log) {
    std::array<std::array<char, 24>, 6> tokens{};
    const int fields = std::sscanf(line, "%23s %23s %23s %23s %23s %23s",
                                   tokens[0].data(), tokens[1].data(), tokens[2].data(),
                                   tokens[3].data(), tokens[4].data(), tokens[5].data());
    for (auto &token : tokens)
        for (char &c : token) if (c >= 'a' && c <= 'z') c -= 'a' - 'A';
    const int start = std::strcmp(tokens[0].data(), "LOG") == 0 ? 1 : 0;
    if (fields - start < 3 || fields - start > 4) return false;
    const bool portFirst = std::strncmp(tokens[start].data(), "COM", 3) == 0;
    const char *port = tokens[start + (portFirst ? 0 : 1)].data();
    const char *name = tokens[start + (portFirst ? 1 : 0)].data();
    if (strnlen(port, tokens[0].size()) != 4 || std::strncmp(port, "COM", 3) || port[3] < '1' || port[3] > '3'
        || strnlen(name, tokens[0].size()) < 2 || name[0] < 'A' || name[0] > 'Z') return false;
    for (const char *c = name; *c; ++c) if (!(*c >= 'A' && *c <= 'Z') && !(*c >= '0' && *c <= '9')) return false;
    static_assert(sizeof(log.name) == sizeof(tokens[0]));
    std::memcpy(log.name.data(), name, log.name.size());
    log.port = port[3] - '0';
    if (const char *trigger = tokens[start + 2].data(); !std::strcmp(trigger, "ONCE")) {
        if (fields - start != 3) return false;
    } else {
        const bool ontime = !std::strcmp(trigger, "ONTIME");
        if (fields - start != (ontime ? 4 : 3)) return false;
        char *tail = nullptr;
        log.period = std::strtod(tokens[start + (ontime ? 3 : 2)].data(), &tail);
        if (!tail || tail == tokens[start + (ontime ? 3 : 2)].data() || *tail
            || !std::isfinite(log.period) || log.period <= 0) return false;
    }
    return true;
}

inline bool parseLogs(const char *text, size_t length, std::vector<Log> &logs) {
    logs.clear();
    if (!text || length < 12 || length > 4096) return false;
    const std::string_view input(text, length);
    if (input.find('\0') != std::string_view::npos || input.substr(0, 12) != "#UNILOGLIST,") return false;
    const size_t separator = input.find(';');
    const size_t checksum = input.rfind('*');
    if (separator == std::string_view::npos) return false;
    const char *cursor = text + separator;
    const bool hasChecksum = checksum != std::string_view::npos;
    const char *end = text + (hasChecksum ? checksum : length);
    if (hasChecksum) {
        if (!validUnicoreLogChecksum(text, length)) return false;
    } else {
        if (input.substr(length - 2) != "\n\n" && input.substr(length - 4) != "\r\n\r\n") return false;
        for (const char *c = text; c < end; ++c)
            if ((static_cast<unsigned char>(*c) < 32 && *c != '\r' && *c != '\n' && *c != '\t')
                || static_cast<unsigned char>(*c) >= 127) return false;
    }
    if (cursor >= end) return false;
    ++cursor;
    long count = -1;
    while (cursor < end) {
        if (!hasChecksum) {
            while (cursor < end && (*cursor == '\r' || *cursor == '\n' || *cursor == ' ' || *cursor == '\t')) ++cursor;
            if (cursor < end && *cursor != '<') return false;
        }
        while (cursor < end && (*cursor == '\r' || *cursor == '\n' || *cursor == ' ' || *cursor == '<')) ++cursor;
        if (cursor == end) break;
        const char *lineEnd = cursor;
        while (lineEnd < end && *lineEnd != '\r' && *lineEnd != '\n') ++lineEnd;
        if (lineEnd - cursor > 159) return false;
        std::array<char, 160> line{};
        std::memcpy(line.data(), cursor, lineEnd - cursor);
        cursor = lineEnd;
        if (count < 0) {
            char *tail = nullptr;
            count = std::strtol(line.data(), &tail, 10);
            while (tail && *tail == ' ') ++tail;
            if (!tail || tail == line.data() || *tail || count < 0 || count > 64) return false;
            logs.reserve(count);
            continue;
        }
        if (logs.size() >= static_cast<size_t>(count)) return false;
        Log log;
        if (!parseLogLine(line.data(), log)) return false;
        for (const Log &existing : logs)
            if (existing.port == log.port && !std::strcmp(existing.name.data(), log.name.data())) return false;
        logs.push_back(log);
    }
    return count >= 0 && logs.size() == static_cast<size_t>(count);
}
} // namespace UnicoreConfigVerification
