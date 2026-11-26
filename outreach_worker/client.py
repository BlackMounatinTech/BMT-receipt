#!/usr/bin/env python3
"""Local authenticated CRM client. Never prints the worker key or cookies."""
import http.cookiejar
import json
import re
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPCookieProcessor

CONFIG=Path.home()/'.config/bmt-outreach-system/config.json'

def request(method='GET',payload=None):
    cfg=json.loads(CONFIG.read_text())
    opener=build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    page=opener.open(cfg['base_url']+'/',timeout=30).read().decode()
    csrf=re.search(r'name="csrf" content="([^"]+)"',page)[1]
    body=json.dumps(payload).encode() if payload is not None else None
    req=Request(cfg['base_url']+'/api/outreach-system',data=body,method=method,
                headers={'Content-Type':'application/json','X-CSRF-Token':csrf,'X-BMT-Outreach-Key':cfg['key']})
    try:
        with opener.open(req,timeout=30) as response:return json.load(response)
    except HTTPError as e:
        try:detail=json.loads(e.read().decode()).get('error','CRM request rejected.')
        except (ValueError,UnicodeError):detail='CRM request rejected.'
        raise ValueError(str(detail)) from None

if __name__=='__main__':
    try:
        if len(sys.argv)==1 or sys.argv[1]=='get':result=request()
        elif sys.argv[1]=='post':result=request('POST',json.loads(Path(sys.argv[2]).read_text()))
        elif sys.argv[1]=='connect-link':
            raise ValueError('Worker credentials cannot create owner-access links. Use an existing owner browser session or authenticated Render administrator recovery.')
        else:raise ValueError('Use get, post FILE, or connect-link.')
        print(json.dumps(result,ensure_ascii=False))
    except Exception as e:
        print(json.dumps({'error':str(e)}));raise SystemExit(1)
