"""Compile real ESP32 datum code; compare decoded frames and NEh/LLH with Python."""
import ast
from dataclasses import dataclass, field
import logging
import math
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[2]
agent = Path(sys.argv[1]) if len(sys.argv) > 1 else root.parent / 'cors/geodetic/agent_universal.py'
names = {'EllipPara', 'RTCMDatum', '_rtcm_getbitu', '_rtcm_getbits', '_decode_type1021',
         '_decode_type1023', '_decode_type1025', '_llh_rad_to_ecef', '_ecef_to_llh_rad',
         '_blh_to_xyh', '_xy_to_blh', '_vn2000_blh_to_local_wgs84_llh', '_transform_itrf_to_vn2000_neh_and_llh'}
namespace = dict(dataclass=dataclass, field=field, math=math, logging=logging)
nodes = [node for node in ast.parse(agent.read_text()).body if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names]
assert len(nodes) == len(names)
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(agent), 'exec'), namespace)


def frame(message, fields):
    bits = f'{message:012b}'
    for value, width in fields:
        assert -(1 << (width - 1)) <= value < 1 << width
        bits += f'{value & ((1 << width) - 1):0{width}b}'
    bits += '0' * (-len(bits) % 8)
    payload = int(bits, 2).to_bytes(len(bits) // 8, 'big')
    data = bytes([0xD3, len(payload) >> 8, len(payload) & 255]) + payload
    crc = 0
    for byte in data:
        crc ^= byte << 16
        for _ in range(8):
            crc = ((crc << 1) ^ (0x1864CFB if crc & 0x800000 else 0)) & 0xFFFFFF
    return data + crc.to_bytes(3, 'big')


frames = [
    frame(1021, [(0, 5), (0, 5)] + [(0, width) for width in (8, 10, 5, 4, 2, 19, 20, 14, 14)]
          + [(191904, 23), (-39303, 23), (111450, 23), (464, 32), (-988, 32), (214, 32), (-25290, 25)]
          + [(0, 63)]),
    frame(1023, [(0, width) for width in (8, 1, 1, 21, 22, 12, 12)]
          + [(10, 8), (-20, 8), (35, 15)] + [(i - 8, 9) for i in range(48)] + [(0, 32)]),
    frame(1025, [(0, 8), (0, 6), (0, 34), (round(105.75 / 1.1e-8), 35), (660000000, 30),
                 (300000000, 36), (1000000, 35)]),
]
# Fixed CORS frames check the exact RTCM bytes as well as the decoded scale.
projection_vectors = [
    ('d30019401070400000000471e827a33ab668000ee6b2800000000000e9a16f', 660000000, 0.9996),
    ('d30019401070400000000471e827a3490484000ee6b28000000000002264a8', 690000000, 0.9999),
]
for encoded, raw_scale, scale in projection_vectors:
    projection = namespace['RTCMDatum']()
    namespace['_decode_type1025'](bytes.fromhex(encoded), projection)
    assert projection.rtcm1025_update and abs(projection.k0 - scale) < 1e-12
    assert projection.projection_1025['raw_l0'] == '9545454545'
    assert projection.projection_1025['raw_k0'] == raw_scale
    assert projection.projection_1025['frame_hex'] == encoded
# Extra trailing fields reflect real RTCM records; decoders must use bounded reads.
datum = namespace['RTCMDatum']()
for message, packet in zip((1021, 1023, 1025), frames):
    namespace[f'_decode_type{message}'](packet, datum)
assert datum.rtcm1021_update and datum.rtcm1023_update and datum.rtcm1025_update
expected = namespace['_transform_itrf_to_vn2000_neh_and_llh'](21.08499, 105.786656, -8.0624, datum)

harness = r'''
#include "functions/backend/Vn2000_Datum.h"
#include "functions/backend/Base_Sample.h"
#include <cassert>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <vector>
int main(int argc, char **argv) {
    assert(argc == 3);
    assert(fabs(ggaEllipsoidalHeight("20.5", "M", "-28.5624", "M") + 8.0624) < 1e-10);
    assert(std::isnan(ggaEllipsoidalHeight("20.5", "M", "", "M")));
    assert(std::isnan(ggaEllipsoidalHeight("invalid", "M", "0", "M")));
    assert(std::isnan(ggaEllipsoidalHeight("20.5", "F", "0", "M")));
    std::ifstream input(argv[1], std::ios::binary), shortInput(argv[2], std::ios::binary);
    std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(input)), {});
    std::vector<uint8_t> shortFrame((std::istreambuf_iterator<char>(shortInput)), {});
    Vn2000Session session;
    Vn2000Result result;
    FIXED_PROJECTIONS
    assert(!transformVn2000(21, 105, 0, session.datum(), result));
    session.feed(shortFrame.data(), shortFrame.size());
    assert(!session.datum().has1021); // Valid CRC cannot authorize truncated parameters.
    auto corrupt = bytes; corrupt[10] ^= 1;
    session.reset(); session.feed(corrupt.data(), corrupt.size());
    assert(!session.datum().has1021);
    session.reset();
    const uint8_t noise[] = {0, 0xD3, 0xFF, 0xD3, 0, 0, 7};
    session.feed(noise, sizeof(noise));
    // One-byte fragmentation and coalesced records both occur over NTRIP.
    for (uint8_t byte : bytes) session.feed(&byte, 1);
    const auto decoded = session.datum();
    assert(decoded.has1021 && decoded.has1023 && decoded.has1025);
    assert(decoded.count1021 == 1 && decoded.count1023 == 1 && decoded.count1025 == 1);
    assert(session.validFrames() == 3);
    assert(transformVn2000(21.08499, 105.786656, -8.0624, decoded, result));
    auto wrongZone = decoded; wrongZone.scale = 0.9999;
    assert(transformVn2000(21, 105, 0, wrongZone, result));
    auto invalid = decoded; invalid.centralMeridianDeg = 0;
    assert(!transformVn2000(21, 105, 0, invalid, result));
    assert(!transformVn2000(NAN, 105, 0, decoded, result));
    // Both projection widths and the optional shifts must follow the reference chain.
    for (double scale : {0.9996, 0.9999}) {
        auto shifted = decoded;
        shifted.scale = scale;
        shifted.resN = 0.25; shifted.resE = -0.75; shifted.resHS = 1.5;
        assert(transformVn2000(21.08499, 105.786656, -8.0624, shifted, result));
        std::cout << std::setprecision(16) << result.north << ' ' << result.east << ' ' << result.h << ' '
            << result.latitude << ' ' << result.longitude << ' ' << result.altitude << ' ';
    }
    assert(transformVn2000(21.08499, 105.786656, -8.0624, decoded, result));
    std::cout << std::setprecision(16) << result.north << ' ' << result.east << ' ' << result.h << ' '
        << result.latitude << ' ' << result.longitude << ' ' << result.altitude << '\n';
    session.reset();
    assert(!session.datum().has1021 && !session.datum().has1023 && !session.datum().has1025);
    assert(session.validFrames() == 0);
    assert(session.datum().count1021 == 0); // A new caster cannot reuse prior-session parameters.
    session.feed(bytes.data(), bytes.size());
    assert(session.datum().has1021 && session.datum().count1021 == 1);
}
'''
checks = []
for encoded, raw_scale, scale in projection_vectors:
    data = ','.join(str(byte) for byte in bytes.fromhex(encoded))
    checks.append('''{
        const uint8_t packet[] = {%s};
        session.reset(); session.feed(packet, sizeof(packet));
        const auto projection = session.datum();
        assert(projection.has1025 && projection.projectionScaleRaw == %d);
        assert(std::abs(projection.scale - %.4f) < 1e-12);
        assert(projection.projectionLongitudeRaw == 9545454545LL && projection.projectionType == 1);
        assert(projection.projectionFrameBytes == sizeof(packet));
        assert(std::string(projection.projectionFrameHex) == "%s");
    }''' % (data, raw_scale, scale, encoded))
harness = harness.replace('FIXED_PROJECTIONS', '\n'.join(checks) + '\n    session.reset();')
with tempfile.TemporaryDirectory(prefix='esp-vn2000-') as directory:
    path = Path(directory)
    (path / 'frames.bin').write_bytes(b''.join(frames))
    (path / 'short.bin').write_bytes(frame(1021, []))
    (path / 'check.cpp').write_text(harness)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-I' + str(root / 'include'), str(root / 'src/functions/backend/Vn2000_Datum.cpp'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    actual = [float(value) for value in subprocess.check_output([str(path / 'check'), str(path / 'frames.bin'), str(path / 'short.bin')], text=True).split()]
    expected_cases = []
    for scale in (0.9996, 0.9999):
        shifted = namespace['RTCMDatum']()
        for message, packet in zip((1021, 1023, 1025), frames):
            namespace[f'_decode_type{message}'](packet, shifted)
        shifted.k0 = scale
        shifted.resN, shifted.resE, shifted.resHS = 0.25, -0.75, 1.5
        expected_cases.append(namespace['_transform_itrf_to_vn2000_neh_and_llh'](21.08499, 105.786656, -8.0624, shifted))
    expected_cases.append(expected)
    assert len(actual) == 18
    for case, values in enumerate(expected_cases):
        for index, (cpp, python) in enumerate(zip(actual[case * 6:case * 6 + 6], values)):
            tolerance = 1e-9 if index in (3, 4) else 0.0001
            assert abs(cpp - python) < tolerance, (case, index, cpp, python)
print('PASS: CRC/truncation/fragmentation/reset checks; ESP32 NEh and LLH agree with Python within 0.1 mm / 1e-9 degrees')

# Operator's software reference: fixed 7 parameters, M6.
reference = namespace['RTCMDatum']()
reference.l0 = math.radians(105)
reference.k0 = 0.9996
software = namespace['_transform_itrf_to_vn2000_neh_and_llh'](21.084988, 105.7866608046, -9.7862, reference)
for actual, expected in zip(software[:3], (2331863.4065, 581516.0764, 15.2749)):
    assert abs(actual - expected) < 0.0001
# CORS parameters and residuals produce a different NEh from the same raw LLH.
for key, value in dict(dX=192.604, dY=37.189, dZ=111.134, rX=0.0234, rY=-0.02762, rZ=0.01152,
                       kT=1.00000008613, res_update=True, resB=9.55082951785786e-9,
                       resL=1.090830782496456e-9, resH=1.75275).items():
    setattr(reference, key, value)
reference.l0 = math.radians(9545454545 * 1.1e-8)
caster = namespace['_transform_itrf_to_vn2000_neh_and_llh'](21.084988, 105.7866608046, -9.7862, reference)
for actual, expected in zip(caster[:3], (2331863.6117, 581515.6492, 16.9987)):
    assert abs(actual - expected) < 0.0001
print('PASS: supplied M6 software reference and logged CORS transformation reproduce within 0.1 mm')
