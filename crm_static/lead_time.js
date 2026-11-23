/* Pure clock helpers. Vancouver stays at UTC-7; US zones retain seasonal changes. */
globalThis.BMTLeadTime = (() => {
  const labels={Eastern:'America/New_York',Central:'America/Chicago',Mountain:'America/Denver','Pacific (US)':'America/Los_Angeles',Arizona:'America/Phoenix',Vancouver:'Etc/GMT+7'};
  const states={};
  for(const [zone,codes] of Object.entries({
    'America/New_York':'CT DE DC GA MA MD ME NC NH NJ NY OH PA RI SC VA VT WV',
    'America/Chicago':'AL AR IA IL LA MN MO MS OK WI',
    'America/Denver':'CO MT NM UT WY',
    'America/Los_Angeles':'CA NV WA',
    'Etc/GMT+7':'BC'
  }))codes.split(' ').forEach(code=>states[code]=zone);
  function zoneFor(lead){
    if(Object.values(labels).includes(lead.lead_timezone))return lead.lead_timezone;
    if(labels[lead.call_zone])return labels[lead.call_zone];
    const state=(lead.location||'').trim().match(/,\s*([A-Za-z]{2})\s*$/)?.[1]?.toUpperCase();
    return states[state]||''; // Split-zone states need a verified company zone.
  }
  function clock(zone,instant=new Date()){
    const time=new Intl.DateTimeFormat('en-US',{timeZone:zone,hour:'numeric',minute:'2-digit'}).format(instant);
    const offsetText=new Intl.DateTimeFormat('en-US',{timeZone:zone,timeZoneName:'shortOffset'}).formatToParts(instant).find(p=>p.type==='timeZoneName').value;
    const match=offsetText.match(/^GMT(?:([+-])(\d{1,2})(?::(\d{2}))?)?$/);
    if(!match)throw Error('Could not determine the time difference.');
    const offset=match[1]?(match[1]==='-'?-1:1)*(Number(match[2])+Number(match[3]||0)/60):0;
    const difference=offset+7;
    return {time,difference,label:difference===0?'Same time':`${difference>0?'+':''}${difference} ${Math.abs(difference)===1?'hour':'hours'}`};
  }
  return {labels,zoneFor,clock};
})();
