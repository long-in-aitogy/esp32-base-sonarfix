"""Exercise optional backend allocations with features enabled and disabled."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent.cpp').read_text()
start = source.index('#if BACKEND_PUBLISH_RAW_RTCM', source.index('void BackendAgent::begin()'))
end = source.index('    // Initialize the WebSocket endpoint', start)
allocations = source[start:end]
harness = r'''
#include <cassert>
#include <cstddef>
#include <memory>
constexpr size_t RTCM_QUEUE_LENGTH = 4;
struct DataPacket { char bytes[1032]; };
int queueAllocations = 0, socketAllocations = 0;
void *xQueueCreate(size_t count, size_t size) {
    assert(count == RTCM_QUEUE_LENGTH && size == sizeof(DataPacket));
    ++queueAllocations; static int queue; return &queue;
}
struct BackendAgent;
struct BackendAgentWebsocket { explicit BackendAgentWebsocket(BackendAgent *) { ++socketAllocations; } };
struct BackendAgent {
    void *rtcmQueue_ = nullptr;
    std::unique_ptr<BackendAgentWebsocket> websocket_;
    void allocate() {
'''
checks = r'''
    }
};
int main() {
    BackendAgent agent;
    agent.allocate(); agent.allocate();
    assert(queueAllocations == BACKEND_PUBLISH_RAW_RTCM);
    assert(socketAllocations == BACKEND_WEBSOCKET_ENABLED);
}
'''
with tempfile.TemporaryDirectory(prefix='backend-allocations-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(harness + allocations + checks)
    for rtcm in (0, 1):
        for websocket in (0, 1):
            subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                            f'-DBACKEND_PUBLISH_RAW_RTCM={rtcm}', f'-DBACKEND_WEBSOCKET_ENABLED={websocket}',
                            str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
            subprocess.run([str(path / 'check')], check=True)
print('PASS: optional RTCM and WebSocket resources allocate only when enabled')
