"""Run explicitly requested booked-company checks without enabling outreach."""
import json,os,signal,subprocess,time
PATH='/api/booked-research/worker'
def run_booked(root,local,request):
 claim=request('POST',{'op':'claim'},path=PATH);job=claim.get('job')
 if not job:return False
 folder=local/'booked-research'/job['id'];folder.mkdir(parents=True,exist_ok=True);os.chmod(folder,0o700)
 cfg=json.loads((local/'config.json').read_text())
 prompt=(root/'booked_workflow.txt').read_text().replace('{{JOB}}',json.dumps(job,ensure_ascii=False)).replace('{{CLIENT}}',str(root/'client.py')).replace('{{RUN_DIR}}',str(folder))
 (folder/'prompt.txt').write_text(prompt)
 from cli import resolve
 command=[resolve(cfg),'-a','never','-c','mcp_servers.playwright.enabled=false','-c','mcp_servers.mobile-next.enabled=false','exec','--ephemeral','--json','-s','danger-full-access','--skip-git-repo-check','-C',str(root),'-o',str(folder/'summary.txt'),'-']
 try:
  with (folder/'events.jsonl').open('w') as log:
   os.chmod(folder/'events.jsonl',0o600);process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
   payload=prompt.encode();deadline=time.monotonic()+1100
   while True:
    remaining=deadline-time.monotonic()
    if remaining<=0:raise subprocess.TimeoutExpired(command,1100)
    try:process.communicate(payload,timeout=min(60,remaining));break
    except subprocess.TimeoutExpired:
     payload=None
     try:request('POST',{'op':'progress','job_id':job['id'],'phase':'Inspecting company sources on the Mac'},path=PATH)
     except Exception:pass
 except Exception:
  if 'process' in locals() and process.poll() is None:
   os.killpg(process.pid,signal.SIGTERM)
   try:process.wait(timeout=10)
   except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
 finally:
  # A completed/partial job rejects this fallback. Never mark an unfinished child complete.
  try:request('POST',{'op':'fail','job_id':job['id'],'reason':'The research session ended without a saved brief. Check Mac/browser access and request another check.'},path=PATH)
  except Exception:pass
 return True
