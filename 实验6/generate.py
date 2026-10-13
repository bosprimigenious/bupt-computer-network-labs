#!/usr/bin/env python3
"""Our multivendor generator, based on agicy MIT lab6's data/template approach."""
import argparse
import ipaddress
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def generate(plan):
    prefix = str(ipaddress.IPv4Network(plan['prefix'] + '.0.0/16')).split('/')[0].rsplit('.', 2)[0]
    routers = plan['routers']
    if len(routers) != 4 or {r['vendor'] for r in routers} != {'Cisco', 'Juniper', 'H3C'}:
        raise ValueError('必须包含4台路由器和Cisco、Juniper、H3C三厂商')
    if sorted(r['id'] for r in routers) != [1, 2, 3, 4]:
        raise ValueError('路由器id必须为1、2、3、4')
    files = {}
    for r in routers:
        i, v = r['id'], r['vendor']
        a, b = r['transit_interface'], r['lan_interface']
        if a == b or not all(re.fullmatch(r'[A-Za-z0-9/_.-]+', x) for x in (a, b)):
            raise ValueError('接口不合法或重复')
        transit, lan, rid = f'{prefix}.255.{i}', f'{prefix}.{i}.254', f'0.0.0.{i}'
        if v == 'Cisco':
            lines = ['enable', 'configure terminal', f'hostname R{i}',
                     f'interface {a}', f'ip address {transit} 255.255.255.0', 'no shutdown', 'exit',
                     f'interface {b}', f'ip address {lan} 255.255.255.0', 'no shutdown', 'exit',
                     'router ospf 6', f'router-id {rid}', f'network {prefix}.255.0 0.0.0.255 area 0',
                     f'network {prefix}.{i}.0 0.0.0.255 area 0', f'passive-interface {b}', 'end']
        elif v == 'H3C':
            lines = ['system-view', f'sysname R{i}', f'interface {a}',
                     f'ip address {transit} 255.255.255.0', 'undo shutdown', 'quit', f'interface {b}',
                     f'ip address {lan} 255.255.255.0', 'undo shutdown', 'quit', f'ospf 6 router-id {rid}',
                     f'silent-interface {b}', 'area 0.0.0.0', f'network {prefix}.255.0 0.0.0.255',
                     f'network {prefix}.{i}.0 0.0.0.255', 'quit', 'quit', 'quit']
        else:
            lines = ['configure', f'set system host-name R{i}', f'set routing-options router-id {rid}',
                     f'set interfaces {a} unit 0 family inet address {transit}/24',
                     f'set interfaces {b} unit 0 family inet address {lan}/24',
                     f'set protocols ospf area 0.0.0.0 interface {a}.0',
                     f'set protocols ospf area 0.0.0.0 interface {b}.0 passive']
            if r.get('srx_security', False):
                lines += [f'set security zones security-zone LAB interfaces {a}.0',
                          f'set security zones security-zone LAB interfaces {b}.0',
                          'set security zones security-zone LAB host-inbound-traffic system-services ping',
                          'set security zones security-zone LAB host-inbound-traffic protocols ospf',
                          'set security policies from-zone LAB to-zone LAB policy LAB-PERMIT match source-address any',
                          'set security policies from-zone LAB to-zone LAB policy LAB-PERMIT match destination-address any',
                          'set security policies from-zone LAB to-zone LAB policy LAB-PERMIT match application any',
                          'set security policies from-zone LAB to-zone LAB policy LAB-PERMIT then permit']
            lines += ['commit check', 'commit', 'exit']
        files[f'R{i}.txt'] = '\n'.join(lines) + '\n'
    pcs = []
    for i in range(1, 5):
        for j in (1, 2):
            name = f'PC{(i-1)*2+j}'
            pcs.append({'name': name, 'address': f'{prefix}.{i}.{j}', 'gateway': f'{prefix}.{i}.254', 'lan': i})
            files[name + '.txt'] = f'ip {prefix}.{i}.{j}/24 {prefix}.{i}.254\n'
    return files, pcs


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--plan', type=Path, default=ROOT / 'topology.json')
    p.add_argument('--output', type=Path, default=ROOT / 'commands')
    args = p.parse_args()
    plan = json.loads(args.plan.read_text())
    files, pcs = generate(plan)
    args.output.mkdir(parents=True, exist_ok=True)
    for name, value in files.items():
        target = args.output / name
        if target.exists() and target.read_text() != value:
            raise FileExistsError(f'{target}已存在不同内容；先备份再显式删除旧文件')
        target.write_text(value)
    print(json.dumps({'generated': list(files), 'pcs': pcs, 'runtime_status': 'NOT READY'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
