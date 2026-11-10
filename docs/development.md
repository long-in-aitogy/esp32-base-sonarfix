# Firmware development and upstream review

## Backend agent ownership

`include/functions/backend/Backend_Agent.h` defines the public agent interface. Its
implementation is split by responsibility under `src/functions/backend/`:

| File | Responsibility |
| --- | --- |
| `backend/Backend_Agent.cpp` | Startup, transport lifecycle and data queues |
| `backend/Backend_Agent_Storage.cpp` | Preferences migration, saved state and default service settings |
| `backend/Backend_Agent_Codec.cpp` | URL/Base64 decoding, fingerprints and license checks |
| `backend/cmd_handler.cpp` | Legacy MQTT commands and GNSS UART routing |
| `backend/Backend_Agent_Commands.cpp` | Backend command validation, execution and results |
| `backend/Backend_Agent_Workflows.cpp` | Auto Base, reference checks and GNSS command exchanges |
| `backend/Backend_Agent_Gnss.cpp` | Periodic receiver readback and saved Survey-In results |
| `backend/Backend_Agent_Status.cpp` | Status and health payloads |
| `backend/Backend_Agent_Projection.cpp` | Coordinate transformation and province projections |
| `backend/Backend_Agent_Websocket.cpp` | RFC6455 handshake, framing and TCP reconnects |

`include/functions/backend/Backend_Agent_Internal.h` and
`include/functions/backend/Backend_Agent_Websocket.h` are implementation headers. Keep
transport framing out of command handling and status formatting.
Survey-In status uses receiver readback; the removed GGA polling state must not
be reintroduced to make RTCM-only mode depend on NMEA.

## Verify a cleanup

Run the build and host checks in [base-4g.md](base-4g.md#kiểm-tra), plus:

```sh
python3 -B test/host/check_gnss_stream.py
python3 -B test/host/check_rover_gga.py
git diff --check
```

These checks cover software behavior. They do not establish antenna position
accuracy or replace verification on the receiver. A structural cleanup should
preserve command bytes, reply handling, NVS keys and MQTT payloads.

## Prepare an upstream change

Fetch the current `long-in-aitogy/esp32-um-ubx-base` `develop` branch and start
the review branch there. The cleanup prepared on 27 October 2026 uses
`6af5a260c9b8f62ad9296d50b01dc66c57a2092e` as its base; fetch again before
publishing because `develop` can advance.

Keep deployment defaults from upstream when transferring firmware from CORS.
Local Wi-Fi credentials and test mountpoints are not firmware fixes. Transfer
intentional command-port routing changes separately from those defaults.
Do not copy `.pio`, `compile_commands.json` or editor databases into the patch.

Review the firmware-only diff against the actual target branch. Separate
mechanical moves from behavior changes when preparing commits. A merge
conflict records overlapping edits; resolve it against the current code and
rerun the checks rather than replacing the target file with an old snapshot.

PR #103 already merged the previous CORS synchronization. PR #66 still points
to an older branch with overlapping changes. The new cleanup is prepared on a
separate branch; changing or closing that PR is a separate repository action.

## Sonar analysis inputs

`.sonarcloud.properties` configures automatic analysis. `sonar-project.properties`
provides the same source/test scope and C++/Python settings for SonarScanner CLI.
Keep both scopes aligned. Existing issue decisions remain managed in SonarCloud.

Generate a compilation database from the selected firmware environment:

```sh
/Users/tun/.platformio/penv/bin/pio run -e tdm240x_dev_general -t compiledb
```

`compile_commands.json` is machine-specific and remains ignored by Git. Configure
its use according to the CFamily analysis mode of the scanner being run.
Coverage report paths are not enabled until a job actually produces those reports.
Run authenticated CLI analysis with the token supplied through the environment;
never put a token in either properties file.
