"""Test the complete RTCM datum decoder and logged VN2000 reference without CORS files."""
from pathlib import Path
import tempfile
from host_coverage import compile_cpp, run_cpp

root = Path(__file__).resolve().parents[2]


def frame(message, fields):
    bits = f'{message:012b}'
    for value, width in fields:
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


packets = [
    frame(1021, [(0, 5), (0, 5)] + [(0, width) for width in (8, 10, 5, 4, 2, 19, 20, 14, 14)]
          + [(191904, 23), (-39303, 23), (111450, 23), (464, 32), (-988, 32), (214, 32), (-25290, 25)]),
    frame(1023, [(0, width) for width in (8, 1, 1, 21, 22, 12, 12)]
          + [(10, 8), (-20, 8), (35, 15)] + [(i - 8, 9) for i in range(48)]),
    bytes.fromhex('d30019401070400000000471e827a33ab668000ee6b2800000000000e9a16f'),
    frame(1021, []),
    frame(1025, [(0, 8), (1, 6), (1, 34), (round(105 / 1.1e-8), 35), (660000000, 30), (0, 36), (0, 35)]),
    frame(1033, [(0, 32)]),
]
harness = r'''
#include "functions/backend/Vn2000_Datum.h"
#include <cassert>
#include <cmath>
#include <fstream>
#include <iterator>
#include <vector>
int main(int argc, char **argv) {
    assert(argc == 7);
    std::vector<std::vector<uint8_t>> packets;
    for (int i = 1; i < argc; ++i) {
        std::ifstream file(argv[i], std::ios::binary);
        packets.emplace_back(std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>());
    }
    Vn2000Session session; Vn2000Result result;
    assert(!transformVn2000(21, 105, 0, session.datum(), result));
    session.feed(packets[3].data(), packets[3].size()); assert(!session.datum().has1021);
    session.reset(); auto corrupt = packets[0]; corrupt.back() ^= 1;
    session.feed(corrupt.data(), corrupt.size()); assert(!session.datum().has1021);
    const uint8_t noise[] = {0, 0xd3, 0xff, 0xd3, 0, 0, 7}; session.feed(noise, sizeof(noise));
    for (unsigned i = 0; i < 3; ++i) for (uint8_t byte : packets[i]) session.feed(&byte, 1);
    auto datum = session.datum();
    assert(datum.has1021 && datum.has1023 && datum.has1025 && session.validFrames() == 3);
    assert(std::abs(datum.dX - 191.904) < 1e-9 && std::abs(datum.dY + 39.303) < 1e-9);
    assert(datum.projectionScaleRaw == 660000000 && std::abs(datum.scale - 0.9996) < 1e-12);
    assert(datum.projectionLongitudeRaw == 9545454545LL && datum.projectionFrameBytes == 31);
    assert(transformVn2000(21.08499, 105.786656, -8.0624, datum, result));
    for (double scale : {0.9996, 0.9999}) {
        datum.scale = scale; datum.resN = 0.25; datum.resE = -0.75; datum.resHS = 1.5;
        assert(transformVn2000(21.08499, 105.786656, -8.0624, datum, result));
        assert(std::isfinite(result.north) && std::isfinite(result.east));
    }
    // Independently recorded CORS reference, already documented in check_vn2000.py.
    Vn2000Datum reference; reference.has1021 = reference.has1023 = true;
    reference.dX=192.604; reference.dY=37.189; reference.dZ=111.134;
    reference.rX=0.0234; reference.rY=-0.02762; reference.rZ=0.01152; reference.kT=1.00000008613;
    reference.resB=9.55082951785786e-9; reference.resL=1.090830782496456e-9; reference.resH=1.75275;
    reference.centralMeridianDeg=9545454545 * 1.1e-8; reference.scale=0.9996;
    assert(transformVn2000(21.084988,105.7866608046,-9.7862,reference,result));
    assert(std::abs(result.north-2331863.6117)<0.0001);
    assert(std::abs(result.east-581515.6492)<0.0001 && std::abs(result.h-16.9987)<0.0001);
    for (unsigned failure=0; failure<9; ++failure) {
        auto invalid=reference;
        if(failure==0) invalid.has1021=false;
        if(failure==1) invalid.centralMeridianDeg=0;
        if(failure==2) invalid.scale=0.998;
        if(failure==3) invalid.resN=NAN;
        if(failure==4) invalid.resE=INFINITY;
        if(failure==5) invalid.resHS=NAN;
        assert(!transformVn2000(failure==6 ? NAN : failure==7 ? 91 : 21,
                               failure==8 ? 181 : 105,0,invalid,result));
    }
    const auto before=session.datum();
    session.feed(packets[4].data(),packets[4].size());
    assert(session.datum().centralMeridianDeg==before.centralMeridianDeg);
    session.feed(packets[5].data(),packets[5].size());
    assert(session.datum().dX==before.dX);
    session.reset(); assert(session.validFrames()==0 && !session.datum().has1021);
    session.feed(packets[0].data(),packets[0].size()); assert(session.datum().has1021);
}
'''
with tempfile.TemporaryDirectory(prefix='projection-native-') as directory:
    path = Path(directory)
    inputs = []
    for index, packet in enumerate(packets):
        file = path / f'{index}.bin'; file.write_bytes(packet); inputs.append(str(file))
    (path / 'check.cpp').write_text(harness)
    compile_cpp(['c++', '-std=c++17', '-fsanitize=address,undefined', '-I' + str(root / 'include'),
                 str(root / 'src/functions/backend/Backend_Agent_Projection.cpp'), str(path / 'check.cpp'),
                 '-o', str(path / 'check')], check=True)
    run_cpp([str(path / 'check'), *inputs], check=True)
print('PASS: complete datum decoder, CRC/fragmentation/truncation, invalid projection, session reset, logged 0.1 mm reference')
