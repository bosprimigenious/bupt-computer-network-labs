#!/usr/bin/env python3
"""Generate a factual protocol report from a finished run; never invent packet/screenshots."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def packets(tshark, path, display_filter):
    proc = subprocess.run([tshark, '-r', str(path), '-Y', display_filter,
                           '-T', 'fields', '-e', 'frame.number', '-e', 'frame.time_epoch',
                           '-e', 'ip.src', '-e', 'ip.dst', '-e', '_ws.col.Info'],
                          capture_output=True, text=True, timeout=60)
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip())
    return [line for line in proc.stdout.splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', required=True, type=Path)
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    lab = Path(__file__).resolve().parent
    if lab / 'evidence' not in evidence.parents:
        raise ValueError('Evidence must be a run directory within this experiment.')
    result = json.loads((evidence / 'result.json').read_text())
    tshark = shutil.which('tshark')
    if not tshark:
        raise RuntimeError('tshark missing; packet observations cannot be generated.')
    sources = {item['name']: Path(item['path']) for item in result.get('captures', [])}
    expected = ['R1-R2-protocols', 'R1-R3-failover', 'PC1-LAN']
    for name in expected:
        if name not in sources or not sources[name].is_file():
            raise ValueError('Missing actual capture: '+name)
    lines = ['# 实验3：真实运行与协议流程证据', '',
             f'生成时间：{datetime.datetime.now().astimezone().isoformat()}',
             f'运行目录：`{evidence.name}`；运行器状态：**{result["status"]}**。',
             '本文件只整理当前result.json和pcap；运行器状态不自动代表个人报告、课堂截图均已完成。', '',
             f'学号第二字节：{result.get("student_octet", "未记录")}；规范SHA256：`{result.get("specification_sha256", "未记录")}`。', '',
             '## 逐阶段实际结果', '',
             '| 阶段 | ping通过/总数 | 检查通过/总数 | 阶段门禁 |',
             '|---|---:|---:|---|']
    for phase in result.get('phases', []):
        ping = phase.get('pings', []); checks = phase.get('checks', [])
        passed = result.get('gates', {}).get('phase_'+phase['name'], False)
        lines.append(f'| {phase["name"]} | {sum(bool(x.get("pass")) for x in ping)}/{len(ping)} | '
                     f'{sum(bool(x.get("pass")) for x in checks)}/{len(checks)} | {passed} |')
    lines += ['', '静态下一跳与出接口阶段保留终端及路由器ARP/路由表；'
              '出接口路由在以太网上会尝试解析远端目的IP，能通时依赖邻接路由器proxy ARP。'
              'RIP阶段记录水平分割启用、禁用，以及同一链路关闭、恢复。'
              'OSPF阶段记录广播、点对点、链路关闭和恢复。请从下方真实阶段报文比较消息方向、数量和字段，不能把整场总包数当成每阶段证明。', '',
              '## 全场抓包核对', '',
              '| 抓包 | 大小 | SHA256 |', '|---|---:|---|']
    for name, path in sources.items():
        lines.append(f'| {name}.pcap | {path.stat().st_size} | `{digest(path)}` |')
    filters = [('RIP更新', 'rip'), ('OSPF Hello', 'ospf.msg == 1'),
               ('OSPF Database Description', 'ospf.msg == 2'), ('OSPF Link State Request', 'ospf.msg == 3'),
               ('OSPF Link State Update', 'ospf.msg == 4'), ('OSPF Link State Ack', 'ospf.msg == 5')]
    lines += ['', '| 消息 | 实际包数 | 最早帧编号 |', '|---|---:|---|']
    observations = {}
    for label, filt in filters:
        records = packets(tshark, sources['R1-R2-protocols'], filt)
        observations[label] = records
        frames = ', '.join(x.split('\t')[0] for x in records[:8]) or '未捕获'
        lines.append(f'| {label} | {len(records)} | {frames} |')
    lines += ['', '如果Link State Request包数为0，本次没有该消息的抓包证据。'
              'LS Request用于请求摘要中对端拥有而本机缺少或较旧的LSA；其出现依赖数据库差异，'
              '仅凭0包不能确定具体未出现原因，也不能把它补画成真实报文。'
              '数据库同步需结合DD内容、LSU内容和实际show ip ospf database输出分析。', '',
              '## 分阶段报文', '']
    for phase in result.get('phases', []):
        start, end = phase.get('started_epoch'), phase.get('finished_epoch')
        lines += [f'### {phase["name"]}', '']
        if start is None or end is None:
            lines += ['该运行未记录完整阶段时间边界，无法可靠分阶段归属pcap；此项为证据缺口。', '']
        else:
            bound = f'frame.time_epoch >= {start:.6f} && frame.time_epoch <= {end:.6f}'
            filt = 'rip' if phase['name'].startswith('rip') else 'ospf' if phase['name'].startswith('ospf') else 'arp || icmp'
            records = packets(tshark, sources['R1-R2-protocols'] if filt in ('rip', 'ospf') else sources['PC1-LAN'],
                              f'({filt}) && ({bound})')
            lines += [f'实际时间窗：{start:.6f}～{end:.6f}，相关报文数：{len(records)}。', '',
                      '前12条：帧编号、时间、源IP、目的IP、解码摘要。', '', '```text']
            lines += records[:12] or ['未捕获对应报文；不能把其他阶段报文代入。']
            lines += ['```', '']
        useful = []
        for item in phase.get('checks', []):
            command = item.get('command', '')
            if any(word in command for word in ['ospf', 'ip route', 'ip arp', 'ip interface']):
                useful.append((item['device'], command, item.get('output', '')))
        for device, snapshots in phase.get('snapshots', {}).items():
            for command, output in snapshots.items():
                if any(word in command for word in ['ospf database', 'ospf neighbor', 'ospf interface']):
                    useful.append((device, command, output))
        for device, command, output in useful:
            lines += [f'实际输出：{device} / `{command}`', '', '```text', output.rstrip(), '```', '']
    lines += ['## 未替代的提交要求', '',
              '本文件没有伪造截图。现场验收应打开本次console日志和pcap，并自行截取所需界面。'
              '水平分割对比需要检查RIP条目是否向接收接口回送；'
              'OSPF广播/点对点对比需要检查邻居状态、DR/BDR与发送对象。'
              '报文数、ping结果和路由表提供证据，但不能自动写成未核对的协议因果结论。']
    output = evidence / 'protocol-report.md'
    output.write_text('\n'.join(lines)+'\n')
    print(output)


if __name__ == '__main__':
    main()
