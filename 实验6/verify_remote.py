#!/usr/bin/env python3
"""Collect real console output; no credentials or simulated response fixtures."""
import argparse
import asyncio
import datetime
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import telnetlib3
from generate import generate

ROOT = Path(__file__).resolve().parent
PROMPT = re.compile(r'(?:^|[\r\n])(?:[\w.@-]+[>#%]|VPCS\[\d+\]>|<[^\r\n]+>|\[[^\r\n]+\]|PC\d+>)\s*$')
ERROR = re.compile(r'%\s*(?:Invalid|Incomplete|Ambiguous)|Error:|syntax error|Unknown command|Unrecognized command', re.I)


class Console:
    def __init__(self, reader, writer, path):
        self.reader, self.writer = reader, writer
        self.log = path.open('w')

    async def command(self, command, timeout=40):
        self.log.write('\n>>> ' + command + '\n')
        self.writer.write(command + '\r\n')
        output = ''
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('命令超时: ' + command)
            chunk = await asyncio.wait_for(self.reader.read(4096), remaining)
            if not chunk:
                raise RuntimeError('console disconnected')
            self.log.write(chunk)
            self.log.flush()
            output += chunk
            if PROMPT.search(output):
                if ERROR.search(output):
                    raise RuntimeError('设备拒绝命令: ' + output[-1000:])
                return output

    def close(self):
        self.writer.close()
        self.log.close()


def ping_ok(output, kind):
    if kind == 'vpcs':
        return len(re.findall(r'icmp_seq=[1-5]\b.*\bttl=', output, re.I)) == 5
    raise ValueError('当前PC采集要求VPCS console')


async def run(args):
    plan = json.loads((ROOT / 'topology.json').read_text())
    _, pcs = generate(plan)
    endpoints = json.loads(args.endpoints.read_text())
    names = [f'R{i}' for i in range(1, 5)] + [p['name'] for p in pcs]
    missing = [n for n in names if not endpoints.get(n, {}).get('host')]
    if missing:
        print('NOT READY: 缺真实、已登录console端点: ' + ', '.join(missing))
        return 2
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    evidence = ROOT / 'evidence' / stamp
    evidence.mkdir(parents=True)
    report = {'status': 'NOT READY', 'scope': '真实三厂商4路由8PC', 'gates': {}, 'output': {},
              'plan_sha256': hashlib.sha256((ROOT / 'topology.json').read_bytes()).hexdigest()}
    consoles = {}
    try:
        for n in names:
            e = endpoints[n]
            if n.startswith('PC') and e.get('kind') != 'vpcs':
                raise ValueError(n + '需要kind=vpcs；Windows/Linux PC请另行采集原始ping记录')
            reader, writer = await asyncio.wait_for(telnetlib3.open_connection(e['host'], int(e['port']), encoding='utf8'), 20)
            c = consoles[n] = Console(reader, writer, evidence / (n + '.log'))
            await c.command('')
        for r in plan['routers']:
            name, v = f"R{r['id']}", r['vendor']
            commands = {'Cisco': ['terminal length 0', 'show version', 'show running-config', 'show ip ospf neighbor', 'show ip route ospf', 'show ip interface brief'],
                        'H3C': ['screen-length disable', 'display version', 'display current-configuration', 'display ospf peer', 'display ip routing-table protocol ospf', 'display ip interface brief'],
                        'Juniper': ['set cli screen-length 0', 'show version', 'show configuration | display set', 'show ospf neighbor', 'show route protocol ospf', 'show interfaces terse']}[v]
            result = {cmd: await consoles[name].command(cmd) for cmd in commands}
            report['output'][name] = result
            version, _, neighbors, routes, _ = list(result.values())[1:]
            report['gates'][name + '_vendor'] = bool(re.search({'Cisco': r'Cisco.*(?:IOS|Internetwork)', 'H3C': r'H3C|Comware', 'Juniper': r'JUNOS|Junos'}[v], version, re.I))
            # A broadcast LAN has two FULL neighbors on a DROTHER; the fourth peer can be 2WAY.
            report['gates'][name + '_neighbors'] = len(re.findall(r'\bFull\b', neighbors, re.I)) >= 2 and all(f'0.0.0.{i}' in neighbors for i in range(1, 5) if i != r['id'])
            report['gates'][name + '_learned_routes'] = all(f"{plan['prefix']}.{i}.0" in routes for i in range(1, 5) if i != r['id'])
        for pc in pcs:
            name = pc['name']
            c = consoles[name]
            result = {'show ip': await c.command('show ip')}
            report['gates'][name + '_address_gateway'] = pc['address'] in result['show ip'] and pc['gateway'] in result['show ip']
            for peer in pcs:
                if peer['name'] == name:
                    continue
                command = f"ping {peer['address']} -c 5"
                # Warm ARP first; second measurement must receive every actual response.
                await c.command(command)
                output = await c.command(command)
                result[command] = output
                report['gates'][name + '_to_' + peer['name']] = ping_ok(output, 'vpcs')
            report['output'][name] = result
        negative = await consoles['PC1'].command(f"ping {plan['prefix']}.4.253 -c 5")
        report['output']['negative_control'] = negative
        report['gates']['negative_control'] = not re.search(r'icmp_seq=\d+.*\bttl=', negative, re.I) and bool(re.search(r'timeout|unreachable|not reachable', negative, re.I))
        report['status'] = 'READY' if all(report['gates'].values()) else 'NOT READY'
    except Exception as exc:
        report['error'] = str(exc)
    finally:
        for c in consoles.values():
            c.close()
        (evidence / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(report['status'], evidence)
    return 0 if report['status'] == 'READY' else 1


if __name__ == '__main__':
    p = argparse.ArgumentParser(description='只读采集，事先手工登录并部署commands；不记录登录凭据。')
    p.add_argument('--endpoints', type=Path, default=ROOT / 'endpoints.example.json')
    sys.exit(asyncio.run(run(p.parse_args())))
