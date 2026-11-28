#!/usr/bin/env python3
"""Active Mac-session daemon checks every minute; CRM leases hourly research and 15-minute inbox checks."""
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

def maintain_run(process,prompt,timeout=1100,heartbeat_seconds=60):
    """Keep liveness current while communicate waits for the AI/browser child."""
    deadline=time.monotonic()+timeout
    payload=prompt.encode()
    while True:
        remaining=deadline-time.monotonic()
        if remaining<=0:raise subprocess.TimeoutExpired(process.args,timeout)
        try:
            process.communicate(payload,timeout=min(heartbeat_seconds,remaining))
            return
        except subprocess.TimeoutExpired:
            payload=None
            if time.monotonic()>=deadline:raise
            try:request('POST',{'op':'heartbeat','state':'AI worker active: checking replies and researching'})
            except Exception as error:print('Outreach run heartbeat failed: '+str(error),file=sys.stderr,flush=True)


def prepare_prompt(template,claim):
    mode=claim.get('mode','research')
    if mode=='check':
        return ('READ-ONLY MANUAL DM CHECK. No messages, replies, cold outreach, purchases or scheduling. Do not enable automation. Use only native cua_repl, one existing tab per Facebook/Instagram/Skool. Preserve drafts. '
          'Read the CRM inbox with the configured client authentication at /api/outreach-inbox (public GET); also read client.py get for channel access/issues. Check every open tracked conversation, including manually contacted legacy leads. CRM lead notes have conversation/profile links. Read the live thread, verify company and speaker. '
          'For each successfully inspected lead, post through client.py op=inbox-check-result, run_id={{RUN_ID}}, lead_id, channel Facebook/Instagram/Skool, source_url (verified thread/profile), proof (what was actually checked), and messages (array of NEW inbound messages only, each text, classification Interested/Booking requested/Question/Not interested/Auto-reply/Other and external_key from stable platform identity where available). Do not record our outgoing messages as inbound. Empty messages is valid after an actual check. Duplicate checks must not duplicate replies. '
          'Do not mark a failed/unreadable thread checked. Log access issues through existing channel-issue workflow, leave backlog explicit. Finish with checked count/new replies/unreachable conversations. Never claim all checked when time expires. Stop after {{WORK_MINUTES}} minutes. '
          'Read the workflow below for client command, run ID and platform guardrails; its sending/reply instructions are overridden by this read-only mode.\n'+template).replace('{{WORK_MINUTES}}',str(claim.get('work_minutes',12))).replace('{{RUN_ID}}',claim.get('run',''))
    if mode=='replies':
        start=template.index('\nWORKFLOW\n');end=template.index('\nREPLY HANDLING',start)
        template=template[:start]+template[end:]
        instructions='INBOX ONLY: Read CRM status and enabled channels. Inspect enabled inboxes for relevant new advertising replies, then every open tracked company conversation, prioritizing unanswered messages and oldest last_thread_check. Handle relevant inbound and meeting/human handoffs, log actual thread checks and remaining backlog, then finish. Do not discover new prospects, add research/sources/candidates, or send cold introductions. The server enforces this separation. '
    else:
        instructions='RESEARCH: Reply checks first, then company-first discovery. During longer research, pause at safe checkpoints about every 15 minutes to recheck relevant inboxes before continuing. Never interrupt an unresolved outbound or unsaved draft. '
    return 'RUN MODE: '+mode+'\n'+instructions+'\n'+template.replace('{{WORK_MINUTES}}',str(claim.get('work_minutes',16)))


def tick():
    LOCAL.mkdir(parents=True,exist_ok=True)
    with (LOCAL/'run.lock').open('w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        request('POST',{'op':'heartbeat','state':'Mac worker connected'})
        cfg=json.loads((LOCAL/'config.json').read_text())
        if cfg.get('booked_research'):
            from booked import run_booked
            if run_booked(ROOT,LOCAL,request):return
        claim=request('POST',{'op':'claim'})
        if not claim.get('run'):return
        ident=claim['run'];folder=LOCAL/'runs'/ident;folder.mkdir(parents=True);os.chmod(folder,0o700)
        cfg=json.loads((LOCAL/'config.json').read_text())
        codex=cfg['codex_path']
        prompt=(ROOT/'workflow.txt').read_text().replace('{{RUN_ID}}',ident).replace('{{CLIENT}}',str(ROOT/'client.py')).replace('{{RUN_DIR}}',str(folder))
        prompt=prepare_prompt(prompt,claim)
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
                try:maintain_run(process,prompt,timeout=claim.get('timeout_seconds',1100))
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGTERM)
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
                    summary='Run reached its time limit; review any unconfirmed send before continuing.'
                if (folder/'summary.txt').exists():summary=(folder/'summary.txt').read_text().strip()[-3500:] or summary
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
