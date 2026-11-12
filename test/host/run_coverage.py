"""Export measured native firmware coverage for SonarQube using LLVM."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[2]
compiler = os.environ.get('CXX', 'clang++')
profdata = os.environ.get('LLVM_PROFDATA', 'llvm-profdata')
cov = os.environ.get('LLVM_COV', 'llvm-cov')
suites = {
    'base': ['test/host/base_checks.cpp', 'src/functions/gnss/Unicore_Log.cpp',
             'src/functions/gnss/gnss_cmd_builder.cpp', 'src/functions/gnss/ublox_commands.cpp',
             'src/functions/gnss/unicore_commands.cpp'],
    'mqtt': ['test/host/mqtt_write_checks.cpp'],
    'wifi': ['test/host/wifi_profiles_checks.cpp'],
    'protocol': ['test/host/protocol_checks.cpp'],
}
files = {}


def add_report(report):
    lines = None
    for record in report.splitlines():
        if record.startswith('SF:'):
            path = Path(record[3:]).resolve()
            lines = None
            if path.is_relative_to(root) and path.relative_to(root).parts[0] in ('src', 'include'):
                lines = files.setdefault(path.relative_to(root).as_posix(), {})
        elif lines is not None and record.startswith('DA:'):
            number, count, *_ = record[3:].split(',')
            lines[int(number)] = lines.get(int(number), False) or int(count) > 0


with tempfile.TemporaryDirectory(prefix='esp32-coverage-') as directory:
    build = Path(directory)
    for name, sources in suites.items():
        binary = build / name
        subprocess.run([compiler, '-std=c++17', '-g', '-fsanitize=address,undefined',
                        '-fprofile-instr-generate', '-fcoverage-mapping',
                        '-I' + str(root / 'test/host'), '-I' + str(root / 'include'),
                        *[str(root / path) for path in sources], '-o', str(binary)], check=True)
        raw, profile = build / f'{name}.profraw', build / f'{name}.profdata'
        subprocess.run([str(binary)], check=True, env=dict(os.environ, LLVM_PROFILE_FILE=str(raw)))
        subprocess.run([profdata, 'merge', '-sparse', str(raw), '-o', str(profile)], check=True)
        report = subprocess.check_output([cov, 'export', '-format=lcov',
                                          f'-instr-profile={profile}', str(binary)], text=True)
        add_report(report)
    for name in ('service_config', 'backend_queues', 'license_reference_commands', 'control_failover_workflow',
                 'status_matrix', 'backend_save_state', 'autobase_command', 'auto_base_transform',
                 'network_lifecycle', 'unicore_survey_ack', 'ntrip_source_connect', 'workflow_restore',
                 'unicore_fixed_readback', 'ntrip_handshake', 'gnss_stream', 'mqtt_dispatch', 'stream_targeting'):
        report = build / f'{name}.lcov'
        environment = dict(os.environ, CXX=compiler, LLVM_PROFDATA=profdata, LLVM_COV=cov,
                           HOST_COVERAGE_OUTPUT=str(report))
        subprocess.run([sys.executable, str(root / f'test/host/check_{name}.py')], check=True, env=environment)
        add_report(report.read_text())
if not any(any(lines.values()) for lines in files.values()):
    raise SystemExit('No measured firmware lines in coverage report')
coverage = ET.Element('coverage', version='1')
for path, lines in sorted(files.items()):
    file = ET.SubElement(coverage, 'file', path=path)
    for number, hit in sorted(lines.items()):
        ET.SubElement(file, 'lineToCover', lineNumber=str(number), covered=str(hit).lower())
    print(f'{path}: {sum(lines.values())}/{len(lines)} measured lines covered')
ET.ElementTree(coverage).write(root / 'cpp-coverage.xml', encoding='utf-8', xml_declaration=True)
