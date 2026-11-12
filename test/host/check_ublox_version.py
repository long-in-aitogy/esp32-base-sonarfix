"""Exercise MON-VER validation and readback failure handling."""
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[2]
source=(root/'src/functions/gnss/Ublox_Readback.cpp').read_text()
a=source.index('bool UbloxReadback::readVersion('); b=source.index('bool UbloxReadback::readSatellites(',a)
method=source[a:b]
codec=(root/'src/functions/backend/Backend_Agent_Codec.cpp').read_text()
a=codec.index('String encodeBase64('); b=codec.index('\n    String urlEncode(',a)
program=r'''
#include <Arduino.h>
#include <cassert>
#include "functions/gnss/Ubx_Reply.h"
namespace BackendAgentInternal {
'''+codec[a:b]+r'''
}
size_t payloadLength=40; bool available=true, invalidText=false;
template <size_t N> bool query(uint8_t cls,uint8_t id,UbxReplyBuffer<N> &reply,String &) {
    assert(cls==10 && id==4); if (!available) return false;
    reply.length=payloadLength+8; reply.frame[6]='S';
    if (invalidText) reply.frame[7]=1;
    return true;
}
namespace UbloxReadback { bool readVersion(String &,String &); }
'''
checks=r'''
int main() {
    String version, error;
    assert(UbloxReadback::readVersion(version,error) && version.size()==56);
    String previous=version; payloadLength=41;
    assert(!UbloxReadback::readVersion(version,error) && version==previous);
    payloadLength=40; invalidText=true;
    assert(!UbloxReadback::readVersion(version,error) && error=="Invalid MON-VER text");
    invalidText=false; available=false;
    assert(!UbloxReadback::readVersion(version,error) && version==previous);
}
'''
with tempfile.TemporaryDirectory(prefix='ublox-version-') as directory:
    path=Path(directory); (path/'check.cpp').write_text(program+method+checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(root/'test/host'),'-I'+str(root/'include'),str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: MON-VER payload shape, text validation and receiver failure')
