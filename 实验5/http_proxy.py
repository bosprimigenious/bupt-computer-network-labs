#!/usr/bin/env python3
"""Real localhost HTTP origin/proxy/client; capture with tcpdump when permitted.
No privileges are changed, and no synthetic TCP packets/pcap are generated.
"""
import argparse
import datetime
import http.client
import http.server
import json
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit


def run(destination, require_pcap=False):
    destination.mkdir(parents=True, exist_ok=True)
    events = []
    lock = threading.Lock()
    def record(kind, **fields):
        with lock:
            events.append({'time': time.time(), 'event': kind, **fields})
    class Origin(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            record('origin_received', client=list(self.client_address), local=list(self.connection.getsockname()), request_line=self.requestline, headers=dict(self.headers))
            body = b'our-network-lab5-origin\n'
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('X-Lab-Origin', 'network-lab5')
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args): pass
    origin = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Origin)
    origin_port = origin.server_address[1]
    class Proxy(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            target = urlsplit(self.path)
            record('proxy_received', client=list(self.client_address), local=list(self.connection.getsockname()), request_line=self.requestline, headers=dict(self.headers))
            if target.hostname != '127.0.0.1' or target.port != origin_port:
                self.send_error(403, 'Only our local lab origin is allowed')
                return
            conn = http.client.HTTPConnection('127.0.0.1', origin_port, timeout=5)
            try:
                conn.request('GET', target.path or '/', headers={'Host': target.netloc, 'Via': '1.1 our-lab5-proxy', 'Connection': 'close'})
                response = conn.getresponse()
                body = response.read()
                record('proxy_forwarded', origin_port=origin_port, status=response.status, upstream_request_line='GET '+(target.path or '/')+' HTTP/1.1', upstream_headers={'Host':target.netloc,'Via':'1.1 our-lab5-proxy'}, response_body=body.decode())
                self.send_response(response.status)
                self.send_header('Content-Type', 'text/plain')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Via', '1.1 our-lab5-proxy')
                self.end_headers()
                self.wfile.write(body)
            finally: conn.close()
        def log_message(self, *args): pass
    proxy = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
    proxy_port = proxy.server_address[1]
    for server in (origin, proxy): threading.Thread(target=server.serve_forever, daemon=True).start()
    result = {'status':'NOT READY','gates':{},'origin_port':origin_port,'proxy_port':proxy_port,'capture_errors':[]}
    capture = None
    log = (destination/'tcpdump.log').open('w')
    tcpdump = shutil.which('tcpdump')
    try:
        if tcpdump:
            capture = subprocess.Popen([tcpdump,'-i','lo0','-n','-U','-s','0','-w',str(destination/'http-proxy.pcap'),'tcp and (port '+str(origin_port)+' or port '+str(proxy_port)+')'],stdout=log,stderr=subprocess.STDOUT)
            time.sleep(.4)
            if capture.poll() is not None:
                result['capture_errors'].append('tcpdump exited with '+str(capture.returncode)+'; see tcpdump.log')
                capture = None
        else: result['capture_errors'].append('tcpdump unavailable')
        client = http.client.HTTPConnection('127.0.0.1', proxy_port, timeout=5)
        target='http://127.0.0.1:'+str(origin_port)+'/course/lab5'
        client.request('GET',target,headers={'Host':'127.0.0.1:'+str(origin_port),'Connection':'close'})
        response=client.getresponse(); body=response.read(); headers=dict(response.getheaders())
        record('client_received',request_target=target,status=response.status,headers=headers,body=body.decode())
        client.close()
        result['gates']['real_http_through_proxy']=response.status==200 and body==b'our-network-lab5-origin\n' and headers.get('Via')=='1.1 our-lab5-proxy'
        result['gates']['absolute_target_to_origin_form']=any(e['event']=='proxy_received' and e['request_line'].startswith('GET http://') for e in events) and any(e['event']=='origin_received' and e['request_line']=='GET /course/lab5 HTTP/1.1' and e['headers'].get('Via')=='1.1 our-lab5-proxy' for e in events)
        proxy_events=[e for e in events if e['event']=='proxy_received']
        origin_events=[e for e in events if e['event']=='origin_received']
        result['gates']['two_real_tcp_connections']=bool(proxy_events and origin_events and proxy_events[0]['client'][1] != origin_events[0]['client'][1] and proxy_events[0]['local'][1]==proxy_port and origin_events[0]['local'][1]==origin_port)
        kinds=[e['event'] for e in events]
        result['gates']['request_response_order']=kinds==['proxy_received','origin_received','proxy_forwarded','client_received']
        time.sleep(.4)
    except Exception as error:
        result['errors']=[type(error).__name__+': '+str(error)]
    finally:
        if capture:
            capture.send_signal(2)
            try:capture.wait(timeout=5)
            except subprocess.TimeoutExpired:capture.kill();capture.wait()
        log.close()
        for server in (proxy,origin):server.shutdown();server.server_close()
        pcap=destination/'http-proxy.pcap'
        result['optional_capture']={'real_tcp_pcap':pcap.is_file() and pcap.stat().st_size>24,'reason':'PPT第41页要求分析HTTP代理流程；TCPpcap为可选附加证据。真实ARP/ICMP抓包另由Dynamips完成。'}
        result['functional_status']='READY' if len(result['gates'])==4 and all(result['gates'].values()) else 'NOT READY'
        result['status']=result['functional_status']
        if require_pcap and not result['optional_capture']['real_tcp_pcap']:result['status']='NOT READY'
        (destination/'http-events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2)+'\n')
        (destination/'http-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if (result['status']=='READY' if require_pcap else result['functional_status']=='READY') else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output','--evidence',type=Path,default=Path(__file__).parent/'evidence'/('http-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')))
    parser.add_argument('--require-pcap',action='store_true')
    args=parser.parse_args()
    raise SystemExit(run(args.output,args.require_pcap))
