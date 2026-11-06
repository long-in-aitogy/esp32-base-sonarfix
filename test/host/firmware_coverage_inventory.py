"""Use the actual ESP32 compiler to enumerate unexecuted firmware lines.

First run: pio run -e tdm240x_dev_general -t compiledb
Only object files are built, so no device or coverage runtime link is required.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def source_fingerprint():
    digest = hashlib.sha256()
    files = [ROOT / "platformio.ini"]
    for directory in ("src", "include"):
        files += sorted(path for path in (ROOT / directory).rglob("*") if path.is_file())
    for path in files:
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def gcov_inventory(text, directory):
    """GCC 8 intermediate output provides executable lines even without .gcda."""
    output = []
    keep = False
    for record in text.splitlines():
        if record.startswith("file:"):
            path = (Path(directory) / record[5:]).resolve()
            keep = path.is_relative_to(ROOT / "src") or path.is_relative_to(ROOT / "include")
            if keep:
                output += ["end_of_record", f"SF:{path}"]
        elif keep and record.startswith("lcount:"):
            line = int(record[7:].split(",", 1)[0])
            if line > 0:
                output.append(f"DA:{line},0")
    return "\n".join(output) + "\nend_of_record\n"


def compile_inventory(item):
    index, entry = item
    directory = Path(entry["directory"])
    command = entry.get("arguments") or shlex.split(entry["command"])
    compiler = Path(command[0])
    gcov = compiler.with_name(compiler.name.rsplit("-", 1)[0] + "-gcov")
    with tempfile.TemporaryDirectory(prefix=f"esp32-inventory-{index}-") as scratch:
        build = Path(scratch)
        command[command.index("-o") + 1] = str(build / "source.o")
        command += ["-fprofile-arcs", "-ftest-coverage", "-O0"]
        compiled = subprocess.run(command, cwd=directory, text=True, capture_output=True)
        if compiled.returncode:
            raise RuntimeError(f"Cannot inventory {entry['file']}:\n{compiled.stderr}")
        exported = subprocess.run([str(gcov), "-i", str(build / "source.gcno")],
                                  cwd=build, text=True, capture_output=True)
        if exported.returncode:
            raise RuntimeError(f"gcov failed for {entry['file']}:\n{exported.stderr}")
        files = list(build.glob("*.gcov"))
        if not files:
            raise RuntimeError(f"No compiler coverage inventory for {entry['file']}")
        return "\n".join(gcov_inventory(file.read_text(), directory) for file in files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "compile_commands.json")
    parser.add_argument("--output", type=Path, default=ROOT / "cpp-baseline.lcov")
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    entries = json.loads(args.database.read_text())
    entries = [entry for entry in entries
               if (Path(entry["directory"]) / entry["file"]).resolve().is_relative_to(ROOT / "src")]
    expected = {path for path in (ROOT / "src").rglob("*") if path.suffix in (".cpp", ".c")}
    actual = {(Path(entry["directory"]) / entry["file"]).resolve() for entry in entries}
    if actual != expected:
        raise RuntimeError(f"Compilation database does not cover every firmware source: {expected - actual}")
    fingerprint = source_fingerprint()
    with ThreadPoolExecutor(max_workers=args.jobs) as workers:
        reports = list(workers.map(compile_inventory, enumerate(entries)))
    if not any("DA:" in report for report in reports):
        raise RuntimeError("The firmware inventory contains no executable lines")
    if source_fingerprint() != fingerprint:
        raise RuntimeError("Firmware changed during coverage inventory generation")
    args.output.write_text("TN:" + fingerprint + "\n" + "\n".join(reports))
    print(f"Inventoried all {len(entries)} firmware translation units; wrote {args.output}")


if __name__ == "__main__":
    main()
