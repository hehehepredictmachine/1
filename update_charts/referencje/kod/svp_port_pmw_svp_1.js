/* PMW-SVP-1 – port 1:1 z backend/masterquo/svp/engine.py + zones/dsvie.py (histogram, value_area, nodes) i analytics/session_engine.py
   (okna sesji w strefach IANA, DST przez Intl). Rozkład wagi świecy równomiernie w [low, high] (UNIFORM_RANGE_ALLOCATION_FROM_CANDLES);
   siatka zakotwiczona w wielokrotnościach bin_size od ceny 0; VA: start w POC (remis → niższa cena), rozszerzanie o jeden bin w stronę
   większego sąsiada (remis → w dół) aż ≥ va_pct; HVN/LVN z wygładzonego histogramu (okno 3, HVN ≥ 0.6×max bez POC, LVN ≤ 0.35×min(szczytów)). */
const SVP_PROFILES={
 LAB_XAU_REFERENCE_V1:{label:'Lab XAUUSD – sesje referencyjne',sessions:[['ASIA','Asia/Tokyo','09:00','15:00'],['LONDON','Europe/London','08:00','16:30'],['NEW_YORK','America/New_York','08:20','13:30']]},
 LAB_BTC_REFERENCE_V1:{label:'Lab BTC – sesje referencyjne',sessions:[['ASIA','Asia/Singapore','08:00','16:00'],['EUROPE','Europe/London','08:00','16:30'],['US','America/New_York','09:30','16:00']]},
 SCALP_OPENING_V1:{label:'Scalp – boksy otwarcia',sessions:[['ASIA','Asia/Tokyo','09:00','15:00'],['LONDON','Europe/London','08:00','12:00'],['NEW_YORK','America/New_York','08:00','12:00']]}};
const _tzf={};
function tzOffsetMin(tz,ms){const f=_tzf[tz]||(_tzf[tz]=new Intl.DateTimeFormat('en-US',{timeZone:tz,hourCycle:'h23',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}));
 const p={};for(const x of f.formatToParts(new Date(ms)))p[x.type]=x.value;return (Date.UTC(+p.year,+p.month-1,+p.day,+p.hour%24,+p.minute,+p.second)-Math.floor(ms/1000)*1000)/60000;}
function zonedToUtc(tz,y,m,d,hh,mm){const g=Date.UTC(y,m-1,d,hh,mm);const o1=tzOffsetMin(tz,g);let t=g-o1*60000;const o2=tzOffsetMin(tz,t);if(o2!==o1)t=g-o2*60000;return t;}
function localDate(tz,ms){const o=tzOffsetMin(tz,ms),d=new Date(ms+o*60000);return [d.getUTCFullYear(),d.getUTCMonth()+1,d.getUTCDate()];}
/* [start,end) UTC jednej sesji w jej LOKALNEJ dacie; koniec ≤ początek = przez północ */
function svpWindow(sess,y,m,d){const [,tz,a,b]=sess,[ah,am]=a.split(':').map(Number),[bh,bm]=b.split(':').map(Number);const s=zonedToUtc(tz,y,m,d,ah,am);
 let e;if(bh*60+bm<=ah*60+am){const nd=new Date(Date.UTC(y,m-1,d+1));e=zonedToUtc(tz,nd.getUTCFullYear(),nd.getUTCMonth()+1,nd.getUTCDate(),bh,bm);}else e=zonedToUtc(tz,y,m,d,bh,bm);return [s,e];}
function svpWindows(profileId,t0,t1){const P=SVP_PROFILES[profileId],out=[];for(const s of P.sessions){let [y,m,d]=localDate(s[1],t0-86400000);
 for(let k=0;k<400;k++){const dt=new Date(Date.UTC(y,m-1,d+k));const Y=dt.getUTCFullYear(),M=dt.getUTCMonth()+1,Dd=dt.getUTCDate();const [a,b]=svpWindow(s,Y,M,Dd);if(a>t1)break;if(b>t0)out.push({session:s[0],tz:s[1],local_date:`${Y}-${String(M).padStart(2,'0')}-${String(Dd).padStart(2,'0')}`,start:a,end:b});}}
 return out.sort((p,q)=>p.start-q.start);}
/* dzielenie całkowite jak float // w CPython (fmod + korekta) – identyczne przypisanie do binów co w silniku bota */
function pyFloorDiv(a,b){const mod=a%b;let div=(a-mod)/b;if(mod&&((b<0)!==(mod<0)))div-=1;let fl=Math.floor(div);if(div-fl>.5)fl+=1;return fl;}
function svpHistogram(bars,idx,bin){const H=new Map();for(const i of idx){const b=bars[i],v=b.v;if(!(v>0))continue;const lo=b.l,hi=b.h,b0=pyFloorDiv(lo,bin),b1=pyFloorDiv(hi,bin);
  if(b1===b0||hi<=lo){H.set(b0,(H.get(b0)||0)+v);continue;}const span=hi-lo;for(let k=b0;k<=b1;k++){const ov=Math.min(hi,(k+1)*bin)-Math.max(lo,k*bin);if(ov>0)H.set(k,(H.get(k)||0)+v*ov/span);}}
 return H;}
function svpValueArea(H,pct){const keys=[...H.keys()].sort((a,b)=>a-b),lo=keys[0],hi=keys[keys.length-1],vals=[];for(let k=lo;k<=hi;k++)vals.push(H.get(k)||0);
 const tot=vals.reduce((a,b)=>a+b,0);let p=0;for(let i=1;i<vals.length;i++)if(vals[i]>vals[p])p=i;let a=p,b=p,acc=vals[p];
 while(acc<pct*tot&&(a>0||b<vals.length-1)){const up=b<vals.length-1?vals[b+1]:-1,dn=a>0?vals[a-1]:-1;if(up>dn){b++;acc+=up;}else{a--;acc+=dn;}}
 return [lo+p,lo+a,lo+b];}
/* suma jak sum() w CPython ≥ 3.12 (kompensacja Neumaiera) – te same remisy przy wykrywaniu węzłów */
function pySum(a){let s=0,c=0;for(const x of a){const t=s+x;if(Math.abs(s)>=Math.abs(x))c+=(s-t)+x;else c+=(x-t)+s;s=t;}return s+c;}
function svpNodes(H,poc,sm_w=3,hvnS=.6,lvnS=.35){const keys=[...H.keys()].sort((a,b)=>a-b),lo=keys[0],hi=keys[keys.length-1],raw=[];for(let k=lo;k<=hi;k++)raw.push(H.get(k)||0);
 const w=Math.max(1,sm_w),h2=Math.floor(w/2),sm=raw.map((_,i)=>{const s=raw.slice(Math.max(0,i-h2),i+h2+1);return pySum(s)/s.length;});const mx=sm.length?Math.max(...sm):0,hv=[],lv=[];
 for(let i=1;i<sm.length-1;i++){if(sm[i]>sm[i-1]&&sm[i]>=sm[i+1]&&sm[i]>=hvnS*mx&&lo+i!==poc)hv.push(lo+i);
  if(sm[i]<sm[i-1]&&sm[i]<=sm[i+1]){const L=Math.max(...sm.slice(0,i)),R=Math.max(...sm.slice(i+1));if(sm[i]<=lvnS*Math.min(L,R))lv.push(lo+i);}}return [hv,lv];}
/* profil zamkniętych świec z open ≥ t0 i close ≤ min(t1, as_of); bary: {t(ms),o,h,l,c,v=tick volume} */
function svpCompute(bars,tfSec,t0,t1,asOf,{tick,binTicks,va=.70,label=null,mode='SESSION'}){const bin=Math.round(binTicks*tick*1e10)/1e10,upto=Math.min(t1,asOf),idx=[];
 for(let i=0;i<bars.length;i++){const b=bars[i];if(b.t>=t0-1&&b.t+tfSec*1000<=upto+1)idx.push(i);}
 const expected=Math.max(0,Math.floor((upto-t0)/(tfSec*1000))),out={contract:'PMW-SVP-1',mode,label,start:t0,end:t1,as_of:asOf,state:asOf<t1?'DEVELOPING':'COMPLETED',tick,bin_ticks:binTicks,bin_size:bin,value_area_pct:va,
  volume_source:'TICK_VOLUME',method:'UNIFORM_RANGE_ALLOCATION_FROM_CANDLES',bars:idx.length,expected_bars:expected,coverage:expected?Math.round(idx.length/expected*1e4)/1e4:0};
 if(!idx.length)return {...out,status:'NO_DATA',reason:'brak zamkniętych świec w zakresie (lub historia niedostępna)'};
 const H=svpHistogram(bars,idx,bin),tot=[...H.values()].reduce((a,b)=>a+b,0);if(!H.size||tot<=0)return {...out,status:'NO_DATA',reason:'zerowe wagi w zakresie'};
 const [poc,vl,vh]=svpValueArea(H,va),[hv,lv]=svpNodes(H,poc);let vaw=0;for(const [k,v] of H)if(k>=vl&&k<=vh)vaw+=v;
 const r10=x=>Math.round(x*1e10)/1e10;
 return {...out,status:out.coverage>=.9||out.state==='DEVELOPING'?'READY':'PARTIAL',reason:out.coverage>=.9?null:`pokrycie ${Math.round(out.coverage*100)}% – historia częściowa`,
  total_weight:tot,poc:r10((poc+.5)*bin),vah:r10((vh+1)*bin),val:r10(vl*bin),va_share:Math.round(vaw/tot*1e4)/1e4,hvn:hv.map(k=>r10((k+.5)*bin)),lvn:lv.map(k=>r10((k+.5)*bin)),
  high:Math.max(...idx.map(i=>bars[i].h)),low:Math.min(...idx.map(i=>bars[i].l)),known_at:bars[idx[idx.length-1]].t+tfSec*1000,
  hist:[...H.entries()].sort((a,b)=>a[0]-b[0]).map(([k,v])=>[k,v])};}
if(typeof module!=='undefined')module.exports={SVP_PROFILES,svpWindows,svpCompute,zonedToUtc};
