"""Compare fixed 1025 packets in both decoders and exercise the real ESP32 report."""
import ast
from dataclasses import dataclass, field
import logging
import math
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root.parent / 'cors/geodetic/agent_universal.py').read_text()
names = {'EllipPara','RTCMDatum','_rtcm_getbitu','_rtcm_getbits','_decode_type1025'}
nodes = [n for n in ast.parse(source).body if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.name in names]
namespace = dict(dataclass=dataclass,field=field,math=math,logging=logging)
exec(compile(ast.Module(body=nodes,type_ignores=[]),'agent-decode','exec'),namespace)
# Identical type-1 projection / 105-degree origin / 500000m FE, different SNO only.
vectors = [
    ('d30019401070400000000471e827a33ab668000ee6b2800000000000e9a16f',660000000,0.9996),
    ('d30019401070400000000471e827a3490484000ee6b28000000000002264a8',690000000,0.9999),
]
for packet_hex,sno,k0 in vectors:
    datum = namespace['RTCMDatum']()
    namespace['_decode_type1025'](bytes.fromhex(packet_hex),datum)
    assert datum.rtcm1025_update and abs(datum.k0-k0)<1e-12
    assert datum.projection_1025['raw_l0']=='9545454545'
    assert datum.projection_1025['raw_k0']==sno
    assert datum.projection_1025['projection_type']==1
    assert datum.projection_1025['frame_hex']==packet_hex
    assert datum.projection_1025['frame_bytes']==31 and not datum.projection_1025['frame_truncated']


harness = r'''
#include "functions/backend/Vn2000_Datum.h"
#include <cassert>
#include <cmath>
#include <cstring>
#include <string>
#include <vector>
void check(const std::vector<uint8_t> &packet, uint32_t scale, double expectedScale, const char *hex) {
    Vn2000Session session;
    session.feed(packet.data(), packet.size());
    const auto &datum = session.datum();
    assert(datum.has1025 && datum.projectionType == 1);
    assert(datum.projectionScaleRaw == scale && std::abs(datum.scale - expectedScale) < 1e-12);
    assert(datum.projectionLongitudeRaw == 9545454545LL);
    assert(datum.projectionFrameBytes == packet.size() && std::string(datum.projectionFrameHex.data()) == hex);
    auto corrupt=packet; corrupt.back() ^= 1; session.reset(); session.feed(corrupt.data(),corrupt.size());
    assert(!session.datum().has1025);
}
int main() {
CASES
}
'''
cases=[]
for packet_hex,sno,k0 in vectors:
    cases.append('check({'+','.join(str(b) for b in bytes.fromhex(packet_hex))+'},'+str(sno)+','+repr(k0)+',"'+packet_hex+'\");')
harness=harness.replace('CASES','\n'.join(cases))
with tempfile.TemporaryDirectory(prefix='projection-vectors-') as directory:
    path=Path(directory); (path/'check.cpp').write_text(harness)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(root/'include'),str(path/'check.cpp'),str(root/'src/functions/backend/Vn2000_Datum.cpp'),
                    '-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: fixed RTCM 1025 M3/M6 packets match Python decoder and preserve raw evidence')
