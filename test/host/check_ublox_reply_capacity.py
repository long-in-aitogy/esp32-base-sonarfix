"""Keep normal UBX reply limit while supporting large NAV-SAT frames."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
program = r'''
#include "functions/gnss/Ubx_Reply.h"
#include <cassert>
#include <vector>
int main() {
    std::vector<uint8_t> packet{0xb5,0x62,1,0x35,0x2c,1}; // 300-byte payload
    packet.resize(306, 0);
    uint8_t a=0,b=0;
    for (size_t i=2;i<packet.size();++i) { a+=packet[i]; b+=a; }
    packet.push_back(a); packet.push_back(b);
    UbxReply normal; UbxReplyBuffer<1544> large;
    bool normalDone=false, largeDone=false;
    for (uint8_t byte : packet) { normalDone |= normal.feed(byte); largeDone |= large.feed(byte); }
    assert(!normalDone && largeDone && large.length == packet.size());
    packet.back() ^= 1; UbxReplyBuffer<1544> bad; bool accepted=false;
    for (uint8_t byte : packet) accepted |= bad.feed(byte);
    assert(!accepted);
}
'''
with tempfile.TemporaryDirectory(prefix='ubx-capacity-') as directory:
    path=Path(directory)
    (path/'check.cpp').write_text(program)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(root/'include'),str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: bounded UBX frames, large reply and checksum rejection')
