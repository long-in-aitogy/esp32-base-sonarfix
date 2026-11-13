"""Check actual CORS-generated u-blox packets through the firmware router.

Usage: python3 test/host/check_cors_accuracy.py /path/to/cors /tmp/esp32-base-checks
"""
import importlib.util
from pathlib import Path
import subprocess
import sys

builder_path = Path(sys.argv[1]) / 'cors_dashboard/backend/app/command_builder.py'
spec = importlib.util.spec_from_file_location('cors_command_builder', builder_path)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

for modern in (False, True):
    profile = {'modern': modern, 'itfm': True}
    for mode in ('SURVEY_IN', 'FIXED_LLA'):
        if mode == 'SURVEY_IN':
            packet = builder.build_base_survey_in_command('Ublox', 300, 3, receiver_profile=profile)[0]
        else:
            packet = builder.build_base_fixed_lla_command('Ublox', 10.75, 106.5, 12.5, 0.01, receiver_profile=profile)[0]
        result = subprocess.run([sys.argv[2], 'Ublox'], input=packet.hex() + '\n',
                                capture_output=True, text=True, check=True)
        actual = bytes.fromhex(result.stdout.strip())
        expected = bytearray(packet)
        if modern:
            offset = 10
            while offset < len(expected) - 2:
                key = int.from_bytes(expected[offset:offset + 4], 'little')
                size = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8}[key >> 28]
                if key in (0x4003000F, 0x40030011):
                    expected[offset + 4:offset + 8] = (50000).to_bytes(4, 'little')
                offset += 4 + size
        else:
            offset = 34 if mode == 'SURVEY_IN' else 26
            expected[offset:offset + 4] = (50000).to_bytes(4, 'little')
        a = b = 0
        for byte in expected[2:-2]:
            a = (a + byte) & 0xFF
            b = (b + a) & 0xFF
        expected[-2:] = bytes((a, b))
        assert actual == expected, (mode, modern)
print('PASS: actual CORS Survey-In/Fixed commands normalize to 5 m in TMODE3 and VALSET')
