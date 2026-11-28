#!/usr/bin/env python3
"""Independent, on-demand booked-prospect research worker. No outreach controls."""
import fcntl,sys,time
from pathlib import Path
from client import request
from job import run_booked
ROOT=Path(__file__).resolve().parent
LOCAL=Path.home()/'.config/bmt-booked-research'
def tick():
 LOCAL.mkdir(parents=True,exist_ok=True)
 request(payload={'op':'heartbeat'})
 # Both independent workers coordinate access to the same physical browser.
 with (LOCAL.parent/'bmt-browser-worker.lock').open('w') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  run_booked(ROOT,LOCAL,request)
if __name__=='__main__':
 repeat='--daemon' in sys.argv
 while True:
  try:tick()
  except Exception:print(time.strftime('%Y-%m-%d %H:%M:%S')+' Booked research connection unavailable; retrying.',file=sys.stderr,flush=True)
  if not repeat:break
  time.sleep(30)
