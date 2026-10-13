#!/usr/bin/env python3
"""Run the Cisco rehearsal and independently gate the real three-vendor lab."""
import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--endpoints',type=Path,default=ROOT/'endpoints.example.json')
p.add_argument('--skip-rehearsal',action='store_true')
a=p.parse_args()
evidence=ROOT/'evidence'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
evidence.mkdir(parents=True)
report={'status':'NOT READY','scope':'实验6真实Cisco/Juniper/H3C互联','gates':{},'steps':[]}
steps=[('generate',[sys.executable,str(ROOT/'generate.py')])]
if not a.skip_rehearsal:steps.append(('cisco_rehearsal',[sys.executable,str(ROOT.parent/'_环境/lab.py'),'run','实验6/cisco-proxy']))
steps.append(('real_three_vendor',[sys.executable,str(ROOT/'verify_remote.py'),'--endpoints',str(a.endpoints)]))
for name,command in steps:
 with (evidence/(name+'.log')).open('w') as log:
  process=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
 report['steps'].append({'name':name,'command':command,'exit_code':process.returncode,'log':str(evidence/(name+'.log'))})
 report['gates'][name]=process.returncode==0
 print(name,process.returncode,flush=True)
if all(report['gates'].values()):report['status']='READY'
(evidence/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(report['status'],evidence/'result.json')
raise SystemExit(0 if report['status']=='READY' else 1)
