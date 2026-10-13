#!/usr/bin/env python3
"""Inspect actual Dynamips packet captures with tshark; never fabricate captures."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

FIELDS=['frame.number','frame.time_epoch','eth.src','eth.dst','arp.opcode','arp.src.proto_ipv4','arp.dst.proto_ipv4','arp.src.hw_mac','ip.src','ip.dst','ip.ttl','icmp.type','icmp.code','icmp.ident','icmp.seq']

def inspect(path):
    proc=subprocess.run(['tshark','-r',str(path),'-Y','arp or icmp','-T','fields','-E','occurrence=f',*[arg for f in FIELDS for arg in ['-e',f]]],text=True,capture_output=True,check=True)
    packets=[]
    for line in proc.stdout.splitlines():
        values=line.split('\t');packets.append(dict(zip(FIELDS,values)))
    return packets

def main(directory):
    if not shutil.which('tshark'):raise RuntimeError('tshark is required; install environment first')
    files=[p for p in directory.glob('*.pcap') if 'http' not in p.name]
    packets=[]
    for p in files:
        for row in inspect(p):row['capture']=p.name;packets.append(row)
    arp=[r for r in packets if r.get('arp.opcode')]
    icmp=[r for r in packets if r.get('icmp.type')]
    duplicate={r['arp.src.hw_mac'] for r in arp if r['arp.src.proto_ipv4']=='10.5.1.2' and r['arp.src.hw_mac']}
    gates={'actual_packet_captures':bool(files) and bool(packets),'arp_request':any(r['arp.opcode']=='1' for r in arp),'arp_reply':any(r['arp.opcode']=='2' for r in arp),'icmp_echo_request':any(r['icmp.type']=='8' for r in icmp),'icmp_echo_reply':any(r['icmp.type']=='0' for r in icmp),'icmp_time_exceeded':any(r['icmp.type']=='11' and r['icmp.code']=='0' for r in icmp),'icmp_destination_unreachable':any(r['icmp.type']=='3' for r in icmp),'duplicate_ip_two_macs':len(duplicate)>=2,'gratuitous_arp':any(r['arp.src.proto_ipv4']==r['arp.dst.proto_ipv4'] for r in arp)}
    # The same Echo ID/sequence on both LANs must preserve IPs while the router
    # decrements TTL and rewrites link-layer endpoints.
    groups={}
    for r in icmp:
        if r['icmp.type']=='8' and r['ip.src']=='10.5.1.2' and r['ip.dst']=='10.5.2.2':groups.setdefault((r['icmp.ident'],r['icmp.seq']),[]).append(r)
    pairs=[]
    for key,rows in groups.items():
        for a in rows:
            for b in rows:
                if a['capture']!=b['capture'] and a['ip.ttl'].isdigit() and b['ip.ttl'].isdigit() and int(a['ip.ttl'])==int(b['ip.ttl'])+1 and a['eth.src']!=b['eth.src'] and a['eth.dst']!=b['eth.dst']:pairs.append({'icmp_id_sequence':key,'before':a,'after':b})
    gates['routed_packet_ttl_and_mac']=bool(pairs)
    result={'status':'READY' if all(gates.values()) else 'NOT READY','gates':gates,'files':[str(p) for p in files],'duplicate_ip_macs':sorted(duplicate),'routed_packet_examples':pairs[:3],'packets':packets}
    (directory/'packet-analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='packets'},ensure_ascii=False,indent=2))
    return 0 if result['status']=='READY' else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path,nargs='?')
    parser.add_argument('--evidence',type=Path)
    args=parser.parse_args()
    directory=args.evidence or args.directory
    if directory is None:parser.error('evidence directory is required')
    raise SystemExit(main(directory))
