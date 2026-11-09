#pragma once
#include "functions/gnss/Unicore_Log.h"
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string_view>
#include <vector>

namespace UnicoreConfigVerification {
struct Log { char name[24] = {}; uint8_t port = 0; double period = 0; };

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

inline bool prepareLogLine(const char *&cursor, const char *end, bool hasChecksum) {
    if (!hasChecksum) {
        while (cursor < end && (*cursor == '\r' || *cursor == '\n'
                                || *cursor == ' ' || *cursor == '\t')) ++cursor;
        if (cursor < end && *cursor != '<') return false;
    }
    while (cursor < end && (*cursor == '\r' || *cursor == '\n'
                            || *cursor == ' ' || *cursor == '<')) ++cursor;
    return true;
}

inline bool readLogLine(const char *&cursor, const char *end, char (&line)[160]) {
    const char *lineEnd = cursor;
    while (lineEnd < end && *lineEnd != '\r' && *lineEnd != '\n') ++lineEnd;
    if (lineEnd - cursor > 159) return false;
    std::memcpy(line, cursor, lineEnd - cursor);
    cursor = lineEnd;
    return true;
}

inline bool parseLogCount(const char *line, long &count, std::vector<Log> &logs) {
    char *tail = nullptr;
    count = std::strtol(line, &tail, 10);
    while (tail && *tail == ' ') ++tail;
    if (!tail || tail == line || *tail || count < 0 || count > 64) return false;
    logs.reserve(count);
    return true;
}

struct ParsedLogTokens {
    char tokens[6][24] = {};
    int fields = 0;
    int start = 0;
};

inline ParsedLogTokens tokenizeLogRecord(const char *line) {
    ParsedLogTokens parsed;
    parsed.fields = std::sscanf(line, "%23s %23s %23s %23s %23s %23s",
                                parsed.tokens[0], parsed.tokens[1], parsed.tokens[2],
                                parsed.tokens[3], parsed.tokens[4], parsed.tokens[5]);
    for (auto &token : parsed.tokens)
        for (char &c : token) if (c >= 'a' && c <= 'z') c -= 'a' - 'A';
    parsed.start = std::strcmp(parsed.tokens[0], "LOG") == 0 ? 1 : 0;
    return parsed;
}

inline bool validLogIdentity(const ParsedLogTokens &parsed) {
    const int fields = parsed.fields;
    const int start = parsed.start;
    if (fields - start < 3 || fields - start > 4) return false;
    const bool portFirst = std::strncmp(parsed.tokens[start], "COM", 3) == 0;
    const char *port = parsed.tokens[start + (portFirst ? 0 : 1)];
    const char *name = parsed.tokens[start + (portFirst ? 1 : 0)];
    if (strnlen(port, sizeof(parsed.tokens[0])) != 4 || std::strncmp(port, "COM", 3)
        || port[3] < '1' || port[3] > '3' || strnlen(name, sizeof(parsed.tokens[0])) < 2
        || name[0] < 'A' || name[0] > 'Z') return false;
    for (const char *c = name; *c; ++c)
        if (!(*c >= 'A' && *c <= 'Z') && !(*c >= '0' && *c <= '9')) return false;
    return true;
}

inline bool parseLogSchedule(const ParsedLogTokens &parsed, Log &log) {
    const int fields = parsed.fields;
    const int start = parsed.start;
    const char *trigger = parsed.tokens[start + 2];
    if (!std::strcmp(trigger, "ONCE")) return fields - start == 3;

    const bool ontime = !std::strcmp(trigger, "ONTIME");
    if (fields - start != (ontime ? 4 : 3)) return false;
    char *tail = nullptr;
    const char *period = parsed.tokens[start + (ontime ? 3 : 2)];
    log.period = std::strtod(period, &tail);
    return tail && tail != period && !*tail && std::isfinite(log.period) && log.period > 0;
}

inline bool isDuplicateLog(const Log &log, const std::vector<Log> &logs) {
    for (const Log &existing : logs)
        if (existing.port == log.port && !std::strcmp(existing.name, log.name)) return true;
    return false;
}

inline bool parseLogRecord(const char *line, long count, std::vector<Log> &logs) {
    if (logs.size() >= static_cast<size_t>(count)) return false;
    const ParsedLogTokens parsed = tokenizeLogRecord(line);
    if (!validLogIdentity(parsed)) return false;

    const bool portFirst = std::strncmp(parsed.tokens[parsed.start], "COM", 3) == 0;
    const char *port = parsed.tokens[parsed.start + (portFirst ? 0 : 1)];
    const char *name = parsed.tokens[parsed.start + (portFirst ? 1 : 0)];
    Log log;
    static_assert(sizeof(log.name) == sizeof(parsed.tokens[0]));
    std::memcpy(log.name, name, sizeof(log.name));
    log.port = port[3] - '0';
    if (!parseLogSchedule(parsed, log) || isDuplicateLog(log, logs)) return false;
    logs.push_back(log);
    return true;
}

inline bool parseLogLines(const char *&cursor, const char *end, bool hasChecksum,
                          std::vector<Log> &logs, long &count) {
    while (cursor < end) {
        if (!prepareLogLine(cursor, end, hasChecksum)) return false;
        if (cursor == end) break;
        char line[160] = {};
        if (!readLogLine(cursor, end, line)) return false;
        if (count < 0) {
            if (!parseLogCount(line, count, logs)) return false;
            continue;
        }
        if (!parseLogRecord(line, count, logs)) return false;
    }
    return count >= 0 && logs.size() == static_cast<size_t>(count);
}

inline bool validLogCharacter(unsigned char value) {
    return value >= 32 && value < 127;
}

inline bool validateUnchecksummedLog(const char *text, size_t length, const char *end,
                                     std::string_view input) {
    if (input.substr(length - 2) != "\n\n" && input.substr(length - 4) != "\r\n\r\n")
        return false;
    for (const char *cursor = text; cursor < end; ++cursor) {
        const auto value = static_cast<unsigned char>(*cursor);
        if (!validLogCharacter(value) && value != '\r' && value != '\n' && value != '\t')
            return false;
    }
    return true;
}

inline bool prepareLogPayload(const char *text, size_t length, const char *&cursor,
                              const char *&end, bool &hasChecksum) {
    if (!text || length < 12 || length > 4096) return false;
    const std::string_view input(text, length);
    if (input.find('\0') != input.npos || input.substr(0, 12) != "#UNILOGLIST,") return false;
    const size_t separator = input.find(';');
    const size_t checksum = input.rfind('*');
    if (separator == input.npos) return false;

    cursor = text + separator + 1;
    hasChecksum = checksum != input.npos;
    end = text + (hasChecksum ? checksum : length);
    if (hasChecksum) return validUnicoreLogChecksum(text, length);
    return validateUnchecksummedLog(text, length, end, input);
}

inline bool parseLogs(const char *text, size_t length, std::vector<Log> &logs) {
    logs.clear();
    const char *cursor = nullptr;
    const char *end = nullptr;
    bool hasChecksum = false;
    if (!prepareLogPayload(text, length, cursor, end, hasChecksum) || cursor >= end)
        return false;
    long count = -1;
    return parseLogLines(cursor, end, hasChecksum, logs, count);
}
} // namespace UnicoreConfigVerification
