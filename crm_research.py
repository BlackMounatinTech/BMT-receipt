"""Apply researched calling cues and published hours without touching call notes."""
import json
from urllib.parse import urlparse
import crm_store as store


def public_url(value):
    if not isinstance(value, str) or len(value) > 2000:
        raise ValueError('Check the source URL.')
    if value and (urlparse(value).scheme not in ('http', 'https') or not urlparse(value).netloc):
        raise ValueError('Use a public website URL.')
    return value


def validate_hours(value):
    if not isinstance(value, dict) or set(value) - {'weekly', 'source_url', 'source', 'checked_at'}:
        raise ValueError('Check the published business hours.')
    weekly = value.get('weekly', {})
    if not isinstance(weekly, dict) or set(weekly) - set('0123456'):
        raise ValueError('Use weekdays 0 through 6.')
    for periods in weekly.values():
        if not isinstance(periods, list) or len(periods) > 4:
            raise ValueError('Check the opening periods.')
        for period in periods:
            if (not isinstance(period, list) or len(period) != 2 or
                    any(type(v) is not int for v in period) or
                    not 0 <= period[0] < 1440 or not 0 <= period[1] <= 1440 or period[0] == period[1]):
                raise ValueError('Use valid opening and closing minutes.')
    public_url(value.get('source_url', ''))
    for key in ('source', 'checked_at'):
        if not isinstance(value.get(key, ''), str) or len(value.get(key, '')) > 160:
            raise ValueError('Check the hours source.')
    return value


def save(lead_id, revision, need, website, hours):
    if type(revision) is not int or not isinstance(need, str) or len(need) > 10000:
        raise ValueError('Refresh the lead and check its research notes.')
    website = public_url(website)
    hours = json.dumps(validate_hours(hours), separators=(',', ':'))
    with store.connect() as con:
        result = con.execute('''UPDATE crm_leads SET need=?,website=?,business_hours=?,
            updated_at=?,revision=revision+1 WHERE id=? AND revision=?''',
            (need, website, hours, store.now(), lead_id, revision))
        if result.rowcount != 1:
            raise store.Conflict('This lead changed. Refresh before updating its research.')
    return {'ok': True, 'revision': revision + 1}
