#!/usr/bin/env python3
"""Recheck recorded raw outputs, config fingerprints and actual packet captures."""
import hashlib
import json
import re
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def audit(lab):
    files=sorted((lab/'evidence').glob('*/result.json'))
    if not files:return {'experiment':str(lab.relative_to(ROOT)),'status':'NOT READY','reason':'无运行证据'}
    p=files[-1];r=json.loads(p.read_text());errors=[]
    if r['status']!='READY' or not r['gates'] or not all(r['gates'].values()) or r.get('errors'):errors.append('运行门禁未全过')
    if digest(Path(r['topology']))!=r['sha256']['topology']:errors.append('拓扑已变化')
    for name,value in r['sha256']['commands'].items():
        if digest(lab/'commands'/(name+'.txt'))!=value:errors.append('设备命令已变化: '+name)
    for path,value in r['sha256']['ios'].items():
        if digest(Path(path))!=value:errors.append('IOS已变化: '+path)
    spec=lab/'specification.json'
    if spec.exists() and digest(spec)!=r.get('specification_sha256'):errors.append('验收spec已变化')
    for ping in r['pings']:
        m=re.search(r'Success rate is (\d+) percent \((\d+)/(\d+)\)',ping['output'])
        if not m or list(map(int,m.groups()))!=ping['expected']:errors.append('原始ping未符合预期')
    if 'negative_control' in r:
        n=r['negative_control'];m=re.search(r'Success rate is (\d+) percent \((\d+)/(\d+)\)',n['output'])
        if not m or list(map(int,m.groups()))!=n['expected']:errors.append('负对照未符合预期')
    for phase in r.get('phases',[]):
        for check in phase['checks']:
            if 'output' not in check:continue
            output=check['output']
            ok=all(t in output for t in check.get('contains',[]))
            if 'regex' in check:ok=ok and bool(re.search(check['regex'],output,re.M|re.S))
            if 'not_regex' in check:ok=ok and not bool(re.search(check['not_regex'],output,re.M|re.S))
            if not ok:errors.append('原始show门禁失败: '+phase['name'])
    for check in r.get('packet_checks',[]):
        proc=subprocess.run(['tshark','-r',check['path'],'-Y',check['filter'],'-T','fields','-e','frame.number'],capture_output=True,text=True,timeout=45)
        if proc.returncode or len(proc.stdout.splitlines())<check.get('min_packets',1):errors.append('重新解码pcap失败: '+check['filter'])
    if lab.name=='实验5':
        a=json.loads((p.parent/'packet-analysis.json').read_text());h=json.loads((p.parent/'http-result.json').read_text())
        if a['status']!='READY' or not all(a['gates'].values()):errors.append('报文全过程分析失败')
        if h['functional_status']!='READY' or not all(h['gates'].values()):errors.append('HTTP流程失败')
    return {'experiment':str(lab.relative_to(ROOT)),'status':'NOT READY' if errors else 'READY','errors':errors,'evidence':str(p.relative_to(ROOT)),'pings':len(r['pings']),'phases':len(r.get('phases',[])),'pcap_checks':len(r.get('packet_checks',[]))}

def main():
    out=[]
    for i in range(1,6):
        try:item=audit(ROOT/f'实验{i}')
        except Exception as e:item={'experiment':f'实验{i}','status':'NOT READY','error':str(e)}
        out.append(item)
    proxy=audit(ROOT/'实验6/cisco-proxy')
    real=sorted((ROOT/'实验6/evidence').glob('*/result.json'))
    r=json.loads(real[-1].read_text()) if real else {}
    out.append({'experiment':'实验6','status':r.get('status','NOT READY'),'reason':'需真实Cisco/Juniper/H3C及PC端点；Cisco预演不代替三厂商验收','cisco_rehearsal':proxy,'evidence':str(real[-1].relative_to(ROOT)) if real else None})
    result={'status':'READY' if all(x['status']=='READY' for x in out) else 'NOT READY','experiments':out}
    (ROOT/'验收记录').mkdir(exist_ok=True)
    (ROOT/'验收记录/汇总.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['status']=='READY' else 1
if __name__=='__main__':raise SystemExit(main())
