"""Check both workflow snapshots preserve the active receiver duration."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'src/functions/backend/Backend_Agent_Workflows.cpp').read_text()
blocks = []
for method, name, end in (
    ('runAutoBaseWorkflow', 'previousBase', '    auto finish'),
    ('runReferenceCheckWorkflow', 'storedBase', '    auto cleanup'),
):
    body = source[source.index('bool BackendAgent::' + method):]
    start = body.index('    DynamicJsonDocument ' + name + '(CONFIG_DOCUMENT_SIZE);')
    block = body[start:body.index(end, start)]
    blocks.append('''{
        String baseConfig_ = R"({"base_setup_method":"SURVEY_IN","survey_in_duration":1800})";
        for (uint32_t surveyInTargetSeconds_ : {0U, 120U, 300U}) {
''' + block + f'''
            assert({name}["survey_in_duration"] == (surveyInTargetSeconds_ ? surveyInTargetSeconds_ : 1800U));
            assert(baseConfig_.find("1800") != String::npos);
        }}
    }}''')
with tempfile.TemporaryDirectory(prefix='survey-snapshot-') as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text('#include <Arduino.h>\n#include <ArduinoJson.h>\n#include <cassert>\nconstexpr size_t CONFIG_DOCUMENT_SIZE=6144;\nint main() {\n' + '\n'.join(blocks) + '\n}')
    subprocess.run(['c++', '-std=c++17', '-fsanitize=address,undefined',
                    '-I' + str(root / 'test/host'),
                    '-I' + str(root / '.pio/libdeps/tdm240x_dev_general/ArduinoJson/src'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
print('PASS: both workflows snapshot 120/300 seconds without changing saved 1800 seconds')
