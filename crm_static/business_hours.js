/* Published local opening hours. Unknown hours never become an open/closed guess. */
globalThis.BMTBusinessHours=(()=>{
  const days=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
  function time(n){if(n===1440)n=0;const h=Math.floor(n/60),m=n%60;return `${h%12||12}${m?':'+String(m).padStart(2,'0'):''} ${h>=12?'PM':'AM'}`;}
  function intervals(periods){
    if(!Array.isArray(periods))return 'Unverified';
    if(!periods.length)return 'Closed';
    return periods.map(([a,b])=>a===0&&b===1440?'Open 24 hours':`${time(a)}–${time(b)}${b<a?' (overnight)':''}`).join(', ');
  }
  function describe(raw,zone,instant=new Date()){
    let hours;try{hours=typeof raw==='string'?JSON.parse(raw):raw;}catch{return {state:'unknown',text:'Hours unverified',week:[]};}
    const weekly=hours?.weekly;
    if(!weekly||!Object.keys(weekly).length||!zone)return {state:'unknown',text:'Hours unverified',week:[]};
    const parts=new Intl.DateTimeFormat('en-US',{timeZone:zone,weekday:'short',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(instant);
    const get=type=>parts.find(p=>p.type===type).value;
    const day=days.indexOf(get('weekday')),minute=Number(get('hour'))*60+Number(get('minute'));
    const today=weekly[String(day)],previous=weekly[String((day+6)%7)];
    const previousOpen=previous?.find(([a,b])=>b<a&&minute<b);
    const active=today?.find(([a,b])=>b<a?minute>=a:minute>=a&&minute<b);
    const open=active||previousOpen;
    const state=open?'open':Array.isArray(today)?'closed':'unknown';
    const text=open?`Open now · Closes ${time(open[1])}`:state==='closed'?'Closed now':'Hours unverified today';
    return {state,text,today:`Today: ${intervals(today)}`,week:days.map((name,i)=>`${name}: ${intervals(weekly[String(i)])}`),source:hours.source||'',sourceUrl:hours.source_url||'',checkedAt:hours.checked_at||''};
  }
  return {describe,intervals};
})();
