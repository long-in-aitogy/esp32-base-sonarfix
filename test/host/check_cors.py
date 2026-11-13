"""Exercise real CORS-generated commands through the firmware UART router.

Usage: python3 test/host/check_cors.py /path/to/cors /tmp/esp32-base-checks
Build the native binary as documented in docs/base-4g.md first.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

builder_path = Path(sys.argv[1]) / "cors_dashboard/backend/app/command_builder.py"
spec = importlib.util.spec_from_file_location("cors_command_builder", builder_path)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

for sensor in ("Ublox", "Unicorecomm"):
    for method, commands in (
        ("SURVEY_IN", builder.build_base_survey_in_command(sensor, 300, 1.0)),
        ("FIXED_LLA", builder.build_base_fixed_lla_command(sensor, 10.75, 106.5, 12.5, 0.01)),
    ):
        # Delay markers are consumed by the executor, not sent to the UART.
        commands = [packet for packet in commands if not packet.startswith(b"$DELAY_")]
        result = subprocess.run(
            [sys.argv[2], sensor], input="\n".join(packet.hex() for packet in commands),
            text=True, capture_output=True, check=True,
        )
        routed = [bytes.fromhex(line) for line in result.stdout.splitlines()]
        assert len(routed) == len(commands)
        if sensor == "Unicorecomm":
            assert routed == [packet.replace(b" com3 ", b" ") for packet in commands]
            assert any(b"gga 1" in packet for packet in routed)
            assert any(b"rtcm1074 1" in packet for packet in routed)
        else:
            # The receiver always uses the 5 m Base accuracy policy.
            if method == "SURVEY_IN":
                expected_mode = builder.build_base_survey_in_command(sensor, 300, 5.0)[0]
            else:
                expected_mode = builder.build_base_fixed_lla_command(sensor, 10.75, 106.5, 12.5, 5.0)[0]
            assert routed[0] == expected_mode and routed[-1] == commands[-1]
            expected = builder.build_ublox_output_config_command({"ports": ["UART1"]})
            assert routed[1] == expected
        print(f"PASS: CORS {sensor} {method}")

for msm in (4, 7, "both"):
    options = {"output_mode": "rtcm_only", "msm_level": msm}
    for commands in (
        builder.build_base_survey_in_command("Unicorecomm", 120, 5, options),
        builder.build_lte_unicore_config("SURVEY_IN", duration=120, gnss_options=options),
    ):
        mode_index = next(i for i, packet in enumerate(commands) if packet.startswith(b"mode base time 120"))
        assert commands.index(b"config undulation 0.0\r\n") < mode_index
        assert b"unlogall\r\n" in commands
        assert not any(packet.lower().startswith((b"gpgga", b"gpgsa", b"gpgsv", b"gpgst")) for packet in commands)
        assert any(packet.lower().startswith(b"rtcm1074") for packet in commands) == (msm in (4, "both"))
        assert any(packet.lower().startswith(b"rtcm1077") for packet in commands) == (msm in (7, "both"))
print("PASS: UI RTCM-only profiles clear old output and preserve MSM4/MSM7 selection")
