/* Pure local-time helpers shared by the onboarding controls and their preview. */
globalThis.BMTSalesTime=(()=>{
 const zones={Eastern:'America/New_York',Central:'America/Chicago',Mountain:'America/Denver','Pacific (US)':'America/Los_Angeles',Arizona:'America/Phoenix',Vancouver:'Etc/GMT+7'};
 function parts(date,zone){return Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(date).map(p=>[p.type,p.value]));}
 function today(zone,now=new Date()){const p=parts(now,zones[zone]);return `${p.year}-${p.month}-${p.day}`;}
 function add(day,n){const d=new Date(day+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+n);return d.toISOString().slice(0,10);}
 function clock(minutes){const h=Math.floor(minutes/60),m=minutes%60;return `${h%12||12}:${String(m).padStart(2,'0')} ${h>=12?'PM':'AM'}`;}
 function timeValue(minutes){return String(Math.floor(minutes/60)).padStart(2,'0')+':'+String(minutes%60).padStart(2,'0');}
 function instant(day,time,zone){
  const nominal=new Date(day+'T'+time+':00Z');let utc=nominal;
  for(let i=0;i<3;i++){const p=parts(utc,zones[zone]);utc=new Date(utc.getTime()+nominal.getTime()-Date.UTC(+p.year,+p.month-1,+p.day,+p.hour,+p.minute));}
  const p=parts(utc,zones[zone]);if(`${p.year}-${p.month}-${p.day}`!==day||`${p.hour}:${p.minute}`!==time)throw Error('That local time does not exist because of a clock change. Choose another time.');return utc;
 }
 return {zones,today,add,clock,timeValue,instant};
})();
