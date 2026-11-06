#include "functions/backend/Websocket_Protocol.h"
#include <cassert>
#include <initializer_list>
#include <string>

int main() {
    using namespace WebsocketProtocol;
    const std::string accept = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=";
    const std::string headers = "Upgrade: websocket\r\nConnection: keep-alive, Upgrade\r\nSec-WebSocket-Accept: " + accept + "\r\n";
    const std::string valid = "HTTP/1.1 101 Switching Protocols\r\n" + headers + "\r\n";
    assert(validUpgrade(valid, accept));
    assert(validUpgrade("HTTP/1.1 101\r\n" + headers + "\r\n", accept));
    assert(validUpgrade("HTTP/1.1 101 OK\r\nUPGRADE: WebSocket\r\nconnection: upgrade\r\nsec-websocket-accept: " + accept + "\r\nX-Test: value\r\n\r\n", accept));
    assert(!validUpgrade(valid, "wrong") && !validUpgrade(valid, ""));
    assert(!validUpgrade(std::string(4097, 'x'), accept));
    for (size_t length = 0; length < valid.size(); ++length)
        assert(!validUpgrade(valid.substr(0, length), accept));
    for (const auto &status : {"HTTP/1.0 101", "HTTP/1.1 200 OK", "HTTP/1.1 1010 OK"})
        assert(!validUpgrade(std::string(status) + "\r\n" + headers + "\r\n", accept));
    for (const auto &extra : std::initializer_list<std::string>{"Upgrade: websocket\r\n", "Connection: upgrade\r\n",
                             "Sec-WebSocket-Accept: " + accept + "\r\n",
                             "Sec-WebSocket-Extensions: permessage-deflate\r\n",
                             "Sec-WebSocket-Protocol: unexpected\r\n", "missing-colon\r\n", ": value\r\n"})
        assert(!validUpgrade("HTTP/1.1 101\r\n" + headers + extra + "\r\n", accept));
    assert(!validUpgrade("HTTP/1.1 101\r\nUpgrade: h2\r\nConnection: upgrade\r\nSec-WebSocket-Accept: " + accept + "\r\n\r\n", accept));
    assert(!validUpgrade("HTTP/1.1 101\r\nUpgrade: websocket\r\nConnection: keep-alive\r\nSec-WebSocket-Accept: " + accept + "\r\n\r\n", accept));
    assert(!validUpgrade("HTTP/1.1 101\r\nUpgrade: websocket\r\n\r\n", accept));
    assert(trim(" \t ").empty());
    assert(hasToken("keep-alive, \tUpgrade ", "upgrade"));
    assert(!hasToken("upgrades,keep-alive", "upgrade"));
}
