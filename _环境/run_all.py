#!/usr/bin/env python3
"""Sequentially run every experiment and fail closed on any missing gate."""
import datetime
import json
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
evidence=ROOT/'验收记录'/stamp
evidence.mkdir(parents=True)
result={'status':'NOT READY','experiments':[]}
for i in range(1,7):
 name=f'实验{i}'
 logpath=evidence/(name+'.log')
 with logpath.open('w') as log:
  proc=subprocess.run(['sh',str(ROOT/'run.sh'),name],stdout=log,stderr=subprocess.STDOUT)
 item={'experiment':name,'exit_code':proc.returncode,'status':'READY' if proc.returncode==0 else 'NOT READY','log':str(logpath)}
 result['experiments'].append(item)
 print(name,item['status'],logpath,flush=True)
 (evidence/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
if len(result['experiments'])==6 and all(r['status']=='READY' for r in result['experiments']):result['status']='READY'
(evidence/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print('ALL:',result['status'],evidence/'result.json')
raise SystemExit(0 if result['status']=='READY' else 1)
