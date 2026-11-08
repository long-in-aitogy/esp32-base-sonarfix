# Remaining sonarfix changes and feature preservation

Review date: 8 November 2026. Author repository:
[`long-in-aitogy/esp32-base-sonarfix`](https://github.com/long-in-aitogy/esp32-base-sonarfix).
The remote `develop` tip is still `0d7eeb895b239be6494da20c3d71f0d9067d5459`;
`main` is `1672fad117bcc8f04af46fa09b9c07393aac77f9`. No newer author
commit was available during this review. Our starting revision is `8831d42`.

This is a selective integration. Git ancestry is not a claim that the entire
author branch has been merged. The review compares remaining source/header
changes after removing whitespace and comments, then checks incoming commit
bodies and the local callers, persistent state and protocol boundaries.

## Disposition of remaining changes

| Area | Author's remaining work | Decision and retained behavior |
| --- | --- | --- |
| Backend event loop | `retryUnknownChipProbe`, queue/loop separation and inlined declarations | The retry/loop boundaries are already present. Keep compile-time transport guards and the local location-reply queue. Do not copy embedded storage/codec bodies back into the loop. |
| Commands | Scoped lock helper, command dispatcher decomposition, stream-value normalization | Command boundaries are already local. Adopt consistent configured-mountpoint normalization. Keep additional storage/verification commands, license rollback, input validation and read-only verification behavior. |
| Auto Base | More helpers for configuration, sampling, projection, result construction and completion | Wait/sample boundaries are already present. Do not transplant upstream completion: it applies coordinates immediately, whereas our path produces `ready_for_review`, correlates location replies, decodes the current RTCM datum and retains M3/M6 conversion evidence. Remaining helper extraction can be adapted separately; it is not missing runtime functionality. |
| Reference check | Configuration/start/wait/sample/result helpers | Preserve local cancellation, Base mode/Survey-In restoration, actual receiver target duration, fresh RTK sampling and transport cleanup. The upstream body restores coordinate triples instead of our complete previous Base configuration. |
| Startup/readback | Configuration helpers, simpler receiver readback and array conversions | Keep local boot recovery, saved-mode/position confirmation, complete MON-VER/NAV-SAT/VALGET checks, multiline UNILOGLIST, WGS84/geoid/sigma validation and byte preservation. A helper-only reorganization is optional, but the upstream bodies are not equivalent. |
| GNSS builders | u-blox routing helpers, enum/array/byte conversions and shorter VALSET builder | Routing helper split is integrated. Keep local 1094/1097/1127 table and the 64-entry VALSET split. Keep Unicore coordinate formatting and shared Base finalization. Style-only type conversions do not justify a protocol change. |
| Mixed UART parser | RTCM/UBX helpers, early returns and `std::array` storage | Helper split is integrated. Keep ellipsoidal height from GGA MSL height plus geoid separation, bad-position invalidation, raw RTCM forwarding and bounded NMEA token inspection. |
| NTRIP | Base/Rover/common files, endpoint helpers, additional bootstrap helpers and explicit loop flags | File/endpoint separation is integrated. Keep shared Base64/JSON helpers, corrected reconnect status, rollover-safe timeout, single-line ICY boundary, datum decoding, short UART write failure and fixed status return for a valid 504-byte read. Do not restore unused receiver bootstrap paths. |
| WebSocket | Byte conversions and simpler upgrade/frame handling | Keep SHA-1 accept verification, server frame validation, size bounds, elapsed-time timeout and receive-buffer reclamation. Existing frame-reader decomposition is already integrated. |
| Wi-Fi/SIM/network | Inline network recovery in main, simpler Wi-Fi connection and automatic APN | Keep Network_Manager ownership, fallback validation, recovery hysteresis, bounded attempts, Wi-Fi NVS migration/credential validation, configured APN and GPRS credentials. |
| Status | Early returns, stream loop, cached transport state and array access | Useful status simplifications are integrated. Keep verification/NVS fields, conversion reports, navigation/satellite/version data and hacc units. Status JSON remains equivalent in 144 cases. |
| Partition/toolchain | Espressif 6.12.0, `no_ota.csv`, compilation database settings | Keep verified Espressif 7.1.3 and our partition table. The installed standard `no_ota.csv` has no `app1` or `agent_state`; adopting it would remove the current partition layout and dedicated backend-state allocation. This is not a safe cleanup. |
| CI/Sonar | `.sonarcloud.properties` and suppression of `cpp::S5421`; no equivalent local workflow in the author's tree | Keep the current Actions workflow, full firmware inventory/native coverage and Quality Gate waiting. Do not import rule suppression or remove tests/reports. |
| Documentation | Doxygen configuration, generated PDFs, moved-path references and a different catalogue output-path policy | Do not overwrite current feature documentation/PDFs with an older feature set. Keep tested catalogue path restrictions. Doxygen is an optional developer-documentation addition and is not required for firmware behavior. |
| Small headers and support files | Formatting/comments, `auto`, `std::array`, `std::byte`, scoped enum, unused include removal | Token-equivalent formatting and style-only changes are not separate feature fixes. No broad mechanical rewrite is needed for the current zero-issue Sonar result. |

## Failure reproduced during this review

The real `applyServiceStreamCommand` implementation was exercised with two enabled
on-demand servers and legacy configurations whose per-server active flag is absent
or null. A command targeted at one server could change the other server through
the shared `stream_active` fallback. Global start also could leave an earlier
per-server stop in effect. Separately, configured mountpoints with surrounding
whitespace failed targeting, and slash/case variants could retain a stale
`active_mountpoint` after stopping the selected stream.

The focused fix keeps the untargeted on-demand server's prior state before
recomputing the global summary, makes global commands update per-server flags,
and uses the existing normalization helper for matching/clearing mountpoints.
Always-on streams still ignore stop requests. Unknown-target legacy fallback,
server-ID/address aliases, locks, licensing and fail-open policy retain their
existing routing. JSON keys remain owned by ArduinoJson.

The test failed against the pre-fix implementation before product code changed.
The durable harness now checks 72 scoped/global transitions in addition to the
existing 44 stream commands and 144 status cases. Missing and null per-server
flags, both server IDs, start/stop, whitespace/slash/case variants and subsequent
global start/stop are exercised. Status output is compared with the starting tree.

## Feature-preservation evidence

| Existing feature | Executable checks retained |
| --- | --- |
| Auto Base review, 60-sample averaging, location reply ownership/correlation and cancellation | `check_workflow_lifecycle.py`, `check_workflow_progress.py`, `check_backend_lifecycle.py` |
| Reference check and safe Base/Survey-In restoration | `check_workflow_lifecycle.py`, `check_workflow_restore.py`, `check_base_startup_confirmation.py` |
| VN2000 datum/M3/M6 and recorded numerical reference | `check_projection_native.py`, projection decoder checks |
| GNSS ACK/readback, chip detection and saved configuration | `readback_checks.cpp`, `config_verification_checks.cpp`, `check_gnss_lifecycle.py`, `check_detection_lifecycle.py`, `check_base_startup_confirmation.py` |
| Scoped locks, license rollback, service deployment, command guards and NVS migration | `base_checks.cpp`, `check_command_dispatch.py`, `check_workflow_lifecycle.py`, `check_backend_storage.py`, `check_nvs_inventory.py` |
| Source/Rover transport, GGA forwarding, datum-session boundary and UART short writes | `check_ntrip_lifecycle.py`, `check_ntrip_config.py`, `check_ntrip_reconnect.py`, `check_rover_gga.py`, `check_workflow_restore.py` |
| MQTT validation/chunking and network/Wi-Fi recovery | `check_mqtt_dispatch.py`, `mqtt_write_checks.cpp`, `check_network_lifecycle.py`, `check_wifi_handover.py`, `check_wifi_nvs.py`, `wifi_profiles_checks.cpp` |
| WebSocket upgrade/frame validation | `protocol_checks.cpp`, `check_websocket_frames.py` |
| Status fields, units and per-server stream control | `check_status_stream.py` |
| Catalogue rendering and constrained output paths | `docs/test_render_catalogues.py` |

Earlier routing verification compared 2,000 generated VALSET/CFG-MSG packets
byte-for-byte. A further ASan/UBSan differential harness compared parser output,
callbacks, state and buffers after every byte of more than 1,000,000 mixed/noisy
bytes against the pre-cleanup parser. These are software checks; receiver accuracy,
real modem timing and field operation still require hardware verification.
