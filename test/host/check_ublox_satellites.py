"""Check NAV-SAT bounds, readback and binary-safe status encoding."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
readback = (root/'src/functions/gnss/Ublox_Readback.cpp').read_text()
a=readback.index('bool UbloxReadback::readSatellites(')
b=readback.index('bool UbloxReadback::readBaud(',a)
method=readback[a:b]
codec=(root/'src/functions/backend/Backend_Agent_Codec.cpp').read_text()
a=codec.index('String encodeBase64('); b=codec.index('\n    String urlEncode(',a)
encoder=codec[a:b]
program=r'''
#include <Arduino.h>
#include <cassert>
#include "functions/gnss/Ubx_Reply.h"
#include "functions/gnss/Ubx_Satellites.h"
namespace BackendAgentInternal {
'''+encoder+r'''
}
bool invalid=false, available=true;
template <size_t N> bool query(uint8_t cls, uint8_t id, UbxReplyBuffer<N> &reply, String &) {
    assert(cls == 1 && id == 0x35); if (!available) return false;
    reply.length=8+8+12*30; reply.frame[10]=1; reply.frame[11]=30;
    for (size_t i=0;i<30;++i) { reply.frame[14+i*12]=0; reply.frame[15+i*12]=i+1; }
    if (invalid) reply.frame[15]=0;
    return true;
}
namespace UbloxReadback { bool readSatellites(String &, String &); }
'''
checks=r'''
int main() {
    String payload, error;
    assert(UbloxReadback::readSatellites(payload,error));
    assert(payload.size() == ((8+12*30+2)/3)*4 && payload.back() == '=');
    String old=payload; invalid=true;
    assert(!UbloxReadback::readSatellites(payload,error) && payload==old);
    assert(error == "Invalid NAV-SAT response");
    invalid=false; available=false;
    assert(!UbloxReadback::readSatellites(payload,error) && payload==old);
    uint8_t shortData[8]{}; assert(!UbxSatellites::valid(shortData,8));
}
'''
with tempfile.TemporaryDirectory(prefix='ublox-satellites-') as directory:
    path=Path(directory); (path/'check.cpp').write_text(program+method+checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(root/'test/host'),'-I'+str(root/'include'),str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: NAV-SAT large payload, invalid entries and binary encoding')
