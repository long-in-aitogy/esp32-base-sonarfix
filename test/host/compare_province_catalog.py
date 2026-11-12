"""Compare the firmware's legacy province meridians against a CORS checkout."""
from collections import defaultdict
from pathlib import Path
import json
import re
import sys

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Projection.cpp').read_text()
table = source[source.index('constexpr std::array<ProvinceProjection'):source.index('    struct EcefCoordinate')]
entries = re.findall(r'\{"([A-Z_]+)",\s*"[^"]+",\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?(?:,\s*([\d.]+))?\}', table)
codes = {
    'AG_KG':'91', 'BN_BG':'24', 'CM_BL':'96', 'CAO_BANG':'04', 'DAKLAK_PY':'66',
    'DIEN_BIEN':'11', 'DNAI_BPHUOC':'75', 'DTHAP_TGIANG':'82', 'GLAI_BDINH':'52',
    'HA_TINH':'42', 'HYEN_TBINH':'33', 'KH_HOA_NTHUAN':'56', 'LAI_CHAU':'12',
    'LANG_SON':'20', 'LCAI_YBAI':'15', 'LDONG_DNONG_BTHUAN':'68', 'NGHE_AN':'40',
    'NBINH_HNAM_NDINH':'37', 'PHU_THO_VPHUC_HBINH':'25', 'QNGAI_KTUM':'51',
    'QNINH':'22', 'QTRI_QBINH':'44', 'SON_LA':'14', 'TNINH_LONGAN':'80',
    'TNGUYEN_BKAN':'19', 'THANH_HOA':'38', 'CTHO_STRANG_HGIANG':'92',
    'DANANG_QNAM':'48', 'HA_NOI':'01', 'HPHONG_HDUONG':'31',
    'HCM_BRVT_BDUONG':'79', 'HUE':'46', 'TQUANG_HGIANG':'08', 'VLONG_BTRE_TVINH':'86',
}
path = Path(sys.argv[1]) / 'cors_dashboard/backend/app/data/coordinate_provinces.json'
expected = defaultdict(set)
for item in json.loads(path.read_text()):
    expected[item['current_code']].add(item['central_meridian'])
assert len(entries) == len(codes) == len(expected) == 34
for code, primary, scale, alternate1, alternate2 in entries:
    actual = {float(value) for value in (primary, alternate1, alternate2) if value}
    assert actual == expected[codes[code]], (code, actual, expected[codes[code]])
    assert float(scale) == 0.9999, (code, scale)
print('PASS: all 34 firmware province meridian choices match the CORS catalog')
