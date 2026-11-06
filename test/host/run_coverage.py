"""Run native firmware tests with ASan/UBSan and export measured Sonar coverage.

Requires matching Clang, llvm-profdata and llvm-cov tools, plus ArduinoJson 6.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]


def tool(name, variable):
    if os.environ.get(variable):
        return os.environ[variable]
    if sys.platform == "darwin" and name != "clang++":
        return subprocess.check_output(["xcrun", "--find", name], text=True).strip()
    result = shutil.which(name)
    if not result:
        raise SystemExit(f"Missing {name}; install Clang and LLVM, or set {variable}")
    return result


def sonar_report(lcov, destination):
    """Keep real production paths and merge coverage across test executables."""
    files = {}
    current = None
    for record in lcov.splitlines():
        if record.startswith("SF:"):
            path = Path(record[3:]).resolve()
            current = None
            if path.is_relative_to(ROOT):
                relative = path.relative_to(ROOT)
                if relative.parts[0] in ("src", "include"):
                    current = files.setdefault(relative.as_posix(), {})
        elif record.startswith("DA:") and current is not None:
            line, count, *_ = record[3:].split(",")
            number = int(line)
            current[number] = current.get(number, False) or int(count) > 0
    if not files or not any(any(lines.values()) for lines in files.values()):
        raise RuntimeError("No executed firmware lines in the coverage export")
    report = ET.Element("coverage", version="1")
    for path, lines in sorted(files.items()):
        file = ET.SubElement(report, "file", path=path)
        for line, covered in sorted(lines.items()):
            ET.SubElement(file, "lineToCover", lineNumber=str(line), covered=str(covered).lower())
        hit = sum(lines.values())
        print(f"{path}: {hit}/{len(lines)} measured lines covered")
    ET.ElementTree(report).write(destination, encoding="utf-8", xml_declaration=True)
    print(f"Wrote {destination}; uninstrumented firmware remains uncovered in Sonar")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arduinojson", type=Path,
                        default=ROOT / ".pio/libdeps/tdm240x_dev_general/ArduinoJson/src")
    parser.add_argument("--output", type=Path, default=ROOT / "cpp-coverage.xml")
    args = parser.parse_args()
    if not (args.arduinojson / "ArduinoJson.h").is_file():
        parser.error("--arduinojson must contain ArduinoJson.h (version 6)")
    compiler = tool("clang++", "CXX")
    profdata = tool("llvm-profdata", "LLVM_PROFDATA")
    cov = tool("llvm-cov", "LLVM_COV")
    suites = {
        "base": ["base_checks.cpp", "src/functions/gnss/gnss_cmd_builder.cpp",
                 "src/functions/gnss/ublox_commands.cpp", "src/functions/gnss/unicore_commands.cpp"],
        "codec": ["codec_checks.cpp", "src/functions/backend/Backend_Agent_Codec.cpp"],
        "config": ["config_verification_checks.cpp"],
        "mqtt": ["mqtt_write_checks.cpp"],
        "wifi": ["wifi_profiles_checks.cpp"],
        "sample": ["sample_checks.cpp"],
        "protocol": ["protocol_checks.cpp"],
        "readback": ["readback_checks.cpp", "src/functions/gnss/Ublox_Readback.cpp",
                     "src/functions/gnss/Unicore_Readback.cpp", "src/functions/backend/Backend_Agent_Codec.cpp"],
    }
    with tempfile.TemporaryDirectory(prefix="esp32-coverage-") as directory:
        build = Path(directory)
        exports = []
        for name, sources in suites.items():
            binary = build / name
            include = [ROOT / "test/host/readback"] if name == "readback" else []
            include += [ROOT / "test/host", ROOT / "include", args.arduinojson.resolve()]
            command = [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-DNATIVE_BUILD",
                       "-g", "-fsanitize=address,undefined", "-fprofile-instr-generate", "-fcoverage-mapping"]
            command += [f"-I{path}" for path in include]
            command += [str(ROOT / (source if source.startswith("src/") else f"test/host/{source}"))
                        for source in sources]
            print(f"Running {name} firmware checks", flush=True)
            subprocess.run(command + ["-o", str(binary)], check=True, cwd=ROOT)
            environment = dict(os.environ, LLVM_PROFILE_FILE=str(build / f"{name}-%p.profraw"))
            subprocess.run([str(binary)], check=True, env=environment, cwd=ROOT)
            # Keep each binary's profile separate: host shims differ between suites.
            profile = build / f"{name}.profdata"
            subprocess.run([profdata, "merge", "-sparse", *map(str, sorted(build.glob(f"{name}-*.profraw"))),
                            "-o", str(profile)], check=True)
            exports.append(subprocess.check_output(
                [cov, "export", "-format=lcov", f"-instr-profile={profile}", str(binary)], text=True, cwd=ROOT))
        for name in ("backend_lifecycle", "backend_storage", "detection_lifecycle", "gnss_lifecycle", "network_lifecycle",
                     "projection_native", "workflow_lifecycle", "base_startup_confirmation", "gga_position", "gnss_stream", "mqtt_dispatch",
                     "ntrip_reconnect", "nvs_inventory", "rover_gga", "status_stream", "websocket_frames",
                     "wifi_handover", "wifi_nvs", "workflow_progress", "workflow_restore"):
            print(f"Running {name} integration checks", flush=True)
            report = build / f"{name}.lcov"
            environment = dict(os.environ, CXX=compiler, LLVM_PROFDATA=profdata, LLVM_COV=cov,
                               HOST_COVERAGE_OUTPUT=str(report), HOST_ARDUINOJSON=str(args.arduinojson.resolve()))
            subprocess.run([sys.executable, str(ROOT / f"test/host/check_{name}.py")],
                           check=True, env=environment, cwd=ROOT)
            exports.append(report.read_text())
        sonar_report("\n".join(exports), args.output)


if __name__ == "__main__":
    main()
