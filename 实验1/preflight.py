"""Read-only static/environment inspection; never connects to or starts a device."""
import argparse
import pathlib
import re
import shutil
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--net", type=pathlib.Path,
                        default=pathlib.Path(__file__).resolve().parent / "lab1.net")
    args = parser.parse_args()
    net = args.net.resolve()
    if not net.is_file():
        print(f"NOT READY: topology file missing: {net}")
        return 1
    text = net.read_text(encoding="utf-8")
    errors = []
    sections = {}
    current = None
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        match = re.fullmatch(r"\[\[router (\w+)\]\]", line)
        if match:
            current = match[1]
            if current in sections:
                errors.append(f"duplicate device {current}")
            sections[current] = {}
        elif current and "=" in line:
            key, value = map(str.strip, line.split("=", 1))
            if key in sections[current]:
                errors.append(f"duplicate key {current}.{key}")
            sections[current][key] = value
    devices = ["SW1", "SW2", "PC1", "PC2", "PC3"]
    if set(sections) != set(devices):
        errors.append("expected exactly SW1/SW2/PC1/PC2/PC3")
    links = {
        ("SW1", "f1/11"): "PC1 f0/0",
        ("SW1", "f1/12"): "PC2 f0/0",
        ("SW1", "f1/1"): "SW2 f1/2",
        ("SW1", "f1/2"): "SW2 f1/1",
        ("SW2", "f1/11"): "PC3 f0/0",
    }
    actual_links = {(name, key): value for name, fields in sections.items()
                    for key, value in fields.items() if re.fullmatch(r"f\d+/\d+", key)}
    if actual_links != links:
        errors.append("link declarations differ from PPT topology")
    for index, name in enumerate(devices):
        fields = sections.get(name, {})
        expected = {"console": str(3004 + index),
                    "model": "3640" if name.startswith("SW") else "2621"}
        if name.startswith("SW"):
            expected.update(slot1="NM-16ESW", ram="128", exec_area="64")
        for key, value in expected.items():
            if fields.get(key) != value:
                errors.append(f"{name}.{key}: expected {value}, got {fields.get(key)}")
        commands = net.parent / "commands" / f"{name}.txt"
        if not commands.is_file():
            errors.append(f"missing commands: {commands}")
    if errors:
        for error in errors:
            print(f"FAIL static: {error}")
    else:
        print("PASS static: 5 devices, console 3004-3008, 5 PPT links, 5 command files")
    blockers = list(errors)
    for name in ("dynamips",):
        binary = shutil.which(name) or shutil.which(name + ".exe")
        print(f"TOOL {name}: {binary or 'MISSING FROM PATH'}")
        if not binary:
            blockers.append(f"{name} missing from PATH (installed GUI packages need manual confirmation)")
    print("CONSOLE: Python telnetlib3; legacy Dynagen/telnet executable not required")
    for raw in sorted({fields.get("image", "") for fields in sections.values()}):
        if not raw:
            blockers.append("image path missing")
            continue
        path = pathlib.Path(raw.replace("\\", "/"))
        if not path.is_absolute():
            path = net.parent / path
        if path.is_file() and path.stat().st_size > 0:
            print(f"IMAGE exists (boot compatibility unverified): {path.resolve()} ({path.stat().st_size} bytes)")
        else:
            print(f"IMAGE MISSING at configured path: {path.resolve()}")
            blockers.append(f"image not at configured path: {raw}")
    work_match = re.search(r"^\s*workingdir\s*=\s*(.+)$", text, re.MULTILINE)
    if work_match:
        work = pathlib.Path(work_match[1].strip().replace("\\", "/"))
        if not work.is_absolute():
            work = net.parent / work
        print(f"WORKINGDIR: {work.resolve()} ({'exists' if work.is_dir() else 'MISSING'})")
        if not work.is_dir():
            blockers.append("working directory missing")
    else:
        blockers.append("workingdir missing")
    for blocker in blockers:
        print(f"BLOCKER: {blocker}")
    print("PRECHECK ONLY: this check does not start IOS or verify ping; use ./run.sh 实验1 for live acceptance")
    return 1 if blockers else 0


if __name__ == "__main__":
    sys.exit(main())
