#!/usr/bin/env python3
"""Run our Cisco IOS lab through the native Dynamips hypervisor.

Requires configobj and telnetlib3. Creates an isolated evidence/working directory
and terminates only the Dynamips child it created. No global reset or kill.
"""
import argparse
import asyncio
import datetime
import hashlib
import json
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

from configobj import ConfigObj
import telnetlib3

ROOT = Path(__file__).resolve().parent.parent
PROMPT = re.compile(r"(?:^|[\r\n])([\w.-]+(?:\([^\r\n]*\))?[>#])(?=\s*(?:[\r\n]|$))")
ERROR = re.compile(r"(?:%\s*(?:Invalid input|Incomplete command|Ambiguous command|Error|Cannot|IP addresses may not|Access VLAN does not exist|Unrecognized command)|Command rejected:)", re.I)


def report(message):
    print(message, flush=True)


class Hypervisor:
    def __init__(self, port, log):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=30)
        self.reader = self.sock.makefile("rb")
        self.log = log

    def command(self, command):
        self.log.write("> " + command + "\n")
        self.log.flush()
        self.sock.sendall((command + "\n").encode())
        lines = []
        while True:
            line = self.reader.readline().decode("utf-8", errors="replace")
            if not line:
                raise RuntimeError("Dynamips disconnected: " + command)
            self.log.write(line)
            self.log.flush()
            lines.append(line.rstrip())
            if re.match(r"\d{3}-", line):
                if not line.startswith("100-"):
                    raise RuntimeError(command + ": " + line.strip())
                return "\n".join(lines)

    def close(self):
        self.reader.close()
        self.sock.close()


class Console:
    def __init__(self, name, reader, writer, log):
        self.name, self.reader, self.writer, self.log = name, reader, writer, log

    async def until_prompt(self, timeout=30, startup=False, expected_echo=None):
        deadline = time.monotonic() + timeout
        data = ""
        answered = False
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                chunk = await asyncio.wait_for(self.reader.read(4096), min(remaining, 2))
            except asyncio.TimeoutError:
                if startup:
                    self.writer.write("\r\n")
                continue
            if not chunk:
                raise RuntimeError(self.name + " console disconnected")
            self.log.write(chunk)
            self.log.flush()
            data += chunk
            if startup and not answered and "initial configuration dialog" in data.lower():
                self.writer.write("no\r\n")
                answered = True
            if startup and "press return to get started" in chunk.lower():
                self.writer.write("\r\n")
            if PROMPT.search(data) and (expected_echo is None or expected_echo in data):
                return data
        raise TimeoutError(self.name + " prompt timeout; last output: " + data[-500:])

    async def command(self, text, timeout=120, interrupt_after=None):
        self.log.write("\n>>> " + text + "\n")
        self.log.flush()
        self.writer.write(text + "\r\n")
        if interrupt_after is not None:
            await asyncio.sleep(interrupt_after)
            self.writer.write("\x1e")
        output = await self.until_prompt(timeout=timeout, expected_echo=text[:32])
        if ERROR.search(output):
            raise RuntimeError(self.name + " rejected " + text + ": " + output)
        return output


def quote(value):
    value = str(value)
    if '"' in value or "\n" in value:
        raise ValueError("Unsupported hypervisor argument")
    return '"' + value + '"'


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def iface(value):
    match = re.fullmatch(r"[fes](\d+)/(\d+)", value, re.I)
    if not match:
        raise ValueError("Unsupported interface " + value)
    return tuple(map(int, match.groups()))


async def run(args):
    lab = ROOT / args.experiment
    topology = lab / ("lab1.net" if args.experiment == "实验1" else "topology.net")
    spec_path = lab / "specification.json"
    spec = json.loads(spec_path.read_text().replace("205.42.", f"205.{args.student_octet}.")) if spec_path.exists() else None
    cfg = ConfigObj(topology.read_text().replace("205.42.", f"205.{args.student_octet}.").splitlines(), encoding="utf-8", list_values=False)
    server = cfg["localhost"]
    devices = {key.split(" ", 1)[1]: value for key, value in server.items() if key.startswith("router ")}
    stamp = datetime.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    evidence = lab / "evidence" / stamp
    work = evidence / "working"
    work.mkdir(parents=True)
    result = {"status": "NOT READY", "started_at": datetime.datetime.now().astimezone().isoformat(),
              "topology": str(topology), "gates": {}, "devices": {}, "pings": [], "errors": []}
    result["student_octet"] = args.student_octet
    result["address_parameter_provisional"] = args.student_octet != 161
    if spec_path.exists():
        result["specification_sha256"] = sha256(spec_path)
        spec["_lab_path"] = str(lab)
    result["sha256"] = {"topology": sha256(topology), "commands": {}, "ios": {}, "runner": sha256(Path(__file__)), "acceptance": sha256(Path(__file__).with_name("acceptance.py"))}
    report("Evidence: " + str(evidence))
    process = None
    hv = None
    consoles = {}
    handles = []
    disk_watch = None
    try:
        if shutil.disk_usage(ROOT).free < 512*1024*1024:
            raise RuntimeError("磁盘剩余不足512MiB，拒绝启动模拟器")
        result["disk_free_before"] = shutil.disk_usage(ROOT).free
        parent = asyncio.current_task()
        async def watch_disk():
            while True:
                await asyncio.sleep(5)
                free = shutil.disk_usage(ROOT).free
                if free < 200*1024*1024:
                    result["errors"].append("磁盘剩余低于200MiB，停止运行以保留日志和失败结果")
                    parent.cancel()
                    return
        disk_watch = asyncio.create_task(watch_disk())
        binary = shutil.which("dynamips")
        if not binary:
            raise RuntimeError("dynamips not installed")
        port = int(server.get("port", 7200))
        probe = socket.socket()
        try:
            probe.bind(("127.0.0.1", port))
        finally:
            probe.close()
        dlog = (evidence / "dynamips.log").open("w")
        hlog = (evidence / "hypervisor.log").open("w")
        handles.extend([dlog, hlog])
        process = subprocess.Popen([binary, "-H", "127.0.0.1:" + str(port)], cwd=work, stdout=dlog, stderr=subprocess.STDOUT)
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("Dynamips exited; see dynamips.log")
            try:
                hv = Hypervisor(port, hlog)
                break
            except OSError:
                await asyncio.sleep(.1)
        if hv is None:
            raise RuntimeError("Hypervisor failed to listen")
        result["hypervisor_version"] = hv.command("hypervisor version")
        hv.command("hypervisor working_dir " + quote(work))
        for index, (name, node) in enumerate(devices.items(), 1):
            model = str(node["model"])
            family = "c3600" if model in ("3620", "3640", "3660") else "c2600"
            image = Path(str(node["image"]).replace("\\", "/"))
            if not image.is_absolute():
                image = (lab / image).resolve()
            if not image.is_file():
                raise FileNotFoundError(image)
            report("Create " + name + " " + model)
            hv.command(f"vm create {name} {index} {family}")
            hv.command(f"{family} set_chassis {name} {model}")
            hv.command(f"vm set_ios {name} " + quote(image))
            for key, api in (("ram", "set_ram"), ("confreg", "set_conf_reg"), ("console", "set_con_tcp_port"), ("exec_area", "set_exec_area"), ("idlepc", "set_idle_pc")):
                if key in node:
                    hv.command(f"vm {api} {name} {node[key]}")
            hv.command(f"vm set_ram_mmap {name} 0")
            for key, adapter in node.items():
                if re.fullmatch(r"slot\d+", key):
                    hv.command(f"vm slot_add_binding {name} {key[4:]} 0 {adapter}")
            result["devices"][name] = {"model": model, "image": str(image), "console_port": int(node["console"])}
            result["sha256"]["ios"][str(image)] = sha256(image)
            result["sha256"]["commands"][name] = sha256(lab / "commands" / (name + ".txt"))
        udp = int(server.get("udp", 10000))
        seen = set()
        links = []
        nio_by_endpoint = {}
        captures = []
        for name, node in devices.items():
            for interface, target in node.items():
                if not re.fullmatch(r"[fes]\d+/\d+", interface, re.I):
                    continue
                remote, remote_interface = str(target).split()
                endpoints = tuple(sorted(((name, interface), (remote, remote_interface))))
                if endpoints in seen:
                    continue
                seen.add(endpoints)
                for side, (host, interface) in enumerate(endpoints):
                    slot, port_number = iface(interface)
                    nio = f"link{len(links)}_{side}"
                    local_port = udp + side
                    peer_port = udp + 1 - side
                    hv.command(f"nio create_udp {nio} {local_port} 127.0.0.1 {peer_port}")
                    hv.command(f"vm slot_add_nio_binding {host} {slot} {port_number} {nio}")
                    nio_by_endpoint[(host, interface.lower())] = nio
                links.append(endpoints)
                udp += 2
        result["links"] = links
        if spec:
            result["gates"]["expected_devices_and_links"] = len(devices) == spec["expected_devices"] and len(links) == spec["expected_links"]
            for capture in spec.get("captures", []):
                nio = nio_by_endpoint[(capture["device"], capture["interface"].lower())]
                path = evidence / (capture["name"] + ".pcap")
                hv.command(f"nio bind_filter {nio} 2 capture")
                hv.command(f"nio setup_filter {nio} 2 {capture.get('link_type', 'en10mb')} " + quote(path))
                captures.append({"nio": nio, "path": str(path), "name": capture["name"]})
            result["captures"] = captures
        else:
            result["gates"]["five_devices_five_links"] = len(devices) == 5 and len(links) == 5
        for name in devices:
            report("Start " + name)
            hv.command("vm start " + name)
        async def connect(name, node):
            reader, writer = await telnetlib3.open_connection(host="127.0.0.1", port=int(node["console"]), encoding="latin1", connect_minwait=.1, connect_maxwait=1)
            logfile = (evidence / (name + ".console.log")).open("w")
            handles.append(logfile)
            console = Console(name, reader, writer, logfile)
            consoles[name] = console
            writer.write("\r\n")
            await console.until_prompt(timeout=600, startup=True)
            report(name + " IOS prompt ready")
        await asyncio.gather(*(connect(name, node) for name, node in devices.items()))
        result["gates"]["ios_boot"] = True
        # The real API returns one line per candidate: "101 0x... [count]".
        # Both MIPS and PPC interpreter loops implement idle_pc (nojit supported).
        result["idlepc"] = {}
        by_image = {}
        for name, node in devices.items():
            by_image.setdefault(result["devices"][name]["image"], []).append(name)
        for image, names in by_image.items():
            representative = names[0]
            report("Calibrate idlepc " + representative + " (approximately 10 seconds)")
            # Do not calibrate against a preloaded idle value: official CPU code
            # explicitly rejects calibration while one is in use.
            for name in names:
                hv.command(f"vm set_idle_pc_online {name} 0 0")
            output = hv.command(f"vm get_idle_pc_prop {representative} 0")
            candidates = [{"pc": pc, "count": int(count)} for pc, count in re.findall(r"(0x[0-9a-fA-F]+)\s+\[(\d+)\]", output)]
            record = {"representative": representative, "devices": names, "raw_output": output, "candidates": candidates}
            result["idlepc"][image] = record
            if not candidates:
                raise RuntimeError("No actual idlepc candidates for " + representative)
            chosen = max(candidates, key=lambda item: item["count"])
            record["selected"] = chosen
            record["applied_responses"] = {}
            for name in names:
                response = hv.command(f"vm set_idle_pc_online {name} 0 {chosen['pc']}")
                record["applied_responses"][name] = response
                report(name + " idlepc " + chosen["pc"] + " count=" + str(chosen["count"]))
        result["gates"]["idlepc_calibrated_and_applied"] = True
        async def configure(name):
            console = consoles[name]
            commands = (lab / "commands" / (name + ".txt")).read_text().replace("205.42.", f"205.{args.student_octet}.").splitlines()
            for command in commands:
                command = command.strip()
                if command and not command.startswith(("!", "#")):
                    report(name + " > " + command)
                    await console.command(command)
            await console.command("terminal length 0")
            result["devices"][name]["configuration_applied"] = True
        await asyncio.gather(*(configure(name) for name in devices))
        result["gates"]["configuration"] = True
        if spec:
            from acceptance import exercise, verify_captures, run_hooks
            await exercise(spec, consoles, result, evidence)
            for capture in captures:
                hv.command(f"nio unbind_filter {capture['nio']} 2")
            verify_captures(spec, captures, result)
            await run_hooks(spec, result, evidence)
        else:
            report("Waiting 65 seconds for STP convergence")
            for _ in range(13):
                await asyncio.sleep(5)
                report("STP convergence wait " + str((_ + 1) * 5) + "/65")
            stp = []
            for name, console in consoles.items():
                interfaces = await console.command("show ip interface brief")
                running = await console.command("show running-config")
                result["devices"][name]["show_ip_interface_brief"] = interfaces
                result["devices"][name]["show_running_config"] = running
                if name.startswith("SW"):
                    output = await console.command("show spanning-tree vlan 1")
                    result["devices"][name]["show_spanning_tree"] = output
                    stp.append(output)
                else:
                    result["devices"][name]["interface_up"] = bool(re.search(r"FastEthernet0/0\s+1\.1\.1\.[123]\s+.*\bup\s+up\b", interfaces))
                    expected_match = re.search(r"^ip address (\S+) (\S+)", (lab / "commands" / (name + ".txt")).read_text(), re.M)
                    actual_match = re.search(r"^interface FastEthernet0/0\r?\n(?P<body>.*?)(?=^!|^interface|\Z)", running, re.M | re.S)
                    actual_address = re.search(r"^\s*ip address (\S+) (\S+)", actual_match["body"], re.M) if actual_match else None
                    expected = list(expected_match.groups()) if expected_match else None
                    actual = list(actual_address.groups()) if actual_address else None
                    result["devices"][name]["address_verification"] = {"expected": expected, "observed": actual, "pass": expected is not None and actual == expected and actual[1] == "255.0.0.0"}
            result["gates"]["pc_interfaces_up"] = all(result["devices"][name].get("interface_up", False) for name in devices if name.startswith("PC"))
            result["gates"]["pc_addresses_and_masks"] = all(result["devices"][name]["address_verification"]["pass"] for name in devices if name.startswith("PC"))
            result["gates"]["stp_forwarding_and_blocking"] = bool(re.search(r"\b(?:BLK|Blocking)\b", "\n".join(stp), re.I)) and bool(re.search(r"\b(?:FWD|Forwarding)\b", "\n".join(stp), re.I))
            addresses = {}
            for name in devices:
                if name.startswith("PC"):
                    match = re.search(r"^ip address (\S+) ", (lab / "commands" / (name + ".txt")).read_text(), re.M)
                    if not match:
                        raise RuntimeError("No address in " + name + " configuration")
                    addresses[name] = match[1]
            for source in addresses:
                for destination, address in addresses.items():
                    if source == destination:
                        continue
                    # First request allows ARP resolution; acceptance uses the second request.
                    warmup = await consoles[source].command("ping " + address)
                    for round_number in range(1, 4):
                        output = await consoles[source].command("ping " + address)
                        match = re.search(r"Success rate is (\d+) percent \((\d+)/(\d+)\)", output)
                        observed = list(map(int, match.groups())) if match else None
                        passed = observed == [100, 5, 5]
                        result["pings"].append({"source": source, "destination": destination, "address": address, "round": round_number, "expected": [100, 5, 5], "observed": observed, "pass": passed, "warmup_output": warmup, "output": output})
                        report(f"PING {source} -> {destination} round {round_number}: {observed} {'PASS' if passed else 'FAIL'}")
            result["gates"]["full_mesh_ping"] = len(result["pings"]) == 18 and all(item["pass"] for item in result["pings"])
            negative_address = "1.1.1.254"
            if negative_address in addresses.values():
                raise RuntimeError("Negative-control address is assigned in this topology")
            output = await consoles["PC1"].command("ping " + negative_address)
            match = re.search(r"Success rate is (\d+) percent \((\d+)/(\d+)\)", output)
            observed = list(map(int, match.groups())) if match else None
            result["negative_control"] = {"source": "PC1", "address": negative_address, "expected": [0, 0, 5], "observed": observed, "output": output}
            result["gates"]["negative_control_unassigned_host"] = observed == [0, 0, 5]
            report("Negative-control ping PC1 -> " + negative_address + ": " + str(observed))
        if all(result["gates"].values()):
            result["status"] = "READY"
    except asyncio.CancelledError:
        if not result["errors"]: result["errors"].append("运行被中断，未完整验收")
        report("FAIL: " + result["errors"][-1])
    except Exception as error:
        result["errors"].append(type(error).__name__ + ": " + str(error))
        report("FAIL: " + result["errors"][-1])
    finally:
        if disk_watch: disk_watch.cancel()
        for console in consoles.values():
            console.writer.close()
        if hv:
            for name in devices:
                try:
                    hv.command("vm stop " + name)
                except Exception as error:
                    result["errors"].append("cleanup " + name + ": " + str(error))
            hv.close()
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for handle in handles:
            handle.close()
        if result["errors"]:
            result["status"] = "NOT READY"
        result["finished_at"] = datetime.datetime.now().astimezone().isoformat()
        (evidence / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        report("RESULT: " + result["status"] + " " + str(evidence / "result.json"))
    return 0 if result["status"] == "READY" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["run"])
    parser.add_argument("experiment", nargs="?", default="实验1")
    parser.add_argument("--student-octet", type=int, choices=[161], default=161)
    arguments = parser.parse_args()
    raise SystemExit(asyncio.run(run(arguments)))
