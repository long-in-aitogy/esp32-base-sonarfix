"""Check verification expectations against independent u-blox HPG 1.32 keys.

Run from any directory: python3 -B test/host/check_ublox_verification.py
"""
import base64
import copy
import importlib.util
from pathlib import Path

root = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location("builder", root / "cors_dashboard/backend/app/command_builder.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def packets(data):
    while data:
        size = int.from_bytes(data[4:6], "little") + 8
        packet, data = data[:size], data[size:]
        assert packet[:2] == b"\xb5\x62" and len(packet) == size
        a = b = 0
        for byte in packet[2:-2]:
            a = (a + byte) & 255
            b = (b + a) & 255
        assert packet[-2:] == bytes([a, b])
        yield packet


def entries(data):
    return {int.from_bytes(data[i:i + 4], "little"): data[i + 4] for i in range(0, len(data), 5)}


for msm in (4, 7, "both"):
    for gal, bds in ((True, False), (False, True), (True, True)):
        config = {"base_setup_method": "FIXED_LLA", "coords": {"lat": "-21.123456789", "lon": "105.987654321", "alt": "-12.3456"},
                  "accuracy": "0.0123", "gnss_options": {"ports": ["USB", "UART2"], "output_mode": "rtcm_only", "msm_level": msm,
                  "constellations": {"gps": True, "glo": True, "gal": gal, "bds": bds}}}
        original = copy.deepcopy(config)
        result = builder.build_ublox_verification_payload(config, route_to_uart1=True)
        assert config == original
        mode = base64.b64decode(result["tmode_b64"])
        assert len(mode) == 40 and mode[2:4] == b"\x02\x01"
        assert int.from_bytes(mode[20:24], "little") == 123
        assert int.from_bytes(mode[4:8], "little", signed=True) * 100 + int.from_bytes(mode[16:17], "little", signed=True) == -21123456789
        rates = entries(base64.b64decode(result["output_b64"]))
        assert len(rates) == 31
        assert rates[0x10740001] == 1 and rates[0x10740002] == 0 and rates[0x10740004] == 1
        assert rates[0x209100BB] == 0 and rates[0x20910007] == 0  # GGA / NAV-PVT
        assert rates[0x20910369] == int(gal and msm in (4, "both"))
        assert rates[0x20910319] == int(gal and msm in (7, "both"))
        assert rates[0x2091036E] == int(bds and msm in (4, "both"))
        assert rates[0x209102D7] == int(bds and msm in (7, "both"))
        assert rates[0x209102BE] == rates[0x20910304] == 1  # 1005 / 1230
        readback = result['readback']
        assert readback['compare_ports'] == ['UART1'] and len(readback['fields']) == 32
        expected_keys = {'I2C': (0x10720001, 0x20910318, 0x10510003),
                         'UART1': (0x10740001, 0x20910319, 0x10520005),
                         'UART2': (0x10760001, 0x2091031A, 0x10530005),
                         'USB': (0x10780001, 0x2091031B, 0x10650001),
                         'SPI': (0x107A0001, 0x2091031C, 0x10640006)}
        for port in readback['ports']:
            keys = entries(base64.b64decode(port['output_b64']))
            assert len(keys) == 32 and all(key in keys for key in expected_keys[port['name']])

blob = builder.build_ublox_output_config_command({"ports": ["UART1", "UART2", "USB"]})
valsets = [p for p in packets(blob) if p[2:4] == b"\x06\x8a"]
assert len(valsets) == 2
assert sum((len(p) - 12) // 5 for p in valsets) == 93
assert all((len(p) - 12) // 5 <= 64 for p in valsets)
for invalid in ({}, {"base_setup_method": "SURVEY_IN"}, {"base_setup_method": "FIXED_LLA", "coords": {"lat": 10}}):
    try:
        builder.build_ublox_verification_payload(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError("Incomplete/non-fixed configuration accepted")
print("PASS: independent Galileo/BeiDou keys, MSM4/7/both, RTCM-only, UART routing, decimal/HP fields, 64-key limit")
