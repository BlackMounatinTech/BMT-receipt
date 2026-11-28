#!/usr/bin/env python3
"""Dedicated client: can post only booked-prospect information-gathering actions."""
import http.cookiejar,json,re,sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,build_opener,HTTPCookieProcessor
CONFIG=Path.home()/'.config/bmt-booked-research/config.json'
ALLOWED={'claim','heartbeat','progress','finish','fail'}
def request(method='POST',payload=None,path='/api/booked-research/worker'):
 if method!='POST' or path!='/api/booked-research/worker' or not isinstance(payload,dict) or payload.get('op') not in ALLOWED:raise ValueError('This client only gathers information for booked prospects.')
 cfg=json.loads(CONFIG.read_text());opener=build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
 page=opener.open(cfg['base_url']+'/',timeout=30).read().decode();csrf=re.search(r'name="csrf" content="([^"]+)"',page)[1]
 req=Request(cfg['base_url']+path,data=json.dumps(payload).encode(),method='POST',headers={'Content-Type':'application/json','X-CSRF-Token':csrf,'X-BMT-Research-Key':cfg['key']})
 try:
  with opener.open(req,timeout=30) as response:return json.load(response)
 except HTTPError as e:
  try:detail=json.loads(e.read().decode()).get('error','Research request rejected.')
  except (ValueError,UnicodeError):detail='Research request rejected.'
  raise ValueError(str(detail)) from None
if __name__=='__main__':
 try:
  if len(sys.argv)!=3 or sys.argv[1]!='post':raise ValueError('Use post PAYLOAD_FILE.')
  print(json.dumps(request(payload=json.loads(Path(sys.argv[2]).read_text())),ensure_ascii=False))
 except Exception as e:print(json.dumps({'error':str(e)}));raise SystemExit(1)
