"""Scoped platform failures and visible, durable operational alerts."""
import hashlib
import json
from datetime import datetime,timedelta

def api():
    import crm_outreach_system
    return crm_outreach_system

def schema(con):
    con.execute('''CREATE TABLE IF NOT EXISTS crm_ai_channel_health(channel TEXT PRIMARY KEY,state TEXT NOT NULL,
      kind TEXT NOT NULL,reason TEXT NOT NULL,action TEXT NOT NULL,proof TEXT NOT NULL,checked_at TEXT NOT NULL,
      next_check TEXT NOT NULL,blocks_history INTEGER NOT NULL DEFAULT 0)''')
    con.execute('''CREATE TABLE IF NOT EXISTS crm_ai_alerts(id TEXT PRIMARY KEY,scope TEXT NOT NULL,kind TEXT NOT NULL,
      severity TEXT NOT NULL,reason TEXT NOT NULL,action TEXT NOT NULL,opened_at TEXT NOT NULL,updated_at TEXT NOT NULL,
      resolved_at TEXT NOT NULL DEFAULT '')''')
    for c in api().CHANNELS:con.execute("INSERT OR IGNORE INTO crm_ai_channel_health VALUES(?,'unknown','','Not checked yet','The next run will check this connection.','','','',0)",(c,))

def alert(con,scope,kind,reason,action,severity='warning'):
    m=api();ident=hashlib.sha256((scope+'|'+kind).encode()).hexdigest()
    con.execute('''INSERT INTO crm_ai_alerts VALUES(?,?,?,?,?,?,?,?,'') ON CONFLICT(id) DO UPDATE SET
      reason=excluded.reason,action=excluded.action,severity=excluded.severity,updated_at=excluded.updated_at,resolved_at='' ''',(ident,scope,kind,severity,reason,action,m.stamp(),m.stamp()))

def ready(con,channel):
    r=con.execute('SELECT * FROM crm_ai_channel_health WHERE channel=?',(channel,)).fetchone()
    if not r or r['state']!='ready' or not r['checked_at'] or api().instant()-datetime.fromisoformat(r['checked_at'])>timedelta(hours=24):
        raise ValueError(channel+' needs a successful live connection check before sending.')

def intro_gate(con,channel):
    ready(con,channel)
    configured=json.loads(api().config(con)['channels'])
    for r in con.execute('SELECT * FROM crm_ai_channel_health WHERE blocks_history=1'):
        if r['channel'] in configured:raise ValueError('New introductions held: '+r['channel']+' contact history is unavailable. Verified existing conversations on other platforms can continue.')

def dispatch(con,p):
    m=api();op=p.get('op')
    if op not in ('channel-block','channel-ready','retry-channel','resolve-alert'):return None
    if p.get('run_id'):m.live_run(con,p['run_id'])
    if op=='resolve-alert':
        row=con.execute("SELECT * FROM crm_ai_alerts WHERE id=? AND resolved_at=''",(p.get('id'),)).fetchone()
        if not row:raise ValueError('Choose an open alert.')
        if row['scope'] in m.CHANNELS:raise ValueError('Use Check again, then verify the platform; an alert cannot bypass its sending block.')
        proof=m.short(p,'proof',2000)
        con.execute('UPDATE crm_ai_alerts SET resolved_at=?,action=? WHERE id=?',(m.stamp(),proof,row['id']));return dict(ok=True)
    channel=p.get('channel')
    if channel not in m.CHANNELS:raise ValueError('Choose a supported platform.')
    row=con.execute('SELECT * FROM crm_ai_channel_health WHERE channel=?',(channel,)).fetchone()
    if op=='retry-channel':
        con.execute("UPDATE crm_ai_channel_health SET state='needs_check',next_check=? WHERE channel=?",(m.stamp(),channel))
        # Keep any history block and alert until the UI has actually been verified.
        return dict(ok=True)
    if op=='channel-ready':
        m.live_run(con,p.get('run_id'));proof=m.short(p,'proof',3000)
        if len(proof.split())<5:raise ValueError('Describe the observed signed-in platform and readable conversation history.')
        con.execute("UPDATE crm_ai_channel_health SET state='ready',kind='',reason='Live platform and history verified',action='',proof=?,checked_at=?,next_check='',blocks_history=0 WHERE channel=?",(proof,m.stamp(),channel))
        con.execute("UPDATE crm_ai_alerts SET resolved_at=? WHERE scope=? AND resolved_at=''",(m.stamp(),channel))
        return dict(ok=True)
    kind=p.get('kind')
    if kind not in ('history_missing','login_required','rate_limit','captcha','temporary_error','account_restricted','recipient_uncertain'):raise ValueError('Choose the platform blocker type.')
    reason=m.short(p,'reason',1500);action=m.short(p,'action',1500);proof=m.short(p,'proof',3000)
    blocks_history=p.get('blocks_history',kind in ('history_missing','login_required'))
    if type(blocks_history)is not bool:raise ValueError('Specify whether history verification is blocked.')
    if kind in ('history_missing','login_required'):blocks_history=True
    cooldown=30 if kind=='temporary_error' else 60 if kind=='rate_limit' else 1440
    # Missing-history/auth prompts need human repair; do not repeatedly click/code-request each run.
    next_check=(m.instant()+timedelta(minutes=cooldown)).isoformat()
    con.execute("UPDATE crm_ai_channel_health SET state='blocked',kind=?,reason=?,action=?,proof=?,checked_at=?,next_check=?,blocks_history=? WHERE channel=?",(kind,reason,action,proof,m.stamp(),next_check,int(blocks_history),channel))
    alert(con,channel,kind,reason,action)
    return dict(ok=True,channel_blocked=channel,other_channels_continue=True)

def snapshot(con):
    m=api();cfg=m.config(con);channels=[dict(r) for r in con.execute('SELECT * FROM crm_ai_channel_health')]
    alerts=[dict(r) for r in con.execute("SELECT * FROM crm_ai_alerts WHERE resolved_at='' ORDER BY severity,opened_at")]
    now=m.instant();heartbeat=cfg['heartbeat'];fresh=bool(heartbeat and now-datetime.fromisoformat(heartbeat)<timedelta(minutes=3))
    running=con.execute("SELECT * FROM crm_ai_runs WHERE state='running' ORDER BY started_at DESC LIMIT 1").fetchone()
    if not fresh:alerts.append(dict(id='worker-offline',scope='Mac worker',kind='offline',severity='critical',reason='No recent Mac-worker heartbeat. Scheduled outreach cannot be assumed to be running.',action='Keep the Mac awake and restart the active-session worker if it stopped.',opened_at=heartbeat or '',updated_at=heartbeat or ''))
    if cfg['enabled'] and fresh and not running and cfg['next_run'] and now-datetime.fromisoformat(cfg['next_run'])>timedelta(minutes=3):
        alerts.append(dict(id='run-overdue',scope='Scheduler',kind='overdue',severity='critical',reason='The next run is overdue even though the worker is connected.',action='Inspect the worker log and restart only after checking for any unconfirmed send.',opened_at=cfg['next_run'],updated_at=cfg['next_run']))
    uncertain=con.execute("SELECT COUNT(*) FROM crm_ai_prospects WHERE state IN ('sending','unconfirmed','blocked')").fetchone()[0]+con.execute("SELECT COUNT(*) FROM crm_ai_messages WHERE direction='outbound' AND state IN ('sending','unconfirmed','blocked')").fetchone()[0]
    if uncertain and not running:alerts.append(dict(id='send-review',scope='Sending',kind='uncertain_send',severity='critical',reason='A message attempt needs delivery review. Never resend automatically.',action='Inspect the exact recipient thread and resolve delivery before restarting sends.',opened_at='',updated_at=''))
    selected=[r for r in channels if r['channel'] in json.loads(cfg['channels'])]
    available=[r['channel'] for r in selected if r['state']=='ready']
    mode='Paused' if not cfg['enabled'] else 'Worker offline' if not fresh else 'Working with blockers' if alerts else 'Checking connections' if not available else 'Working' if running else 'Waiting for next run'
    return dict(mode=mode,heartbeat_fresh=fresh,active_run=running['id'] if running else None,channels=channels,alerts=alerts,available_channels=available,
                cold_outreach_held=any(r['blocks_history'] for r in selected),last_run=dict(con.execute('SELECT * FROM crm_ai_runs ORDER BY started_at DESC LIMIT 1').fetchone() or {}))
