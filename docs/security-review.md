# Firmware security review — 31 October 2026

## Fixed in the CORS working tree

- WebSocket upgrade now requires an HTTP/1.1 101 status, Upgrade/Connection
  headers and the exact Sec-WebSocket-Accept derived from the fresh client
  nonce. Duplicate security headers, unsolicited extensions/subprotocols and
  incomplete or oversized responses are rejected. The five-second handshake
  timeout also works across millis rollover.
- Server frames with masking, RSV bits, reserved opcodes, invalid control
  lengths, nonminimal length encodings or oversized payloads are rejected.
  This client does not assemble fragmented WebSocket messages: it closes the
  connection instead of executing the first text fragment as a full command.
  Partial TCP delivery of an otherwise complete frame is still supported.
- Outgoing long text lengths are shifted as uint64_t, avoiding shifts wider
  than size_t on ESP32.
- Legacy MQTT ATG commands cannot bypass a full device lock. Embedded NUL,
  empty and oversized legacy messages are rejected. Their full text is no
  longer logged because commands may contain Wi-Fi or broker passwords.
  Scoped output locks retain their existing semantics.
- Raw-command Base64 decoding uses unsigned arithmetic, validates padding and
  trailing bits, and rejects data after padding. Valid padded/unpadded data
  and whitespace remain supported. Output capacity remains enforced.
- Existing service JSON conversions and base command finalization are shared
  instead of duplicated. Configuration keys and command byte order remain
  unchanged.

Protocol reference: [RFC 6455, client requirements and data framing](https://www.rfc-editor.org/rfc/rfc6455).
The accept challenge checks protocol correctness; it does not authenticate a
server or protect an unencrypted connection from an active network attacker.

## Verification

Development checks compiled actual Base64, frame parser and MQTT callback code
with address/undefined-behavior sanitizers. They checked legitimate commands and
ping, partial TCP frames, spoofed/incomplete upgrade responses, malformed
frames, full-capacity Base64, invalid padding, and locked/NUL/oversized legacy
commands. Header validation used the RFC example accept value. Firmware builds
also compile the mbedTLS SHA-1/Base64 calls used for the actual nonce challenge.
GNSS command, CORS compatibility, GGA, Wi-Fi handover, location ACK and VN2000
host checks pass. No hardware or production connectivity was tested.

## Remaining deployment work

MQTT currently uses WiFiClient/TinyGsmClient without TLS. The optional backend
WebSocket transport also uses plain clients. Secure transport requires matching
broker/backend endpoints, trust roots and modem TLS support; this patch does
not silently change ports or certificates on working devices. Broker ACLs must
restrict publishing commands and subscribing to device/config topics to the
intended identities. Their deployed configuration was not audited here.

The stored license/bearer-token format check is not cryptographic offline
proof of issuance. Broker/backend authentication remains the trust boundary.
Retained MQTT command/replay policy also needs broker/backend review: the
current PubSubClient callback does not expose the RETAIN flag. Configuration
state topics can contain service credentials and require restrictive ACLs.

The local configuration AP and HTTP portal have since been removed. A
one-time upgrade path selects a working legacy profile, verifies persistence
of that single network, then retires the old profile list and AP password.
Web cleanup uses fixed groups rather than arbitrary namespace/key deletion;
license, device locks, current network and base/service settings are preserved.
See [memory and storage](memory-storage.md).

Flash encryption, secure boot and hardware provisioning still require an
explicit device rollout and recovery procedure.
