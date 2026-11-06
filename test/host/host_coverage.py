"""Optional coverage for existing native harnesses; standalone checks stay unchanged."""
import json
import os
from pathlib import Path
import re
import subprocess

_compiled = {}


def remap_lcov(lcov, sources):
    """LLVM reports physical lines; map only explicitly marked, verified fragments."""
    mappings = {}
    for filename in sources:
        mapping = {}
        origin, line = None, 1
        for physical, text in enumerate(Path(filename).read_text().splitlines(), 1):
            directive = re.fullmatch(r'#line (\d+) (".*")', text)
            if directive:
                line = int(directive[1]); origin = json.loads(directive[2])
            else:
                if origin and Path(origin).is_absolute():
                    mapping[physical] = (origin, line)
                line += 1
        if mapping:
            mappings[str(Path(filename).resolve())] = mapping
    output, current = [], None
    for record in lcov.splitlines():
        if record.startswith("SF:"):
            current = mappings.get(str(Path(record[3:]).resolve()))
            if current is None:
                output.append(record)
        elif current is None:
            output.append(record)
        elif record.startswith("DA:"):
            physical, count, *_ = record[3:].split(",")
            location = current.get(int(physical))
            if location:
                origin, line = location
                output += [f"SF:{origin}", f"DA:{line},{count}", "end_of_record"]
    return "\n".join(output)


def mapped(path, fragment, *, stripped_includes=False):
    """Map unchanged production code to its real source lines using #line."""
    path = Path(path).resolve()
    source = path.read_text()
    if stripped_includes:
        if fragment != re.sub(r"^#include.*$", "", source, flags=re.M):
            raise ValueError(f"Modified source cannot receive coverage: {path}")
        line = 1
    else:
        start = source.find(fragment)
        if start < 0 or not fragment:
            raise ValueError(f"Fragment does not match production source: {path}")
        if source.find(fragment, start + 1) >= 0:
            raise ValueError(f"Ambiguous source fragment: {path}")
        line = source.count("\n", 0, start) + 1
    return f'\n#line {line} {json.dumps(str(path))}\n{fragment}\n#line 1 "host-harness"\n'


def compile_cpp(command, **kwargs):
    command = list(command)
    command[1:1] = ["-g"]
    output = os.environ.get("HOST_COVERAGE_OUTPUT")
    if output:
        command[0] = os.environ["CXX"]
        command[1:1] = ["-g", "-fprofile-instr-generate", "-fcoverage-mapping"]
        json_dir = os.environ.get("HOST_ARDUINOJSON")
        if json_dir:
            command = [f"-I{json_dir}" if arg.startswith("-I") and "/.pio/libdeps/" in arg else arg
                       for arg in command]
        binary = command[command.index("-o") + 1]
        profile = str(Path(binary).with_suffix(".profraw"))
        _compiled[binary] = (profile, [arg for arg in command if arg.endswith(".cpp")])
    return subprocess.run(command, **kwargs)


def run_cpp(command, **kwargs):
    binary = str(command[0])
    compiled = _compiled.get(binary)
    if not compiled:
        return subprocess.run(command, **kwargs)
    profile, sources = compiled
    environment = dict(os.environ, LLVM_PROFILE_FILE=profile)
    result = subprocess.run(command, env=environment, **kwargs)
    if result.returncode:
        raise subprocess.CalledProcessError(result.returncode, command)
    indexed = str(Path(profile).with_suffix(".profdata"))
    subprocess.run([os.environ["LLVM_PROFDATA"], "merge", "-sparse", profile, "-o", indexed], check=True)
    lcov = subprocess.check_output([os.environ["LLVM_COV"], "export", "-format=lcov",
                                   f"-instr-profile={indexed}", binary], text=True)
    with open(os.environ["HOST_COVERAGE_OUTPUT"], "a") as report:
        report.write(remap_lcov(lcov, sources) + "\n")
    return result


def cpp_output(command, **kwargs):
    return run_cpp(command, stdout=subprocess.PIPE, check=True, **kwargs).stdout
