"""Evidence-driven multi-stage acceptance for our course experiments."""
import asyncio
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

async def wait(seconds):
    for elapsed in range(0, seconds, 5):
        await asyncio.sleep(min(5, seconds-elapsed))
        print(f'Convergence {min(elapsed+5,seconds)}/{seconds}s', flush=True)

async def exercise(spec, consoles, result, evidence):
    result['phases'] = []
    await wait(spec.get('startup_wait', 45))
    for phase in spec['phases']:
        print('PHASE: '+phase['name'], flush=True)
        record = {'name':phase['name'], 'started_epoch':time.time(), 'commands':[], 'checks':[], 'pings':[]}
        result['phases'].append(record)
        for name, commands in phase.get('commands', {}).items():
            for command in commands:
                if isinstance(command,dict):
                    output=await consoles[name].command(command['command'],timeout=command.get('timeout',120),interrupt_after=command.get('interrupt_after'))
                else:
                    output=await consoles[name].command(command)
                record['commands'].append({'device':name,'command':command,'output':output})
        await wait(phase.get('wait_seconds',0))
        if phase.get('convergence'):
            deadline=time.monotonic()+phase.get('convergence_timeout',150)
            record['convergence_attempts']=[]
            settled=False
            while time.monotonic()<deadline:
                attempt=[]
                for check in phase['convergence']:
                    output=await consoles[check['device']].command(check['command'])
                    passed=all(t in output for t in check.get('contains',[])) and (bool(re.search(check['regex'],output,re.M|re.S)) if 'regex' in check else True)
                    attempt.append({**check,'output':output,'pass':passed})
                record['convergence_attempts'].append(attempt)
                if all(c['pass'] for c in attempt):
                    settled=True
                    break
                print('Waiting for observed routing convergence: '+phase['name'],flush=True)
                await asyncio.sleep(5)
            record['checks'].append({'convergence':phase['name'],'pass':settled,'attempts':len(record['convergence_attempts'])})
        for ping in phase.get('pings',[]):
            console=consoles[ping['source']]
            command=ping.get('command','ping '+ping['target'])
            warmup=await console.command(command)
            for n in range(ping.get('rounds',3)):
                output=await console.command(command)
                match=re.search(r'Success rate is (\d+) percent \((\d+)/(\d+)\)',output)
                observed=list(map(int,match.groups())) if match else None
                success=ping.get('success',True)
                expected=[100,5,5] if success else [0,0,5]
                passed=observed==expected
                item={**ping,'round':n+1,'expected':expected,'observed':observed,'output':output,'warmup_output':warmup,'pass':passed}
                record['pings'].append(item);result['pings'].append(item)
                print(f"PING {ping['source']} -> {ping['target']}: {observed} {passed}",flush=True)
        for check in phase.get('checks',[]):
            output=await consoles[check['device']].command(check['command'])
            passed=all(text in output for text in check.get('contains',[]))
            if 'regex' in check: passed = passed and bool(re.search(check['regex'],output,re.M|re.S))
            if 'not_regex' in check: passed = passed and not bool(re.search(check['not_regex'],output,re.M|re.S))
            record['checks'].append({**check,'output':output,'pass':passed})
            print(f"CHECK {check['device']} {check['command']}: {passed}",flush=True)
        for action in phase.get('interactive',[]):
            console=consoles[action['device']]
            console.writer.write(action['input'].replace('\\n','\r\n')+'\r\n')
            output=await console.until_prompt(timeout=action.get('timeout',40))
            passed=bool(re.search(action['regex'],output,re.M|re.S))
            record['checks'].append({**action,'output':output,'pass':passed})
        record['snapshots']={}
        for name, commands in spec.get('snapshots',{}).items():
            record['snapshots'][name]={}
            for command in commands:
                record['snapshots'][name][command]=await consoles[name].command(command)
        record['finished_epoch']=time.time()
        result['gates']['phase_'+phase['name']]=bool(record['pings'] or record['checks']) and all(x['pass'] for x in record['pings']+record['checks'])
    for name, commands in spec.get('snapshots',{}).items():
        result['devices'][name]['snapshots']={}
        for command in commands:
            result['devices'][name]['snapshots'][command]=await consoles[name].command(command)

async def run_hooks(spec, result, evidence):
    for hook in spec.get('hooks',[]):
        command=[str(Path(__file__).resolve().parent/'.venv/bin/python'),str(Path(spec['_lab_path'])/hook['script']),'--evidence',str(evidence)]
        proc=await asyncio.create_subprocess_exec(*command,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT)
        out,_=await proc.communicate()
        result.setdefault('hooks',[]).append({'command':command,'exit_code':proc.returncode,'output':out.decode(errors='replace')})
        print(out.decode(errors='replace'),flush=True)
        result['gates']['hook_'+hook['script']]=proc.returncode==0

def verify_captures(spec,captures,result):
    tool=shutil.which('tshark')
    checks=[]
    paths={c['name']:c['path'] for c in captures}
    requests=list(spec.get('packet_checks',[]))
    for phase,record in zip(spec.get('phases',[]), result.get('phases',[])):
        for check in phase.get('packet_checks',[]):
            requests.append({**check,'phase':phase['name'],'filter':f"({check['filter']}) && frame.time_epoch >= {record['started_epoch']} && frame.time_epoch <= {record['finished_epoch']}"})
    for check in requests:
        path=paths[check['capture']]
        if tool:
            proc=subprocess.run([tool,'-r',path,'-Y',check['filter'],'-T','fields','-e','frame.number'],capture_output=True,text=True,timeout=45)
            packets=[s for s in proc.stdout.splitlines() if s.strip()]
            passed=proc.returncode==0 and len(packets)>=check.get('min_packets',1)
            item={**check,'path':path,'packets':len(packets),'pass':passed,'exit_code':proc.returncode,'stderr':proc.stderr}
        else: item={**check,'path':path,'pass':False,'error':'tshark unavailable'}
        checks.append(item)
        print('PCAP '+check['filter']+': '+str(item),flush=True)
    result['packet_checks']=checks
    if captures: result['gates']['real_capture_files']=all(Path(c['path']).is_file() and Path(c['path']).stat().st_size>24 for c in captures)
    if checks: result['gates']['packet_analysis']=all(c['pass'] for c in checks)
