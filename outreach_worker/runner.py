#!/usr/bin/env python3
"""Active Mac-session daemon checks every minute; CRM leases 30-minute outreach runs."""
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from client import request

ROOT=Path(__file__).resolve().parent
LOCAL=Path.home()/'.config/bmt-outreach-system'

def tick():
    LOCAL.mkdir(parents=True,exist_ok=True)
    with (LOCAL/'run.lock').open('w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        request('POST',{'op':'heartbeat','state':'Mac worker connected'})
        claim=request('POST',{'op':'claim'})
        if not claim.get('run'):return
        ident=claim['run'];folder=LOCAL/'runs'/ident;folder.mkdir(parents=True);os.chmod(folder,0o700)
        cfg=json.loads((LOCAL/'config.json').read_text())
        codex=cfg['codex_path']
        prompt=(ROOT/'workflow.txt').read_text().replace('{{RUN_ID}}',ident).replace('{{CLIENT}}',str(ROOT/'client.py')).replace('{{RUN_DIR}}',str(folder))
        probe=LOCAL/'diagnostic-once.txt'
        if probe.exists():
            prompt=probe.read_text();probe.unlink()
        (folder/'prompt.txt').write_text(prompt)
        command=[codex,'-a','never','-c','mcp_servers.playwright.enabled=false','-c','mcp_servers.mobile-next.enabled=false',
                 'exec','--ephemeral','--json','-s','danger-full-access','--skip-git-repo-check','-C',str(ROOT),'-o',str(folder/'summary.txt'),'-']
        summary='Run ended without a summary.'
        try:
            with (folder/'events.jsonl').open('w') as log:
                os.chmod(folder/'events.jsonl',0o600)
                process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                try:process.communicate(prompt.encode(),timeout=1100)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGTERM)
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
                    summary='Run reached its time limit; review any unconfirmed send before continuing.'
                if (folder/'summary.txt').exists():summary=(folder/'summary.txt').read_text()[-3500:]
                if process.returncode and summary=='Run ended without a summary.':summary='Worker exited with an error; local run log saved.'
        except Exception as e:summary='Worker stopped: '+str(e)
        if 'process' in locals() and process.returncode:
            try:request('POST',{'op':'attention','reason':'Worker exited unexpectedly; inspect local run log.'})
            except Exception:pass
        try:request('POST',{'op':'finish','run_id':ident,'summary':summary})
        except Exception:pass # A completed/expired lease is already durable in the CRM.

if __name__=='__main__':
    repeat='--daemon' in sys.argv
    while True:
        try:tick()
        except Exception as e:
            print(time.strftime('%Y-%m-%d %H:%M:%S')+' outreach worker: '+str(e),file=sys.stderr,flush=True)
            if not repeat:raise SystemExit(1)
        if not repeat:break
        time.sleep(60)
