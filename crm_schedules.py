"""Opening-hour calling views over existing imported contacts; no duplicate leads."""
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import crm_store as store

HOME=ZoneInfo('Etc/GMT+7')  # Vancouver's permanent UTC-7, matching the calling clock.
NAMES={'morning':'Morning','daytime':'Daytime','evening':'Evening','saturday':'Saturday','sunday':'Sunday'}
ZONES={'Eastern':'America/New_York','Central':'America/Chicago','Mountain':'America/Denver',
       'Pacific (US)':'America/Los_Angeles','Arizona':'America/Phoenix','Vancouver':'Etc/GMT+7'}
DESCRIPTIONS={
 'morning':'Open at 6 AM your time, and 1 or 2 hours ahead. Sorted by opening time.',
 'daytime':'Same time as you or behind, open during 7 AM–5 PM your time. Sorted by opening time.',
 'evening':'Open during 5–8 PM your time. Sorted by opening time.',
 'saturday':'Published Saturday hours, converted to your time. Earliest opening first.',
 'sunday':'Published Sunday hours, converted to your time. Earliest opening first.'}

def kind_for(list_id):
    return list_id[9:] if list_id.startswith('schedule:') and list_id[9:] in NAMES else None

def source_list(con,list_id,lead_id):
    if not list_id or not list_id.startswith('schedule:'):return list_id
    if not kind_for(list_id):raise ValueError('Choose a calling list.')
    row=con.execute('SELECT list_id FROM crm_call_items WHERE lead_id=? ORDER BY called_at DESC,position,list_id LIMIT 1',(lead_id,)).fetchone()
    if not row:raise ValueError('This lead is not in an imported calling list.')
    return row['list_id']

def history(con,rows):
    latest={}
    for event in con.execute('SELECT lead_id,outcome,called_at AS created_at FROM crm_call_items WHERE called_at IS NOT NULL ORDER BY called_at'):
        latest[event['lead_id']]=dict(event)
    for event in con.execute('SELECT lead_id,outcome,created_at FROM crm_call_events ORDER BY created_at,id'):
        if event['created_at'] >= latest.get(event['lead_id'],{}).get('created_at',''):
            latest[event['lead_id']]=dict(event)
    for row in rows:
        event=latest.get(row['id'])
        row['last_called_at']=event['created_at'] if event else None
        row['last_call_outcome']=event['outcome'] if event else None
    return rows

def imported():
    from crm_calling import schema
    with store.connect() as con:
        schema(con)
        rows=[dict(r) for r in con.execute('''SELECT l.*,
            COALESCE(n.text,(SELECT SUBSTR(text,INSTR(text,CHAR(10))+1) FROM crm_notes WHERE lead_id=l.id AND text LIKE 'Phone: %' AND INSTR(text,CHAR(10))>0 ORDER BY id DESC LIMIT 1),'') AS call_notes,COALESCE(n.version,0) AS note_version
            FROM crm_leads l LEFT JOIN crm_call_notes n ON n.lead_id=l.id
            WHERE EXISTS(SELECT 1 FROM crm_call_items i WHERE i.lead_id=l.id)''')]
        return history(con,rows)

def windows(lead,target):
    try:
        weekly=json.loads(lead.get('business_hours') or '{}').get('weekly',{})
        zone=ZoneInfo(lead.get('lead_timezone') or ZONES.get(lead.get('call_zone'),''))
    except (ValueError,TypeError,KeyError):return []
    if not isinstance(weekly,dict):return []
    result=[]
    # Include the local prior day for overnight periods crossing into the target day.
    for delta in (-1,0,1):
        day=target+timedelta(days=delta)
        for start,end in weekly.get(str(day.weekday()),[]):
            local_start=datetime.combine(day,datetime.min.time(),zone)+timedelta(minutes=start)
            local_end=datetime.combine(day,datetime.min.time(),zone)+timedelta(minutes=end+(1440 if end<start else 0))
            a=(local_start.astimezone(HOME).date()-target).days*1440+local_start.astimezone(HOME).hour*60+local_start.astimezone(HOME).minute
            b=(local_end.astimezone(HOME).date()-target).days*1440+local_end.astimezone(HOME).hour*60+local_end.astimezone(HOME).minute
            if a<1440 and b>0:result.append((max(0,a),min(1440,b)))
    merged=[]
    for a,b in sorted(result):
        if merged and a<=merged[-1][1]:merged[-1]=(merged[-1][0],max(merged[-1][1],b))
        else:merged.append((a,b))
    return merged

def select(kind,rows,instant=None):
    if kind not in NAMES:raise ValueError('Choose a calling list.')
    today=(instant or datetime.now(timezone.utc)).astimezone(HOME).date()
    if kind in ('saturday','sunday'):
        weekday=5 if kind=='saturday' else 6
        target=today+timedelta(days=(weekday-today.weekday())%7)
    else:
        target=today+timedelta(days=(7-today.weekday())%7 if today.weekday()>4 else 0)
    picked=[]
    for lead in rows:
        if lead.get('last_called_at') or lead.get('is_test'):
            continue
        periods=windows(lead,target)
        try:
            z=ZoneInfo(lead.get('lead_timezone') or ZONES.get(lead.get('call_zone'),''))
            offset=(datetime.combine(target,datetime.min.time(),z).utcoffset()-datetime.combine(target,datetime.min.time(),HOME).utcoffset()).total_seconds()/3600
        except (ValueError,TypeError,KeyError):continue
        if kind=='morning':matches=[p for p in periods if p[0]<=360<p[1]] if offset in (1,2) else []
        elif kind=='daytime':matches=[p for p in periods if p[0]<1020 and p[1]>420] if offset<=0 else []
        elif kind=='evening':matches=[p for p in periods if p[0]<1200 and p[1]>1020]
        else:matches=periods
        if not matches:continue
        row=dict(lead);row.update(outcome=lead.get('last_call_outcome'),called_at=lead.get('last_called_at'),
            opening_minute=min(p[0] for p in matches),closing_minute=max(p[1] for p in matches),schedule_date=target.isoformat())
        picked.append(row)
    picked.sort(key=lambda r:(r['opening_minute'],r['company'].casefold(),r['id']))
    for i,row in enumerate(picked):row['position']=i
    return picked

def lists():
    rows=imported();result=[]
    for kind,name in NAMES.items():
        selected=select(kind,rows)
        result.append(dict(id='schedule:'+kind,name='BMT USA Marketing Leads '+name+' List 1',
            total=len(selected),completed=sum(bool(r['last_called_at']) for r in selected),
            kind=kind,description=DESCRIPTIONS[kind],scheduled=True))
    return result

def items(list_id):return select(kind_for(list_id),imported())
