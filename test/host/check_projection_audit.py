"""Compare fixed 1025 packets in both decoders and exercise the real ESP32 report."""
import ast
from dataclasses import dataclass, field
import logging
import math
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root.parent / 'agent_universal.py').read_text()
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

workflow = (root / 'src/functions/backend/Backend_Agent_Workflows.cpp').read_text()
helpers = workflow[workflow.index('String datumParameterText('):workflow.index('// Correlation is checked')]
report = workflow[workflow.index('    DynamicJsonDocument progress(CONFIG_DOCUMENT_SIZE);',workflow.index('bool BackendAgent::runAutoBaseWorkflow')):workflow.index('    if (progress.overflowed())')]
harness = r'''
#include <Arduino.h>
#include <ArduinoJson.h>
#include "functions/backend/Vn2000_Datum.h"
#include <cassert>
#include <cmath>
#include <limits>
#include <vector>
#include <iostream>
constexpr size_t CONFIG_DOCUMENT_SIZE = 8192; // Host pointers/JSON slots are larger than ESP32.
unsigned slots(JsonVariantConst value) {
    unsigned count = value.size();
    if (value.is<JsonObjectConst>()) for (JsonPairConst item:value.as<JsonObjectConst>()) count += slots(item.value());
    if (value.is<JsonArrayConst>()) for (JsonVariantConst item:value.as<JsonArrayConst>()) count += slots(item);
    return count;
}
'''
checks = r'''
void check(std::vector<uint8_t> bytes, uint32_t sno, double k0) {
    Vn2000Session session;
    session.feed(bytes.data(),bytes.size());
    auto datum = session.datum();
    assert(datum.has1025 && datum.projectionScaleRaw == sno && fabs(datum.scale-k0)<1e-12);
    assert(datum.projectionLongitudeRaw == 9545454545LL && datum.projectionType == 1);
    assert(datum.projectionFrameBytes == 31 && strlen(datum.projectionFrameHex) == 62);
    assert(std::string(datum.projectionFrameHex) == expectedHex);
    datum.has1021 = datum.has1023 = true;
    std::vector<double> latitudes(56,21.08499);
    double rawLatitude=21.08499,rawLongitude=105.78666,rawAltitude=-9.83;
    Vn2000Result result{2331863.64,581515.72,16.94,21.084990131093591,105.78665745895107,-8.1155038587749004};
    String sensorType_="Unicorecomm",host="cors.example",mountpoint="VRS.105M6",projectionSource="rtcm1025";
    uint16_t port=2101;
    bool enableTransform=true;
    DynamicJsonDocument location(1024);
    location["province_code"]="01"; location["province_name"]="Ha Noi";
    REPORT
    assert(!progress.overflowed());
    // ESP32 ArduinoJson v6 uses 16-byte slots, native host uses 32-byte slots.
    const auto used = progress.memoryUsage() - slots(progress.as<JsonVariantConst>()) * (JSON_OBJECT_SIZE(1)-16);
    assert(used + 256 <= 4096); // Leave space for phase, step, timestamp and later telemetry.
    assert(report["processor"] == "esp32" && report["projection_source"] == "rtcm1025");
    assert(report["rtcm1025"]["raw_k0"] == sno && report["rtcm1025"]["raw_l0"] == "9545454545");
    assert(report["rtcm1025"]["frame_hex"] == expectedHex);
    String wire; serializeJson(progress,wire);
    DynamicJsonDocument roundtrip(8192);
    assert(deserializeJson(roundtrip,wire) == DeserializationError::Ok);
    assert(roundtrip["conversion_report"]["rtcm1025"]["raw_k0"] == sno);
    std::cout << "ESP32 projection report bytes=" << wire.length() << "; estimated ESP32 JSON memory=" << used << "\n";
}
int main() {
    CASES
}
'''
# Use fixed packets, not a decoder-generated encoder round trip.
cases = []
for packet_hex,sno,k0 in vectors:
    cases.append('expectedHex="'+packet_hex+'"; check({'+','.join(str(b) for b in bytes.fromhex(packet_hex))+'},'+str(sno)+','+repr(k0)+');')
checks = checks.replace('REPORT',report).replace('CASES','\n'.join(cases))
with tempfile.TemporaryDirectory(prefix='esp-projection-audit-') as directory:
    path = Path(directory)
    (path/'check.cpp').write_text(harness+'\nconst char *expectedHex;\n'+helpers+checks)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
        '-I'+str(root/'test/host'),'-I'+str(root/'include'),'-I'+str(root/'.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
        str(path/'check.cpp'),str(root/'src/functions/backend/Backend_Agent_Projection.cpp'),'-o',str(path/'check')],check=True)
    subprocess.run([str(path/'check')],check=True)
print('PASS: fixed M3/M6 1025 packets, Python/ESP32 raw fields, exact frame preservation and production report round trip/budget')
