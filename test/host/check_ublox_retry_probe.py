"""Validate the actual u-blox retry probe against complete and malformed MON-VER replies."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent.cpp').read_text()
probe = source[source.index('bool BackendAgent::probeUblox('):source.index('bool BackendAgent::probePassiveUblox(')]
harness = r'''
#include <Arduino.h>
#include "functions/gnss/Ubx_Reply.h"
#include <array>
#include <cassert>
#include <deque>
#include <vector>
uint32_t now = 0;
uint32_t millis() { return now; }
void delay(unsigned ms) { now += ms; }
struct Stream {
    std::deque<uint8_t> incoming; std::vector<uint8_t> reply;
    int available() { return incoming.size(); }
    int read() { auto value = incoming.front(); incoming.pop_front(); return value; }
    size_t write(const uint8_t *, size_t size) { incoming.insert(incoming.end(), reply.begin(), reply.end()); return size; }
};
struct BackendAgent { bool probeUblox(Stream &); };
'''
checks = r'''
int main() {
    BackendAgent agent; Stream stream;
    std::vector<uint8_t> frame = {0xb5,0x62,0x0a,0x04,40,0};
    frame.insert(frame.end(),40,'A'); uint8_t a=0,b=0;
    for (size_t i=2;i<frame.size();++i) { a+=frame[i]; b+=a; }
    frame.push_back(a); frame.push_back(b);
    stream.reply=frame; assert(agent.probeUblox(stream));
    stream.reply={0xb5,0x62,0x0a,0x04}; assert(!agent.probeUblox(stream));
    stream.reply={0xb5,0x62,0x0a,0x04,0,0,0x0e,0x34}; assert(!agent.probeUblox(stream));
    stream.reply=frame; stream.reply.back()^=1; assert(!agent.probeUblox(stream));
    stream.reply={0,0xb5,0,0}; stream.reply.insert(stream.reply.end(),frame.begin(),frame.end());
    assert(agent.probeUblox(stream));
}
'''
with tempfile.TemporaryDirectory(prefix='ublox-retry-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + probe + checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I'+str(root/'test/host'),'-I'+str(root/'include'),
                    str(path/'check.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: retry identifies only complete checksum-valid u-blox MON-VER replies')
