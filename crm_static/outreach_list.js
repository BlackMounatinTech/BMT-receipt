/* Contact dates are distinct from import dates. Never infer a send from creation. */
const OutreachList = (() => {
  const zone = 'America/Vancouver';
  function day(value) {
    if (!value) return '';
    if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return Number.isNaN(Date.parse(value)) ? '' : value;
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    const parts = new Intl.DateTimeFormat('en-CA', {timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(date);
    const part = type => parts.find(p=>p.type===type).value;
    return `${part('year')}-${part('month')}-${part('day')}`;
  }
  function label(value) {
    const date = day(value);
    return date ? new Intl.DateTimeFormat('en-US', {timeZone:'UTC',month:'short',day:'numeric',year:'numeric'}).format(new Date(date+'T12:00:00Z')) : 'Date not recorded';
  }
  function select(rows, {platform='',status='',from='',to='',sort='newest'}={}) {
    const result=rows.filter(l=>(!platform || (platform==='unknown' ? !l.contact_method : l.contact_method===platform)) && (!status || l.status===status) && (!from || day(l.last_contacted_at)>=from) && (!to || (day(l.last_contacted_at) && day(l.last_contacted_at)<=to)));
    result.sort((a,b)=>{
      const name=()=>a.company.localeCompare(b.company) || a.id-b.id;
      if(sort==='company') return name();
      if(sort==='followup') return (a.follow_up||'9999-12-31').localeCompare(b.follow_up||'9999-12-31') || name();
      const x=day(a.last_contacted_at),y=day(b.last_contacted_at);
      if(!x || !y) return x ? -1 : y ? 1 : name();
      return (sort==='oldest' ? x.localeCompare(y) : y.localeCompare(x)) || name();
    });
    return result;
  }
  return {day,label,select};
})();
if(typeof module!=='undefined') module.exports=OutreachList;
