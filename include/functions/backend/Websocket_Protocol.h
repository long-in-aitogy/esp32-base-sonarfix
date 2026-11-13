#pragma once
#include <string>
#include <string_view>
#include <algorithm>
#include <cctype>

namespace WebsocketProtocol {
inline std::string lower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(),
                   [](unsigned char c) { return std::tolower(c); });
    return value;
}
inline std::string trim(std::string_view value) {
    const auto start = value.find_first_not_of(" \t");
    return start == std::string_view::npos ? std::string()
        : std::string(value.substr(start, value.find_last_not_of(" \t") - start + 1));
}
inline bool hasToken(std::string_view value, std::string_view token) {
    size_t start = 0;
    do {
        const auto end = value.find(',', start);
        if (lower(trim(value.substr(start, end - start))) == token) return true;
        if (end == std::string_view::npos) break;
        start = end + 1;
    } while (start < value.size());
    return false;
}
inline bool validUpgrade(std::string_view response, std::string_view accept) {
    if (accept.empty() || response.size() > 4096 || response.size() < 4
        || response.compare(response.size() - 4, 4, "\r\n\r\n") != 0) return false;
    const auto firstEnd = response.find("\r\n");
    if (const auto status = response.substr(0, firstEnd); status != "HTTP/1.1 101" && status.compare(0, 13, "HTTP/1.1 101 ") != 0) return false;
    bool upgrade = false;
    bool connection = false;
    bool accepted = false;
    for (size_t start = firstEnd + 2; start + 2 < response.size();) {
        const auto end = response.find("\r\n", start);
        const auto line = response.substr(start, end - start);
        const auto colon = line.find(':');
        if (colon == std::string_view::npos || colon == 0) return false;
        const auto name = lower(std::string(line.substr(0, colon)));
        const auto value = trim(line.substr(colon + 1));
        if (name == "upgrade") {
            if (upgrade || lower(value) != "websocket") return false;
            upgrade = true;
        } else if (name == "connection") {
            if (connection || !hasToken(value, "upgrade")) return false;
            connection = true;
        } else if (name == "sec-websocket-accept") {
            if (accepted || value != accept) return false;
            accepted = true;
        } else if (name == "sec-websocket-extensions" || name == "sec-websocket-protocol") {
            return false; // Neither was requested by this client.
        }
        start = end + 2;
    }
    return upgrade && connection && accepted;
}
} // namespace WebsocketProtocol
