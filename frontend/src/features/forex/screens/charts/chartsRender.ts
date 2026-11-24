// @ts-nocheck
/* CHARTS 1:1 (pakiet update_charts, K1): kod rysowania przeniesiony z update_charts/referencje/kod/charts_wzorzec/charts.js (= REF_B 947–1386)
   bez zmian stałych, kolorów, czcionek, odstępów, kolejności rysowania, progów i tekstów. Usunięte (D1 / prompt §2): generatory DEMO
   wzorca (generatory świec, dane bota z podglądu, losowanie w chartTick, demonstracyjny Kronos).
   Dane: model widoku (chartsData.ts → setVM) albo fixture testu 1:1 (load). Dodane wyłącznie ochrony stanu pustego (brak świec → BRAK
   rysowania, status z API). Ekran jest wpięty w silnik kuli FOREX jak SCREENS[0] we wzorcu (planet / draw / tick / open / close). */
import { SVP_PROFILES, svpWindows, svpCompute } from './svpPort.js';
import { drawHeat } from './chartsHeat';
/** visible: GET /api/v1/svp/visible (tylko produkcja; instrument silnika). Brak → port (tryb testowy, BTC). */
export type ChartsEnv = { announce?: (t: string) => void; visible?: (q: { tf: string; t0: number; t1: number; bin: number; va: number }) => Promise<any> };
export function createCharts(env: ChartsEnv = {}) {
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,x)), lerp=(a,b,t)=>a+(b-a)*t;
const smooth=x=>{x=clamp(x);return x*x*(3-2*x)};
const easeIO3=x=>{x=clamp(x);return x<.5?4*x*x*x:1-Math.pow(-2*x+2,3)/2}, easeOut3=x=>{x=clamp(x);return 1-Math.pow(1-x,3)};
const seg=(ms,a,d)=>clamp((ms-a)/d);
let S={view:{w:1,h:1,dpr:1},reduced:false}, SUB={state:'none',p:0,pi:0};          // podmieniane przez bind() na obiekty silnika
const announce=t=>{try{env.announce&&env.announce(t);}catch(e){}};
const VM={status:'loading',probs:null,kronos:null};
const PROBS0={win:{name:'Legacy ML · P(cel przed SL)',task:'—',v:null,state:'NO_DATA',cal:'NOT_APPLICABLE',src:'brak modelu w API'},tp2:{name:'SH tp_model · P(TP2 przed SL)',task:'—',v:null,state:'NO_DATA',cal:'NOT_APPLICABLE',src:'brak modelu w API'}};
/* K3: włączniki warstw sygnałów i wybór strategii pamiętane lokalnie (bez zapisu w backendzie); tylko poza trybem testowym */
const PKEY='pmw.charts.str.v1';let PROD=false;const seenSig=new Set();let lastAnn=0;
function loadPref(){try{return JSON.parse(localStorage.getItem(PKEY)||'null');}catch(e){return null;}}
function savePref(){if(!PROD)return;try{const all=Object.keys(SMETA);localStorage.setItem(PKEY,JSON.stringify({L:{strat:L.strat,plan:L.plan,card:L.card,stratLv:L.stratLv,view:L.view,hwin:L.hwin,hpal:L.hpal,hgain:L.hgain,hcob:L.hcob,hbbo:L.hbbo,hbub:L.hbub,hvol:L.hvol},off:all.filter(id=>!STR.on.has(id)),open:STR.open}));}catch(e){}}
const IPROF_REF={ema:[20,50],rsi:14,sig:'EMA'};   /* wzorzec (fixtures testu 1:1); produkcja: profil silnika z /api/v1/candles */                                // ostatni model widoku z API
/* ---------- CHARTS — podgląd zgodny z architekturą PMW 1.41.0 (wartości DEMONSTRACYJNE) ----------
   Źródła w aplikacji (do podpięcia przez Claude Code): /api/v1/candles?tf, /api/v1/timeframes, /api/v1/structure, /api/v1/zones/map,
   /api/v1/market-zones, /api/v1/liquidity/sessions, /api/v1/svp/visible, /api/v1/kronos + /api/v1/kronos/forecast, WebSocket bar/quote/connection.
   Instrumenty: XAUUSD (XAUUSD-) i BTC (BTCUSDT-). Interwały z TF_REGISTRY. Tu wszystkie liczby są generowane lokalnie. */
const CH_MS={inMs:2400,outMs:1500};

/* PMW-SVP-1 – port 1:1 w ./svpPort.js (K5: jeden moduł dla ekranu i testu zgodności 27/27) */

/* BOTVM – warstwy bota: model widoku z API (chartsData.ts) albo fixture testu 1:1. */
const BOTVM={sig:{},zones:{},states:{},meta:{FX_SMC:[],FX_SCALP:[],FX_HEDGE:[],LEGACY:[],SH:[]}};
const ASSETS={XAUUSD:{sym:'XAUUSD-',p:4012.4,d:2,v:1.15},BTC:{sym:'BTCUSDT-',p:96420,d:2,v:95}};
let TFR=[['M1',60,'TRIGGER',1],['M3',180,'TRIGGER',0],['M5',300,'TRIGGER',1],['M15',900,'SETUP',1],['M30',1800,'SETUP_CONTEXT',0],['H1',3600,'LOCAL_CONTEXT',1],['H4',14400,'HTF',1],['H8',28800,'TREND_REGIME_CONTEXT',0],['D1',86400,'BACKGROUND',1]];
let TFSEC=Object.fromEntries(TFR.map(r=>[r[0],r[1]]));
const KR_TFS=['M1','M5','M15','M30','H1'],KR_H={M1:15,M5:12,M15:8,M30:8,H1:6};
const CH={iprof:IPROF_REF,cv:$('#chart'),ctx:$('#chart').getContext('2d'),asset:'XAUUSD',tf:'M15',data:[],ind:null,view:120,offset:0,yMin:0,yMax:1,hover:null,khover:null,status:'live',drag:null,lastTick:0,flash:0,swap:1,token:0,
 kr:{tf:'M5',mode:'AUTO',on:{M1:true,M5:true,M15:true,M30:true,H1:true},onChart:true,data:[],fc:null,anim:1,state:'READY'},tz:'LOCAL',serverOff:2};
const L={ema:true,avwap:true,rsi:true,macd:true,atr:true,sar:false,bb:false,vp:false,vpPoc:true,vpVa:true,vpAuto:false,strat:true,stratLv:'sel',mzHist:false,svpS:true,svpProf:'AUTO',svpBinX:50,svpBinB:2000,svpVa:.7,svpOff:{},vpHvn:true,vpLvn:true,vpTf:null,vpBars:200,vpMode:'AUTO',
 mz:true,fvg:false,ob:false,sd:false,sr:false,liq:false,zmap:false,svp:false,walls:false,structure:true,patterns:false,sessions:false,heat:false,iq:false,ai:false,
 kronos:true,granite:false,plan:true,sigs:true,sigHist:true,card:true,mcTp:true,scalp:false,hedge:false,grid:true,volume:true,labels:true,sync:true,ctype:'candles',
 view:'chart',hwin:900,hpal:'classic',hgain:1,hcob:true,hbbo:true,hbub:true,hvol:true};   /* HEATMAPA: widok, okno (s), paleta, kontrast, warstwy */
const UNAVAIL_PROD={granite:'Granite TTM: linia prognozy nie jest podłączona do API na tym ekranie (stan modelu – PLAN · MODELE / Modele)',mcTp:'Monte Carlo przy TP: wynik PMW-MC-1 nie jest podłączony do API na tym ekranie'};
const UNAVAIL={bb:'BB na wykresie głównym: tylko w Chart Lab (silnik nie liczy tej linii)',iq:'IQ Gold Gann / IQ Star Lines: brak źródła – wymaga licencji MQL5 i mapowania eksportera',heat:'Heatmapa likwidacji: brak klucza dostawcy (CoinGlass) – nic nie jest symulowane'};
/* ===================== CHARTS · warstwy bota (strategie z koszyków, strefy z wybranego TF, Session Volume Profile) =====================
   Aplikacja: /api/v1/baskets/signals (FX_SMC, FX_SCALP, FX_HEDGE), /api/v1/bot-signals + /api/v1/setups (S01–S12), /api/v1/sh/signals (SH, TP1–TP3),
   /api/v1/market-zones?tf=<wybrany TF>, /api/v1/svp/* (PMW-SVP-1). */
const BK_ORDER=['FX_SMC','FX_SCALP','FX_HEDGE','LEGACY','SH'];
const BK_INFO={FX_SMC:['KOSZYK FX_SMC','SMC · FOREX / MT5'],FX_SCALP:['KOSZYK FX_SCALP','SCALP · FOREX / MT5'],FX_HEDGE:['KOSZYK FX_HEDGE','HEDGING · plany ochrony'],
 LEGACY:['S01–S12','dotychczasowe strategie złota (LEGACY)'],SH:['SH','SCALPING / HEDGING · TP1–TP3']};
const BK_COL={FX_SMC:'207,198,255',FX_SCALP:'190,228,206',FX_HEDGE:'160,170,190',LEGACY:'236,239,245',SH:'232,214,160'};
const BASKET_OF=sid=>sid.startsWith('FX_SMC')?'FX_SMC':sid.startsWith('FX_SCALP')?'FX_SCALP':sid.startsWith('FX_HEDGE')?'FX_HEDGE':sid.startsWith('SH_')?'SH':'LEGACY';
const SMETA={};function rebuildMeta(){for(const k in SMETA)delete SMETA[k];for(const bk of BK_ORDER)for(const m of (BOTVM.meta[bk]||[]))SMETA[m.id]={...m,bk};}
const STR={on:new Set(),sel:null,open:{FX_SMC:true,FX_SCALP:true,FX_HEDGE:false,LEGACY:true,SH:true}};
const RES_PL={OTWARTY:'OTWARTY',SL:'SL',TIMEOUT:'CZAS MINĄŁ',TP1:'TP1',TP2:'TP2',TP3:'TP3'};
const resPL=r=>RES_PL[r]||r.replace('SL_PO_','SL po ').replace('TIMEOUT_PO_','czas po ');
function idxOf(d,t){if(!d.length||t<d[0].t)return -1;let lo=0,hi=d.length-1;while(lo<hi){const m=(lo+hi+1)>>1;if(d[m].t<=t)lo=m;else hi=m-1;}return lo;}
function stratAvail(sid){const m=SMETA[sid];if(!m)return 'brak w rejestrze';if(m.bk==='FX_HEDGE')return 'plan ochrony otwartej ekspozycji – nie generuje sygnałów wejścia';
 if(m.bk==='LEGACY'&&CH.asset!=='XAUUSD')return 'S01–S12 tylko XAUUSD (bot: UNSUPPORTED_ASSET)';
 if(m.bk==='SH'&&CH.asset==='BTC')return 'SH zablokowany w konfiguracji bota: '+(m.status.BTC||'').split('–')[0].trim();
 const st=(BOTVM.states[CH.asset]||{})[sid];if(st&&st.un)return 'brak danych wejściowych: '+st.un;return null;}
function botIndex(){const d=CH.data,list=[];
 for(const s of BOTVM.sig[CH.asset]||[]){const onTf=s.src==='SH'?TFSEC[CH.tf]<=900:s.tf===CH.tf;if(!onTf)continue;const i=idxOf(d,s.t);if(i<0||(s.src!=='SH'&&d[i].t!==s.t))continue;
  list.push({...s,key:s.sid+'|'+s.t,idx:i,eidx:Math.max(i,idxOf(d,s.et)),bk:BASKET_OF(s.sid)});}
 CH.bsig=list;const Z=(BOTVM.zones[CH.asset]||{})[CH.tf];CH.bzones=Z?Z.map(z=>({...z,i0:Math.max(0,idxOf(d,z.t0)),i1:z.t1?Math.max(0,idxOf(d,z.t1)):null})):null;CH.svpKey='';}
const sigVisible=s=>L.strat&&STR.on.has(s.sid)&&!stratAvail(s.sid);
function pickPlan(){const vis=(CH.bsig||[]).filter(sigVisible);let G=STR.sel?vis.find(s=>s.key===STR.sel):null;if(!G)G=vis.filter(s=>s.res==='OTWARTY').pop()||vis[vis.length-1]||null;CH.sig=G;}
/* ---- Session Volume Profile (port PMW-SVP-1, zgodność z svp/engine.py sprawdzona 44/44) ---- */
const SVP_BINS={XAUUSD:[10,25,50,100,200],BTC:[500,1000,2000,5000]};
const svpBinTicks=()=>CH.asset==='BTC'?L.svpBinB:L.svpBinX;
const svpProfile=()=>L.svpProf==='AUTO'?(CH.asset==='BTC'?'LAB_BTC_REFERENCE_V1':'LAB_XAU_REFERENCE_V1'):L.svpProf;
function svpRecalc(){const d=CH.data;if(!d.length)return;const sec=TFSEC[CH.tf],prof=svpProfile(),key=[CH.asset,CH.tf,prof,svpBinTicks(),L.svpVa,JSON.stringify(L.svpOff),d.length,d[0].t].join('|');
 if(CH.svpKey===key)return;CH.svpKey=key;CH.svpS=null;CH.svpMsg=null;
 if(sec>3600){CH.svpMsg=`Profil sesyjny liczony jest na TF ≤ H1 – świeca ${CH.tf} jest dłuższa niż sesja.`;return;}
 const closed=d.filter(b=>b.closed),asOf=closed[closed.length-1].t+sec*1000;
 CH.svpS=svpWindows(prof,d[0].t,asOf+sec*1000).filter(w=>!L.svpOff[w.session]&&w.start<asOf).map(w=>({...svpCompute(closed,sec,w.start,w.end,asOf,{tick:.01,binTicks:svpBinTicks(),va:L.svpVa,label:w.session,mode:w.end>asOf?'LIVE':'SESSION'}),local_date:w.local_date,session:w.session,tz:w.tz})).filter(p=>p.status!=='NO_DATA');}
/* K5: VISIBLE z API bota dla instrumentu silnika (XAUUSD): zapytanie po 1,2 s bez zmiany zakresu (API: najwyżej raz na sekundę), wynik trzymany
   dla tego samego klucza; do czasu odpowiedzi – poprzedni wynik API tego instrumentu / TF. BTC i tryb testowy: port 1:1 (svpPort.js, 27/27). */
const VPA={key:null,res:null,want:null,timer:0,ctx:null};
function svpVisibleApi(closed,sec){const t0=closed[0].t,t1=closed[closed.length-1].t+sec*1000,ctx=CH.asset+'|'+CH.tf+'|'+svpBinTicks()+'|'+L.svpVa,key=ctx+'|'+t0+'|'+t1;
 if(VPA.key===key)return VPA.res;if(VPA.want!==key){VPA.want=key;clearTimeout(VPA.timer);VPA.timer=setTimeout(()=>{const k=VPA.want;
  env.visible({tf:CH.tf,t0,t1,bin:svpBinTicks(),va:L.svpVa}).then(r=>{if(r&&VPA.want===k){VPA.key=k;VPA.res=r;VPA.ctx=ctx;}else if(VPA.want===k)VPA.want=null;}).catch(()=>{if(VPA.want===k)VPA.want=null;});},1200);}
 return VPA.ctx===ctx?VPA.res:null;}
function svpVisible(start,end){const d=CH.data,sec=TFSEC[CH.tf],e=Math.min(end,d.length-1);if(e-start<3)return null;const closed=d.slice(start,e);
 if(env.visible&&!CH.frozen&&CH.asset==='XAUUSD')return svpVisibleApi(closed,sec);
 return svpCompute(closed,sec,closed[0].t,closed[closed.length-1].t+sec*1000,closed[closed.length-1].t+sec*1000,{tick:.01,binTicks:svpBinTicks(),va:L.svpVa,mode:'VISIBLE'});}
/* ---- rysowanie (wywoływane z drawMain wewnątrz obszaru ceny) ---- */
const ZT={FVG_BULL:['fvg','FVG ▲'],FVG_BEAR:['fvg','FVG ▼'],OB_BULL:['ob','OB ▲'],OB_BEAR:['ob','OB ▼'],DEMAND:['sd','POPYT'],SUPPLY:['sd','PODAŻ'],SR_SUPPORT:['sr','WSPARCIE'],SR_RESISTANCE:['sr','OPÓR'],EQH:['liq','EQH'],EQL:['liq','EQL']};
const ZST_PL={ACTIVE:'AKTYWNA',TESTED:'TESTOWANA',PRELIMINARY:'WSTĘPNA',INVALIDATED:'UNIEWAŻNIONA',EXPIRED:'WYGASŁA'};
function drawBotLayers(ctx,g,box){const {R,X,Y,cw,start,end,priceB}=g,d=CH.data,F9='9px "Helvetica Neue",Helvetica,Arial,sans-serif',F10='10px "Helvetica Neue",Helvetica,Arial,sans-serif';
 const seg=(x0,x1,p,col,dash,w)=>{const y=Math.round(Y(p))+.5;if(y<R.t||y>priceB)return y;ctx.strokeStyle=col;ctx.lineWidth=w||1;ctx.setLineDash(dash||[]);ctx.beginPath();ctx.moveTo(x0,y);ctx.lineTo(x1,y);ctx.stroke();ctx.setLineDash([]);ctx.lineWidth=1;return y;};
 const tag=(x,y,txt,col,right)=>{if(y<R.t||y>priceB)return;ctx.font=F9;const tw=ctx.measureText(txt).width+10;const xx=right?x-tw:x;ctx.fillStyle='rgba(3,4,8,.82)';ctx.fillRect(xx,y-7,tw,14);ctx.fillStyle=col;ctx.textAlign='left';ctx.fillText(txt,xx+5,y);ctx.font=F10;};
 /* 1. strefy bota – wyłącznie z wybranego TF */
 if(CH.bzones)for(const z of CH.bzones){const live=z.st!=='INVALIDATED'&&z.st!=='EXPIRED';if(!live&&!L.mzHist)continue;const [k,lab]=ZT[z.ty]||['mz',z.ty];if(!((L.mz&&z.v&&live)||L[k]))continue;
  const bull=/BULL|DEMAND|SUPPORT|EQL/.test(z.ty),a=live?1:.45;box(z.i0,z.lo,z.up,bull?`rgba(214,224,246,${.075*a})`:`rgba(140,148,170,${.10*a})`,live?`rgba(${bull?'214,224,246':'160,168,188'},.32)`:null,`${lab} · ${CH.tf}${z.q!=null?' · Q '+Math.round(z.q):''}${live?(z.st==='TESTED'?' · TESTOWANA':''):' · '+ZST_PL[z.st]}`,live?null:z.i1);}
 /* 2. Session Volume Profile */
 if(L.svpS&&CH.svpS)for(const P of CH.svpS){const i0=Math.max(0,idxOf(d,P.start)),i1=idxOf(d,Math.min(P.end,P.as_of)-1);if(i1<start||i0>=end||i1<0)continue;
  const xa=X(i0)-cw/2,xb=X(i1)+cw/2,xl=Math.max(R.l,xa),bin=P.bin_size,mxw=Math.max(...P.hist.map(h=>h[1])),wmax=Math.max(18,Math.min(180,(xb-xa)*.85)),dev=P.state==='DEVELOPING';
  ctx.fillStyle='rgba(160,170,200,.025)';ctx.fillRect(xl,Y(P.high),Math.max(0,xb-xl),Y(P.low)-Y(P.high));ctx.setLineDash(dev?[3,3]:[]);ctx.strokeStyle='rgba(170,180,210,.18)';ctx.strokeRect(Math.round(xl)+.5,Math.round(Y(P.high))+.5,Math.round(Math.max(0,xb-xl)),Math.round(Y(P.low)-Y(P.high)));ctx.setLineDash([]);
  for(const [kk,w] of P.hist){const p0=kk*bin,y0=Y(p0+bin),y1=Y(p0);if(y1<R.t||y0>priceB)continue;const inVa=p0>=P.val-1e-9&&p0<P.vah-1e-9,poc=Math.abs((kk+.5)*bin-P.poc)<bin/2;
   ctx.fillStyle=poc&&L.vpPoc?'rgba(236,226,190,.62)':inVa&&L.vpVa?'rgba(200,210,232,.24)':'rgba(200,210,232,.10)';const x0=xa,ww=w/mxw*wmax;if(x0+ww<R.l)continue;ctx.fillRect(Math.max(R.l,x0),y0,Math.max(1,x0+ww-Math.max(R.l,x0)),Math.max(1,y1-y0-.4));}
  if(L.vpPoc){const y=seg(xl,xb,P.poc,'rgba(236,226,190,.85)',[],1.2);if(L.labels)tag(Math.min(xb,R.r)-2,y,'POC '+fmtP(P.poc),'rgba(236,226,190,.95)',true);}
  if(L.vpVa){seg(xl,xb,P.vah,'rgba(180,192,220,.6)',[4,3]);seg(xl,xb,P.val,'rgba(180,192,220,.6)',[4,3]);}
  if(L.vpHvn)for(const p of P.hvn)seg(xl,Math.min(xb,xl+wmax*.9),p,'rgba(220,226,236,.45)',[1,2]);if(L.vpLvn)for(const p of P.lvn)seg(xl,Math.min(xb,xl+wmax*.6),p,'rgba(120,130,150,.6)',[1,3]);
  if(L.labels&&xb-xl>40){const dd=P.local_date;ctx.font=F9;ctx.fillStyle='rgba(200,206,218,.8)';ctx.textAlign='left';ctx.fillText(`${P.session} ${dd.slice(8)}.${dd.slice(5,7)} · ${dev?'W TOKU':'ZAMKNIĘTA'}${P.status==='PARTIAL'?' · CZĘŚCIOWA':''}`,xl+4,Y(P.high)-7);ctx.font=F10;}}
 /* 3. strategie bota: markery + plan (entry, SL, TP1–TP3) */
 if(!L.strat||!CH.bsig)return;const vis=CH.bsig.filter(sigVisible);
 let lv=!L.plan?[]:L.stratLv==='all'?vis.slice():L.stratLv==='last'?Object.values(vis.reduce((o,s)=>(o[s.sid]=s,o),{})):[];if(CH.sig&&!lv.includes(CH.sig))lv.push(CH.sig);
 for(const s of lv){if(s.eidx<start||s.idx>=end)continue;const sel=s===CH.sig,col=BK_COL[s.bk],open=s.res==='OTWARTY',x0=Math.max(R.l,X(s.idx)-cw/2),x1=open?R.r:Math.min(R.r,X(s.eidx)+cw/2),ye=Y(s.e),last=s.tp[s.tp.length-1];
  ctx.fillStyle=`rgba(170,215,190,${sel?.08:.035})`;ctx.fillRect(x0,Math.min(ye,Y(last)),x1-x0,Math.abs(Y(last)-ye));ctx.fillStyle=`rgba(208,138,138,${sel?.09:.04})`;ctx.fillRect(x0,Math.min(ye,Y(s.sl)),x1-x0,Math.abs(Y(s.sl)-ye));
  const ya=sel?.95:.55;const yE=seg(x0,x1,s.e,`rgba(${col},${ya})`,[],sel?1.4:1),yS=seg(x0,x1,s.sl,`rgba(222,150,150,${ya})`,[5,3]);const yT=s.tp.map((p,j)=>seg(x0,x1,p,`rgba(178,226,200,${s.hit.includes('TP'+(j+1))?ya:ya*.75})`,[3,3]));
  if(s.inv!=null&&sel)seg(x0,x1,s.inv,'rgba(160,166,178,.5)',[2,4]);
  if(sel||L.stratLv!=='all'){const r_=Math.abs(s.e-s.sl)||1;tag(x1-2,yE,`${s.sid.replace('FX_','')} ${s.sd>0?'LONG':'SHORT'} · WEJŚCIE ${fmtP(s.e)}`,`rgba(${col},1)`,true);tag(x1-2,yS,`SL ${fmtP(s.sl)}${s.res.startsWith('SL')?' ✕':''}`,'rgba(232,170,170,1)',true);
   s.tp.forEach((p,j)=>tag(x1-2,yT[j],`TP${j+1} ${fmtP(p)} · ${(Math.abs(p-s.e)/r_).toFixed(1)}R${s.hit.includes('TP'+(j+1))?' ✓':''}`,'rgba(190,232,208,1)',true));
   if(s.tp.length<3&&sel)tag(x1-2,yT[yT.length-1]+(s.sd>0?-16:16),'TP3 – brak w kontrakcie tej strategii','rgba(150,156,168,1)',true);}}
 for(const s of CH.bsig)s._mx=null;
 for(const s of vis){if(s.idx<start||s.idx>=end)continue;const x=X(s.idx),up=s.sd>0,y=up?Y(d[s.idx].l)+11:Y(d[s.idx].h)-11,sel=s===CH.sig,sz=sel?6.5:4.4,col=BK_COL[s.bk];s._mx=x;s._my=y;
  ctx.fillStyle=`rgba(${col},${s.res==='OTWARTY'?.6+.4*Math.sin(performance.now()/380):.9})`;ctx.beginPath();if(up){ctx.moveTo(x,y-sz);ctx.lineTo(x-sz,y+sz);ctx.lineTo(x+sz,y+sz);}else{ctx.moveTo(x,y+sz);ctx.lineTo(x-sz,y-sz);ctx.lineTo(x+sz,y-sz);}ctx.closePath();ctx.fill();
  if(sel){ctx.strokeStyle='rgba(255,255,255,.9)';ctx.beginPath();ctx.arc(x,y,sz+4,0,6.283);ctx.stroke();}
  if(L.labels&&cw>5){ctx.font='8px "Helvetica Neue",Helvetica,Arial,sans-serif';ctx.fillStyle=`rgba(${col},.85)`;ctx.textAlign='center';ctx.fillText(s.sid.replace('FX_SMC_','SMC').replace('FX_SCALP_','SC').replace('SH_SCALPING','SH·S').replace('SH_HEDGING','SH·H'),x,up?y+sz+9:y-sz-8);ctx.font=F10;}}}
function hitSignal(px,py){let best=null,bd=14;for(const s of (CH.bsig||[]).filter(sigVisible)){if(s._mx==null)continue;const dd=Math.hypot(s._mx-px,s._my-py);if(dd<bd){bd=dd;best=s;}}return best;}
/* ----- wskaźniki (te same wzory co silnik: EMA, RSI, MACD, ATR, SAR Wilder, AVWAP ±σ) ----- */
function ema(a,n){const k=2/(n+1),o=[];let e=null;for(let i=0;i<a.length;i++){if(i<n-1){o.push(null);continue;}if(e===null){let s=0;for(let j=i-n+1;j<=i;j++)s+=a[j];e=s/n;}else e=a[i]*k+e*(1-k);o.push(e);}return o;}
function rsiF(c,n=14){const o=[null];let g=0,l=0;for(let i=1;i<c.length;i++){const d=c[i]-c[i-1];if(i<=n){g+=Math.max(d,0);l+=Math.max(-d,0);o.push(i===n?100-100/(1+g/(l||1e-9)):null);if(i===n){g/=n;l/=n;}}else{g=(g*(n-1)+Math.max(d,0))/n;l=(l*(n-1)+Math.max(-d,0))/n;o.push(100-100/(1+g/(l||1e-9)));}}return o;}
function atrF(d,n=14){const o=[];let a=null;for(let i=0;i<d.length;i++){const tr=i?Math.max(d[i].h-d[i].l,Math.abs(d[i].h-d[i-1].c),Math.abs(d[i].l-d[i-1].c)):d[i].h-d[i].l;a=a===null?tr:(a*(n-1)+tr)/n;o.push(i>=n-1?a:null);}return o;}
function sarF(d,st=.02,mx=.2){const o=[];if(d.length<2)return o;let up=d[1].c>=d[0].c,af=st,ep=up?d[0].h:d[0].l,s=up?d[0].l:d[0].h;o.push(null);
 for(let i=1;i<d.length;i++){s=s+af*(ep-s);if(up){s=Math.min(s,d[i-1].l,d[Math.max(0,i-2)].l);if(d[i].l<s){up=false;s=ep;ep=d[i].l;af=st;}else if(d[i].h>ep){ep=d[i].h;af=Math.min(mx,af+st);}}
  else{s=Math.max(s,d[i-1].h,d[Math.max(0,i-2)].h);if(d[i].h>s){up=true;s=ep;ep=d[i].h;af=st;}else if(d[i].l<ep){ep=d[i].l;af=Math.min(mx,af+st);}}o.push({v:s,up});}return o;}
function pivots(d,k=3){const P=[];for(let i=k;i<d.length-k;i++){let H=true,Lw=true;for(let j=1;j<=k;j++){if(d[i].h<=d[i-j].h||d[i].h<d[i+j].h)H=false;if(d[i].l>=d[i-j].l||d[i].l>d[i+j].l)Lw=false;}if(H)P.push({i,kind:'H',p:d[i].h});if(Lw)P.push({i,kind:'L',p:d[i].l});}return P;}
function volProfile(bars,bins){if(!bars.length)return null;let lo=Math.min(...bars.map(b=>b.l)),hi=Math.max(...bars.map(b=>b.h));const step=(hi-lo)/bins||1,H=new Array(bins).fill(0);
 for(const b of bars){const a=Math.floor((b.l-lo)/step),z=Math.min(bins-1,Math.floor((b.h-lo)/step));const per=b.v/Math.max(1,z-a+1);for(let j=Math.max(0,a);j<=z;j++)H[j]+=per;}
 let pi=0;H.forEach((v,j)=>{if(v>H[pi])pi=j;});const tot=H.reduce((a,b)=>a+b,0);let a=pi,z=pi,acc=H[pi];while(acc<tot*.7&&(a>0||z<bins-1)){const na=a>0?H[a-1]:-1,nz=z<bins-1?H[z+1]:-1;if(nz>=na){z++;acc+=H[z];}else{a--;acc+=H[a];}}
 const mean=tot/bins,hvn=[],lvn=[];for(let j=2;j<bins-2;j++){if(H[j]>H[j-1]&&H[j]>=H[j+1]&&H[j]>mean*1.35&&j!==pi)hvn.push(lo+(j+.5)*step);if(H[j]<H[j-1]&&H[j]<=H[j+1]&&H[j]<mean*.55)lvn.push(lo+(j+.5)*step);}
 return {lo,hi,step,H,max:Math.max(...H),poc:lo+(pi+.5)*step,val:lo+a*step,vah:lo+(z+1)*step,hvn:hvn.slice(0,4),lvn:lvn.slice(0,4)};}
function computeAll(){const d=CH.data,c=d.map(b=>b.c),atr=atrF(d);const e12=ema(c,12),e26=ema(c,26),ml=c.map((_,i)=>e12[i]!=null&&e26[i]!=null?e12[i]-e26[i]:null);
 const IP=CH.iprof;let sig;if(IP.sig==='SMA'){sig=ml.map((_,i)=>{if(i<8)return null;let s=0;for(let j=i-8;j<=i;j++){if(ml[j]==null)return null;s+=ml[j];}return s/9;});}   /* profil silnika M02I: sygnał MACD = SMA(9) */
 else{const sigSrc=ml.map(v=>v??0),sg=ema(sigSrc.slice(25),9);sig=ml.map((_,i)=>i>=25&&sg[i-25]!=null?sg[i-25]:null);}
 const day=86400000;let anchor=-1,pv=0,vv=0,pv2=0;const av=[],up1=[],dn1=[],up2=[],dn2=[];
 d.forEach((b,i)=>{const dd=Math.floor(b.t/day);if(dd!==anchor){anchor=dd;pv=0;vv=0;pv2=0;}const tp=(b.h+b.l+b.c)/3;pv+=tp*b.v;vv+=b.v;pv2+=tp*tp*b.v;const m=pv/vv,sd=Math.sqrt(Math.max(0,pv2/vv-m*m));av.push(m);up1.push(m+sd);dn1.push(m-sd);up2.push(m+2*sd);dn2.push(m-2*sd);});
 const P=pivots(d,3),A=atr[atr.length-1]||1;const zones=[];const last=d.length-1;
 for(let i=2;i<d.length;i++){if(d[i].l>d[i-2].h&&d[i].l-d[i-2].h>A*.25)zones.push({k:'FVG',up:true,i0:i-1,lo:d[i-2].h,hi:d[i].l});if(d[i].h<d[i-2].l&&d[i-2].l-d[i].h>A*.25)zones.push({k:'FVG',up:false,i0:i-1,lo:d[i].h,hi:d[i-2].l});}
 for(let i=1;i<d.length-1;i++){const mv=d[i+1].c-d[i+1].o;if(Math.abs(mv)>A*1.6&&Math.sign(d[i].c-d[i].o)===-Math.sign(mv))zones.push({k:'OB',up:mv>0,i0:i,lo:d[i].l,hi:d[i].h});}
 const keep=(k,n)=>zones.filter(z=>z.k===k).filter(z=>{for(let j=z.i0+2;j<=last;j++){if(z.up?d[j].l<z.lo:d[j].h>z.hi)return false;}return true;}).slice(-n);
 const fvg=keep('FVG',5),ob=keep('OB',4);
 const ph=P.filter(p=>p.kind==='H').slice(-12),pl=P.filter(p=>p.kind==='L').slice(-12);
 const sr=[...ph.slice(-3).map(p=>({lo:p.p-A*.18,hi:p.p+A*.18,i0:p.i,res:true})),...pl.slice(-3).map(p=>({lo:p.p-A*.18,hi:p.p+A*.18,i0:p.i,res:false}))];
 const sd=[...ob.slice(-2).map(z=>({lo:z.lo-A*.3,hi:z.hi+A*.1,i0:z.i0-3,up:z.up}))];
 const liq=[];for(const arr of [ph,pl])for(let a=0;a<arr.length;a++)for(let b=a+1;b<arr.length;b++)if(Math.abs(arr[a].p-arr[b].p)<A*.15&&arr[b].i-arr[a].i>4)liq.push({p:(arr[a].p+arr[b].p)/2,i0:arr[a].i,i1:arr[b].i,k:arr[a].kind==='H'?'EQH':'EQL'});
 const brk=[];let lh=null,ll=null,trend=0;for(let i=0;i<d.length;i++){const ph_=P.find(p=>p.i===i-3&&p.kind==='H'),pl_=P.find(p=>p.i===i-3&&p.kind==='L');if(ph_)lh=ph_;if(pl_)ll=pl_;
  if(lh&&d[i].c>lh.p){brk.push({i,from:lh.i,p:lh.p,k:trend<0?'CHoCH':'BOS',up:true});trend=1;lh=null;}if(ll&&d[i].c<ll.p){brk.push({i,from:ll.i,p:ll.p,k:trend>0?'CHoCH':'BOS',up:false});trend=-1;ll=null;}}
 const mz=[...P.slice(-8).filter((_,j)=>j%2===0).map(p=>({lo:p.kind==='H'?p.p-A*.35:p.p,hi:p.kind==='H'?p.p:p.p+A*.35,i0:p.i,tf:['M1','M5','M15','M30'][p.i%4],up:p.kind==='L'}))];
 const lc=d[last].c;const ai={zone:[lc-A*.8,lc-A*.35],inv:lc-A*1.6,targets:[lc+A*1.2,lc+A*2.1]};
 const scalp={entry:lc-A*.9,sl:lc-A*2.6,tp:[lc+A*1.1,lc+A*2.2,lc+A*3.4]},hedge={entry:lc+A*1.6,sl:lc+A*3.2,tp:[lc-A*.4,lc-A*1.9,lc-A*3.0]};
 const dd=Math.floor(d[last].t/day),prev=d.filter(b=>Math.floor(b.t/day)===dd-1),today=d.filter(b=>Math.floor(b.t/day)===dd);
 const zmPrev=volProfile(prev.length?prev:d.slice(-60),24),zmDev=volProfile(today.length?today:d.slice(-20),24);
 const dOpen=today.length?today[0].o:lc,dHi=today.length?Math.max(...today.map(b=>b.h)):lc,dLo=today.length?Math.min(...today.map(b=>b.l)):lc,hv=A*Math.sqrt(86400/TFSEC[CH.tf])*.55;
 const pat={range:{i0:Math.max(0,last-46),i1:last-6,lo:Math.min(...d.slice(-46,-6).map(b=>b.l)),hi:Math.max(...d.slice(-46,-6).map(b=>b.h))},label:'formacja: podwójny szczyt (WATCH)',pi:ph.length?ph[ph.length-1].i:last};
 const gr=[];let gp=lc;for(let k=1;k<=10;k++){gp+=Math.sin(k*.7)*A*.12+A*.05;gr.push(gp);}
 /* K3: demonstracyjny sygnał S07, historia sygnałów i szanse modeli wzorca usunięte – sygnały i szanse wyłącznie z API (D1 §3.2, §3.7) */
 CH.ind={ema20:ema(c,IP.ema[0]),ema50:IP.ema[1]!=null?ema(c,IP.ema[1]):c.map(()=>null),rsi:rsiF(c,IP.rsi),macd:ml,sig,atr,sar:sarF(d),av,up1,dn1,up2,dn2,fvg,ob,sr,sd,liq:liq.slice(-4),brk:brk.slice(-6),mz,ai,scalp,hedge,zmPrev,zmDev,walls:{o:dOpen,h:dHi,l:dLo,hv},pat,granite:gr};}
function applySeries(anim){CH.offset=0;if(CH.data.length)computeAll();else CH.ind=null;CH.probs=VM.probs||PROBS0;botIndex();STR.sel=null;pickPlan();if(CH.data.length){const sl=CH.data.slice(-CH.view);CH.yMin=Math.min(...sl.map(c=>c.l));CH.yMax=Math.max(...sl.map(c=>c.h));}if(anim)CH.swap=0;loadKronos();}
function loadKronos(){const K=CH.kr,k=VM.kronos;if(!k){K.data=[];K.fc=null;return;}if(k.tf)K.tf=k.tf;if(k.on)K.on={...K.on,...k.on};K.role=k.role;K.emptyTxt=k.emptyTxt;K.data=k.candles||[];K.fc=k.forecast?{...k.forecast,created_at:new Date(k.forecast.created_at)}:null;if(k.state)K.state=k.state;K.anim=0;}
function setChartStatus(st){CH.status=st;const el=$('#ch-status');el.dataset.s=st;el.querySelector('.t').textContent={live:'MT5 POŁĄCZONY',loading:'ŁADOWANIE',offline:'ROZŁĄCZONO',stale:'DANE NIEAKTUALNE'}[st];}
function chartsConnect(){++CH.token;setChartStatus(VM.status||'loading');}
function chartsPlanet(cms){if(S.reduced){const k=SUB.p;return {move:0,rMul:1,op:1-smooth(k*2)};}
 return {move:easeIO3(seg(cms,0,800)),rMul:1+Math.pow(seg(cms,450,1050),2.2)*9,op:1-smooth(seg(cms,900,600))};}
function niceStep(x){const p=Math.pow(10,Math.floor(Math.log10(x))),m=x/p;return (m<1.5?1:m<3?2:m<7?5:10)*p;}
const dig=()=>ASSETS[CH.asset].d;function fmtP(v){return v==null?'—':v.toFixed(dig());}
function tzShift(){return CH.tz==='UTC'?0:CH.tz==='SERVER'?CH.serverOff*3600000:-new Date().getTimezoneOffset()*60000;}
function fmtT(t,full,tf){const d=new Date(t+tzShift()),pad=n=>String(n).padStart(2,'0');const dd=pad(d.getUTCDate())+'.'+pad(d.getUTCMonth()+1),hm=pad(d.getUTCHours())+':'+pad(d.getUTCMinutes());return (tf||CH.tf)==='D1'?dd:(full?dd+' '+hm:hm);}
function chartTick(now){/* aplikacja: świece i kwotowania na żywo przychodzą ze store przez setVM (bez losowania) */}
function rectOf(sel){const r=$(sel).getBoundingClientRect();return {l:r.left,t:r.top,r:r.right,b:r.bottom,w:r.width,h:r.height};}
function heikin(d){const o=[];let po=null,pc=null;for(const b of d){const c=(b.o+b.h+b.l+b.c)/4,op=po===null?(b.o+b.c)/2:(po+pc)/2;o.push({...b,o:op,c,h:Math.max(b.h,op,c),l:Math.min(b.l,op,c)});po=op;pc=c;}return o;}
/* ----- rysowanie: wykres główny ----- */
function drawMain(ctx,cms,dt,red){
 const R0=rectOf('#mc-plot');if(R0.w<40)return;if(!CH.data.length){$('#mc-read').innerHTML='';const sc=$('#sig-card');if(sc)sc.hidden=true;return;}const d=L.ctype==='heikin'?heikin(CH.data):CH.data,n=d.length,end=n-CH.offset,start=Math.max(0,end-CH.view),sl=d.slice(start,end);
 const axW=74,taH=22,paneH=Math.min(78,R0.h*.14),R={l:R0.l,r:R0.r-axW,t:R0.t+6,b:R0.b-taH};
 const panes=[];if(L.rsi)panes.push('rsi');if(L.macd)panes.push('macd');const pb=R.b-panes.length*(paneH+10),volH=L.volume?(pb-R.t)*.13:0,priceB=pb-volH-4;
 const cw=(R.r-R.l)/CH.view,X=i=>R.l+(i-(end-CH.view)+.5)*cw;
 const gridA=red?smooth(SUB.p*2-1):smooth(seg(cms,1150,600)),reveal=red?1:easeOut3(seg(cms,1200,750)),lineA=red?0:(1-smooth(seg(cms,1900,450)))*smooth(seg(cms,1150,200)),uiA=red?smooth(SUB.p*2-1):smooth(seg(cms,1900,500));
 CH.swap=Math.min(1,CH.swap+dt/.45);CH.flash=Math.max(0,CH.flash-dt/.6);
 let mn=Math.min(...sl.map(c=>c.l)),mx=Math.max(...sl.map(c=>c.h));const pad=(mx-mn)*.08;mn-=pad;mx+=pad;const k=1-Math.exp(-dt*8);CH.yMin=lerp(CH.yMin,mn,k);CH.yMax=lerp(CH.yMax,mx,k);
 const Y=v=>R.t+(CH.yMax-v)/(CH.yMax-CH.yMin)*(priceB-R.t);const dim=CH.status==='offline'?.35:CH.status==='loading'?0:1;const I=CH.ind;
 CH.geo={R,R0,X,Y,cw,start,end,priceB,pb,paneH,panes,axW};
 ctx.save();ctx.beginPath();ctx.rect(R0.l,R0.t,R0.w,R0.h);ctx.clip();ctx.font='10px "Helvetica Neue",Helvetica,Arial,sans-serif';ctx.textBaseline='middle';
 /* siatka + oś */
 const stp=niceStep((CH.yMax-CH.yMin)/6);ctx.globalAlpha=gridA;
 for(let v=Math.ceil(CH.yMin/stp)*stp;v<CH.yMax;v+=stp){const y=Math.round(Y(v))+.5;if(y<R.t||y>priceB)continue;if(L.grid){ctx.strokeStyle='rgba(200,210,230,.07)';ctx.setLineDash([1,5]);ctx.beginPath();ctx.moveTo(R.l,y);ctx.lineTo(R.r,y);ctx.stroke();ctx.setLineDash([]);}
  if(CH.offset===0&&Math.abs(y-Y(d[n-1].c))<14)continue;ctx.fillStyle=`rgba(137,139,145,${uiA})`;ctx.textAlign='left';ctx.fillText(fmtP(v),R.r+10,y);}
 ctx.strokeStyle='rgba(43,48,59,.9)';ctx.beginPath();ctx.moveTo(R.r+.5,R.t);ctx.lineTo(R.r+.5,R.b);ctx.moveTo(R.l,R.b+.5);ctx.lineTo(R.r,R.b+.5);ctx.stroke();
 const every=Math.max(1,Math.ceil(96/cw));ctx.textAlign='center';ctx.fillStyle=`rgba(137,139,145,${uiA})`;
 for(let i=start;i<end;i++){if(i%every)continue;const x=X(i);ctx.fillText(fmtT(d[i].t,false),x,R.b+12);if(L.grid){ctx.strokeStyle='rgba(200,210,230,.035)';ctx.beginPath();ctx.moveTo(Math.round(x)+.5,R.t);ctx.lineTo(Math.round(x)+.5,R.b);ctx.stroke();}}
 ctx.globalAlpha=1;
 if(CH.status==='loading'){const t=performance.now()/1000,xx=R.l+((t*.45)%1)*(R.r-R.l),gy=(R.t+priceB)/2,g=ctx.createLinearGradient(xx-220,0,xx+40,0);g.addColorStop(0,'rgba(220,226,236,0)');g.addColorStop(1,'rgba(220,226,236,.5)');ctx.strokeStyle=g;ctx.beginPath();ctx.moveTo(Math.max(R.l,xx-220),gy);ctx.lineTo(xx+40,gy);ctx.stroke();}
 const oa=uiA*dim,clipPrice=()=>{ctx.save();ctx.beginPath();ctx.rect(R.l,R.t,R.r-R.l,priceB-R.t);ctx.clip();};
 const box=(i0,lo,hi,fill,stroke,label,i1)=>{const x0=Math.max(R.l,X(i0)-cw/2),x1=i1!=null?X(i1)+cw/2:R.r;if(x1<R.l)return;const y0=Y(hi),y1=Y(lo);ctx.fillStyle=fill;ctx.fillRect(x0,y0,x1-x0,y1-y0);if(stroke){ctx.strokeStyle=stroke;ctx.strokeRect(Math.round(x0)+.5,Math.round(y0)+.5,Math.round(x1-x0),Math.round(y1-y0));}
  if(label&&L.labels){ctx.fillStyle='rgba(200,206,218,.75)';ctx.textAlign='left';ctx.font='9px "Helvetica Neue",Helvetica,Arial,sans-serif';ctx.fillText(label,x0+5,y0+8);ctx.font='10px "Helvetica Neue",Helvetica,Arial,sans-serif';}};
 const hline=(p,col,label,dash,w)=>{const y=Math.round(Y(p))+.5;if(y<R.t||y>priceB)return;ctx.strokeStyle=col;ctx.lineWidth=w||1;ctx.setLineDash(dash||[]);ctx.beginPath();ctx.moveTo(R.l,y);ctx.lineTo(R.r,y);ctx.stroke();ctx.setLineDash([]);ctx.lineWidth=1;
  if(label&&L.labels){ctx.fillStyle=col;ctx.textAlign='right';ctx.font='9px "Helvetica Neue",Helvetica,Arial,sans-serif';ctx.fillText(label,R.r-6,y-7);ctx.font='10px "Helvetica Neue",Helvetica,Arial,sans-serif';}};
 const series=(arr,col,w,dash)=>{ctx.strokeStyle=col;ctx.lineWidth=w||1;ctx.setLineDash(dash||[]);ctx.beginPath();let st=false;for(let i=start;i<end;i++){const v=arr[i];if(v==null){st=false;continue;}const x=X(i),y=Y(v);st?ctx.lineTo(x,y):ctx.moveTo(x,y);st=true;}ctx.stroke();ctx.setLineDash([]);ctx.lineWidth=1;};
 if(dim>0&&oa>0&&I){clipPrice();ctx.globalAlpha=oa;
  /* warstwy bota: strefy wybranego TF, Session Volume Profile, strategie z koszyków */
  svpRecalc();pickPlan();drawBotLayers(ctx,{R,X,Y,cw,start,end,priceB},box);
  /* profil widocznego zakresu (PMW-SVP-1 VISIBLE, siatka zakotwiczona) – po prawej */
  if(L.vp){const vp=svpVisible(start,end);CH.vp=vp&&vp.status!=='NO_DATA'?vp:null;if(CH.vp){const P=CH.vp,wmax=(R.r-R.l)*.18,mxw=Math.max(...P.hist.map(h=>h[1])),bin=P.bin_size;
   for(const [kk,w] of P.hist){const p0=kk*bin,y0=Y(p0+bin),y1=Y(p0);const inVa=p0>=P.val-1e-9&&p0<P.vah-1e-9;ctx.fillStyle=inVa&&L.vpVa?'rgba(200,210,230,.13)':'rgba(200,210,230,.06)';const ww=w/mxw*wmax;ctx.fillRect(R.r-ww,y0,ww,Math.max(1,y1-y0-.4));}
   if(L.vpVa){hline(P.vah,'rgba(170,182,206,.5)','VISIBLE VAH',[4,4]);hline(P.val,'rgba(170,182,206,.5)','VISIBLE VAL',[4,4]);}if(L.vpPoc)hline(P.poc,'rgba(236,226,190,.6)','VISIBLE POC '+fmtP(P.poc),[],1);}}else CH.vp=null;
  if(L.sessions&&CH.svpS)for(const P of CH.svpS){const i0=Math.max(0,idxOf(d,P.start)),i1=idxOf(d,Math.min(P.end,P.as_of)-1);if(i1<start||i0>=end)continue;ctx.setLineDash(P.state==='DEVELOPING'?[3,3]:[]);box(i0,P.low,P.high,'rgba(160,170,200,.035)','rgba(160,170,200,.22)',P.session+(P.state==='DEVELOPING'?' · W TOKU':''),i1);ctx.setLineDash([]);}
  if(L.walls){const W=I.walls;hline(W.o,'rgba(200,206,218,.5)','DAILY OPEN',[6,4]);hline(W.h,'rgba(200,206,218,.4)','DAILY HIGH',[2,4]);hline(W.l,'rgba(200,206,218,.4)','DAILY LOW',[2,4]);hline(W.o+W.hv,'rgba(160,172,200,.45)','WALL +1σ · HV_PROXY',[8,6]);hline(W.o-W.hv,'rgba(160,172,200,.45)','WALL −1σ · HV_PROXY',[8,6]);}
  if(L.zmap&&CH.svpS){const done=CH.svpS.filter(P=>P.state==='COMPLETED').pop(),dev=CH.svpS.find(P=>P.state==='DEVELOPING');if(done){hline(done.poc,'rgba(220,214,190,.6)',`${done.session} POC (poprzednia sesja)`,[]);hline(done.vah,'rgba(180,190,215,.45)','VAH',[3,3]);hline(done.val,'rgba(180,190,215,.45)','VAL',[3,3]);}if(dev)hline(dev.poc,'rgba(220,214,190,.4)',`${dev.session} POC rozwijający się`,[2,5]);}
  if(L.patterns){const P_=I.pat;ctx.setLineDash([4,3]);box(P_.range.i0,P_.range.lo,P_.range.hi,'rgba(0,0,0,0)','rgba(200,206,218,.3)','ZAKRES M5',P_.range.i1);ctx.setLineDash([]);if(P_.pi>=start){ctx.fillStyle='rgba(220,226,236,.8)';ctx.textAlign='center';ctx.font='9px "Helvetica Neue",Helvetica,Arial,sans-serif';ctx.fillText('◇ '+P_.label,X(P_.pi),Y(d[P_.pi].h)-14);ctx.font='10px "Helvetica Neue",Helvetica,Arial,sans-serif';}}
  if(L.avwap){if(['M1','M5'].includes(CH.tf)){series(I.av,'rgba(236,226,190,.75)',1.3);series(I.up1,'rgba(236,226,190,.3)',1,[4,4]);series(I.dn1,'rgba(236,226,190,.3)',1,[4,4]);series(I.up2,'rgba(236,226,190,.18)',1,[2,5]);series(I.dn2,'rgba(236,226,190,.18)',1,[2,5]);}}
  if(L.ema){series(I.ema20,'rgba(205,220,255,.75)',1.2);series(I.ema50,'rgba(160,170,195,.7)',1.2);}
  if(L.sar)for(let i=start;i<end;i++){const s=I.sar[i];if(!s)continue;ctx.fillStyle=s.up?'rgba(230,234,242,.8)':'rgba(140,148,166,.85)';ctx.fillRect(X(i)-1.2,Y(s.v)-1.2,2.4,2.4);}
  if(L.structure)for(const b of I.brk){if(b.i<start)continue;const y=Math.round(Y(b.p))+.5;ctx.strokeStyle=b.k==='CHoCH'?'rgba(236,226,190,.7)':'rgba(220,226,236,.55)';ctx.beginPath();ctx.moveTo(Math.max(R.l,X(b.from)),y);ctx.lineTo(X(b.i),y);ctx.stroke();ctx.fillStyle=ctx.strokeStyle;ctx.textAlign='center';ctx.font='9px "Helvetica Neue",Helvetica,Arial,sans-serif';ctx.fillText(b.k,(Math.max(R.l,X(b.from))+X(b.i))/2,y+(b.up?-8:9));ctx.font='10px "Helvetica Neue",Helvetica,Arial,sans-serif';}
  if(L.ai){const A_=I.ai;box(start,A_.zone[0],A_.zone[1],'rgba(200,190,255,.05)','rgba(200,190,255,.3)','AI: strefa wejścia');hline(A_.inv,'rgba(200,190,255,.6)','AI: unieważnienie',[5,4]);A_.targets.forEach((p,j)=>hline(p,'rgba(200,190,255,.5)','AI: cel '+(j+1),[2,4]));}
  if(CH.kr.mode!=='OFF'&&CH.kr.onChart&&CH.kr.on[CH.kr.tf]&&CH.kr.fc)hline(CH.kr.fc.pred_close_h,'rgba(186,170,255,.8)',`KRONOS ${CH.kr.tf} +${CH.kr.fc.horizon}`,[6,4],1.2);
  ctx.globalAlpha=1;ctx.restore();}
 /* linia zamknięć — wejście */
 if(lineA>0&&dim>0){ctx.save();ctx.globalAlpha=lineA*dim;ctx.strokeStyle='rgba(236,239,245,.85)';ctx.lineWidth=1.2;ctx.beginPath();const last=start+Math.floor(reveal*(end-start-1));for(let i=start;i<=last;i++){const x=X(i),y=Y(d[i].c);i===start?ctx.moveTo(x,y):ctx.lineTo(x,y);}ctx.stroke();
  if(reveal<1){const hx=X(last),hy=Y(d[last].c),g=ctx.createRadialGradient(hx,hy,0,hx,hy,26);g.addColorStop(0,'rgba(255,255,255,.95)');g.addColorStop(.25,'rgba(210,225,255,.35)');g.addColorStop(1,'rgba(210,225,255,0)');ctx.fillStyle=g;ctx.fillRect(hx-26,hy-26,52,52);}ctx.restore();}
 /* świece / linia / obszar + wolumen */
 if(dim>0){const vmax=Math.max(...sl.map(c=>c.v));
  if(L.ctype==='line'||L.ctype==='area'){const kk=red?smooth(SUB.p*2-1):smooth(seg(cms,1550,700));ctx.globalAlpha=kk*dim;ctx.beginPath();for(let i=start;i<end;i++){const x=X(i),y=Y(d[i].c);i===start?ctx.moveTo(x,y):ctx.lineTo(x,y);}ctx.strokeStyle='rgba(236,239,245,.9)';ctx.lineWidth=1.4;ctx.stroke();
   if(L.ctype==='area'){ctx.lineTo(X(end-1),priceB);ctx.lineTo(X(start),priceB);ctx.closePath();const g=ctx.createLinearGradient(0,R.t,0,priceB);g.addColorStop(0,'rgba(220,228,245,.16)');g.addColorStop(1,'rgba(220,228,245,0)');ctx.fillStyle=g;ctx.fill();}ctx.lineWidth=1;}
  for(let i=start;i<end;i++){const c=d[i],j=(i-start)/Math.max(1,end-start);let kk=red?smooth(SUB.p*2-1):easeOut3(seg(cms,1550+j*550,350));kk*=red?1:clamp(CH.swap*1.6-j*.6);if(kk<=0)continue;
   const x=X(i),up=c.c>=c.o,bw=Math.max(1,cw*.62),forming=!CH.data[i].closed;ctx.globalAlpha=kk*dim*(forming?.75+.25*Math.sin(performance.now()/300):1);
   if(L.ctype==='candles'||L.ctype==='hollow'||L.ctype==='heikin'){const yc=Y(c.c),yo=lerp(yc,Y(c.o),kk),yh=lerp(yc,Y(c.h),kk),yl=lerp(yc,Y(c.l),kk);
    ctx.strokeStyle=up?'rgba(236,239,245,.75)':'rgba(138,145,158,.95)';ctx.beginPath();ctx.moveTo(Math.round(x)+.5,yh);ctx.lineTo(Math.round(x)+.5,yl);ctx.stroke();
    const top=Math.min(yc,yo),hb=Math.max(1,Math.abs(yc-yo)),hollow=L.ctype==='hollow'?up:!up;
    if(!hollow){ctx.fillStyle=up?'rgba(236,239,245,.92)':'rgba(138,145,158,.9)';ctx.fillRect(x-bw/2,top,bw,hb);}else{ctx.fillStyle='#000';ctx.fillRect(x-bw/2,top,bw,hb);ctx.strokeRect(Math.round(x-bw/2)+.5,Math.round(top)+.5,Math.max(0,Math.round(bw)-1),Math.max(0,Math.round(hb)-1));}}
   if(L.volume){const vh=c.v/vmax*volH*kk;ctx.fillStyle=up?'rgba(220,226,236,.13)':'rgba(138,145,158,.10)';ctx.fillRect(x-bw/2,priceB+4+volH-vh,bw,vh);}}
  ctx.globalAlpha=1;
  if(L.granite&&CH.offset===0){const gr=CH.ind.granite;ctx.globalAlpha=oa;ctx.strokeStyle='rgba(170,200,230,.7)';ctx.setLineDash([2,3]);ctx.beginPath();ctx.moveTo(X(n-1),Y(d[n-1].c));gr.forEach((p,j)=>ctx.lineTo(X(n-1)+(j+1)*cw,Y(p)));ctx.stroke();ctx.setLineDash([]);
   ctx.fillStyle='rgba(170,200,230,.85)';ctx.textAlign='left';ctx.font='9px "Helvetica Neue",Helvetica,Arial,sans-serif';ctx.fillText('GRANITE TTM · punkt',X(n-1)+4,Y(gr[gr.length-1])-10);ctx.font='10px "Helvetica Neue",Helvetica,Arial,sans-serif';ctx.globalAlpha=1;}
  if(CH.offset===0){const lc=d[n-1],y=Math.round(Y(lc.c))+.5,stale=CH.status==='stale';ctx.globalAlpha=uiA*dim;ctx.setLineDash([3,4]);ctx.strokeStyle=stale?'rgba(183,167,122,.55)':'rgba(220,226,236,.4)';ctx.beginPath();ctx.moveTo(R.l,y);ctx.lineTo(R.r,y);ctx.stroke();ctx.setLineDash([]);
   if(CH.flash>0&&!red){const g=ctx.createRadialGradient(X(n-1),y,0,X(n-1),y,22);g.addColorStop(0,`rgba(255,255,255,${.6*CH.flash})`);g.addColorStop(1,'rgba(255,255,255,0)');ctx.fillStyle=g;ctx.fillRect(X(n-1)-22,y-22,44,44);}
   ctx.fillStyle='#06080c';ctx.fillRect(R.r+1,y-11,axW-2,22);ctx.strokeStyle=stale?'#b7a77a':`rgba(191,199,218,${.6+.4*CH.flash})`;ctx.strokeRect(R.r+1.5,y-10.5,axW-3,21);ctx.fillStyle=stale?'#d9c99a':'#fff';ctx.textAlign='left';ctx.fillText(fmtP(lc.c),R.r+8,y+.5);ctx.globalAlpha=1;}}
 /* panele RSI / MACD */
 panes.forEach((pn,pi)=>{const t0=pb+10+pi*(paneH+10),t1=t0+paneH;ctx.globalAlpha=uiA*Math.max(dim,.35);ctx.strokeStyle='rgba(43,48,59,.9)';ctx.strokeRect(R.l+.5,t0+.5,R.r-R.l,paneH);
  ctx.fillStyle='rgba(137,139,145,.9)';ctx.textAlign='left';ctx.font='9px "Helvetica Neue",Helvetica,Arial,sans-serif';
  if(pn==='rsi'){const yv=v=>t1-(v/100)*paneH;ctx.fillText('RSI '+CH.iprof.rsi,R.l+6,t0+9);[70,30].forEach(v=>{ctx.strokeStyle='rgba(200,210,230,.12)';ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(R.l,Math.round(yv(v))+.5);ctx.lineTo(R.r,Math.round(yv(v))+.5);ctx.stroke();ctx.setLineDash([]);ctx.fillText(v,R.r+10,yv(v));});
   ctx.strokeStyle='rgba(220,228,245,.8)';ctx.beginPath();let st=false;for(let i=start;i<end;i++){const v=CH.ind.rsi[i];if(v==null)continue;const x=X(i),y=yv(v);st?ctx.lineTo(x,y):ctx.moveTo(x,y);st=true;}ctx.stroke();}
  else{const vals=[];for(let i=start;i<end;i++){const a=CH.ind.macd[i],b=CH.ind.sig[i];if(a!=null)vals.push(Math.abs(a));if(b!=null)vals.push(Math.abs(b));}const m=Math.max(...vals,1e-9),yv=v=>(t0+t1)/2-v/m*paneH*.45;
   ctx.fillText('MACD 12 · 26 · 9',R.l+6,t0+9);for(let i=start;i<end;i++){const a=CH.ind.macd[i],b=CH.ind.sig[i];if(a==null||b==null)continue;const hv=a-b;ctx.fillStyle=hv>=0?'rgba(220,226,236,.28)':'rgba(138,145,158,.28)';const y0=yv(0),y1=yv(hv);ctx.fillRect(X(i)-cw*.3,Math.min(y0,y1),cw*.6,Math.abs(y1-y0));}
   const ln=(arr,col)=>{ctx.strokeStyle=col;ctx.beginPath();let st=false;for(let i=start;i<end;i++){const v=arr[i];if(v==null)continue;const x=X(i),y=yv(v);st?ctx.lineTo(x,y):ctx.moveTo(x,y);st=true;}ctx.stroke();};ln(CH.ind.macd,'rgba(220,228,245,.85)');ln(CH.ind.sig,'rgba(150,158,176,.85)');}
  ctx.font='10px "Helvetica Neue",Helvetica,Arial,sans-serif';ctx.globalAlpha=1;});
 if(CH.status==='offline'||CH.status==='loading'){ctx.globalAlpha=uiA;ctx.fillStyle='#898b91';ctx.textAlign='center';ctx.font='9px "Helvetica Neue",Helvetica,Arial,sans-serif';ctx.fillText(CH.status==='offline'?'R O Z Ł Ą C Z O N O   ·   O S T A T N I E   Z N A N E   D A N E':'Ł A D O W A N I E   D A N Y C H',(R.l+R.r)/2,(R.t+priceB)/2+(CH.status==='loading'?22:0));ctx.globalAlpha=1;}
 /* krzyż */
 const hv=CH.hover;let hi_=n-1-CH.offset;
 if(hv&&SUB.state==='on'&&dim>0&&hv.x>R.l&&hv.x<R.r&&hv.y>R.t&&hv.y<R.b){hi_=clamp(Math.floor((hv.x-R.l)/cw)+(end-CH.view),start,end-1);const x=Math.round(X(hi_))+.5,y=Math.round(hv.y)+.5;ctx.strokeStyle='rgba(220,226,236,.32)';ctx.beginPath();ctx.moveTo(x,R.t);ctx.lineTo(x,R.b);ctx.moveTo(R.l,y);ctx.lineTo(R.r,y);ctx.stroke();
  if(hv.y<priceB){const v=CH.yMax-(hv.y-R.t)/(priceB-R.t)*(CH.yMax-CH.yMin);ctx.fillStyle='#11151d';ctx.fillRect(R.r+1,y-11,axW-2,22);ctx.fillStyle='#dfe3eb';ctx.textAlign='left';ctx.fillText(fmtP(v),R.r+8,y);}
  const tl=fmtT(d[hi_].t,true),tw=ctx.measureText(tl).width+18;ctx.fillStyle='#11151d';ctx.fillRect(x-tw/2,R.b+1,tw,20);ctx.fillStyle='#dfe3eb';ctx.textAlign='center';ctx.fillText(tl,x,R.b+11);}
 ctx.restore();
 const hc=d[hi_],o=$('#mc-read');if(hc&&I){const chg=(hc.c-hc.o)/hc.o*100,f=v=>v==null?'—':fmtP(v);
  o.innerHTML=`<span>O<b>${f(hc.o)}</b>H<b>${f(hc.h)}</b>L<b>${f(hc.l)}</b>C<b>${f(hc.c)}</b><b>${chg>=0?'+':''}${chg.toFixed(2)}%</b></span>`+
  (L.ema?`<span>EMA ${CH.iprof.ema[0]}<b>${f(I.ema20[hi_])}</b>${CH.iprof.ema[1]!=null?`EMA ${CH.iprof.ema[1]}<b>${f(I.ema50[hi_])}</b>`:''}</span>`:'')+(L.avwap&&['M1','M5'].includes(CH.tf)?`<span>AVWAP<b>${f(I.av[hi_])}</b></span>`:'')+
  (L.rsi?`<span>RSI<b>${I.rsi[hi_]!=null?I.rsi[hi_].toFixed(1):'—'}</b></span>`:'')+(L.atr?`<span>ATR 14<b>${f(I.atr[hi_])}</b></span>`:'')+(L.vp&&CH.vp?`<span>POC<b>${f(CH.vp.poc)}</b></span>`:'');}
 $('#mc-title').textContent=`${ASSETS[CH.asset].sym} · ${CH.tf}`;
 placeCard(R,uiA);
 /* odczyt sygnałów strategii pod kursorem */ if(hv&&CH.bsig){const ms=CH.bsig.filter(g=>g.idx===hi_&&sigVisible(g));if(ms.length)$('#mc-read').innerHTML+=`<span>SYGNAŁ<b>${ms.map(m=>`${m.sid} ${m.sd>0?'LONG':'SHORT'} · ${resPL(m.res)}`).join(' | ')}</b></span>`;}
}
function placeCard(R,uiA){const el=$('#sig-card');el.hidden=!(L.card&&CH.sig);if(el.hidden)return;const host=$('.cs-win.main').getBoundingClientRect();el.style.left=(R.l-host.left+10)+'px';el.style.top=(R.t-host.top+6)+'px';el.style.opacity=uiA;
 const G=CH.sig,key=CH.asset+CH.tf+G.key+CH.cardMin;if(el.dataset.key===key)return;el.dataset.key=key;const M=SMETA[G.sid]||{},P=CH.probs,pc=v=>v==null?'—':Math.round(v*100)+'%',R_=Math.abs(G.e-G.sl)||1,pad=n=>String(n).padStart(2,'0');
 const row=(o,v)=>{const ok=o.state==='READY'&&v!=null;return `<div class="pm ${ok?'':'na'}" title="${o.task} · ${o.src}"><span class="nm">${o.name}</span><span class="v">${ok?pc(v):'—'}</span><span class="bar">${ok?`<i style="width:${v*100}%"></i>`:''}</span><span class="st">${ok?(o.cal==='CALIBRATED_DEV'?'SKALIBROWANY · ':'')+'GOTOWY':({NOT_TRAINED:'NIEWYTRENOWANY',DISABLED:'WYŁĄCZONY',STALE:'NIEAKTUALNY',ERROR:'BŁĄD',NO_DATA:'BRAK DANYCH'}[o.state]||o.state)} · ${o.src}</span></div>`;};
 const t=new Date(G.t+tzShift()),tl=`${pad(t.getUTCDate())}.${pad(t.getUTCMonth()+1)} ${pad(t.getUTCHours())}:${pad(t.getUTCMinutes())}`;
 const tps=[0,1,2].map(j=>G.tp[j]!=null?`<span>TP${j+1}</span><span>${fmtP(G.tp[j])}</span><span>${(Math.abs(G.tp[j]-G.e)/R_).toFixed(2)} R${G.hit.includes('TP'+(j+1))?' · ✓ osiągnięty':''}${G.sh?` · ${Math.round(G.sh[j]*100)}% poz.`:''}</span>`:`<span>TP3</span><span>—</span><span>brak w kontrakcie strategii</span>`).join('');
 const why=G.src==='BASKET'?`<div class="sec"><span>REGUŁA KOSZYKA</span><span>${M.fam||''}</span></div><div class="ai"><b>Setup:</b> ${M.setup||'—'}<br><b>Trigger:</b> ${M.trig||'—'}<br><b>Anulowanie:</b> ${M.cancel||'—'}<br><b>Wyjście:</b> ${M.exit||'—'}</div>
   <div class="note">Reżim przy sygnale: <b>${G.rg}</b> – ${G.ro?'w routingu AUTO (bot publikuje w trybie AUTO)':'poza routingiem AUTO (bot opublikuje tylko w wyborze ręcznym)'}. Cele: ${G.tb==='STRUKTURA'?'strukturalne z reguły':'TP = '+(M.tp_r||[]).join(' / ')+' R'}; timeout ${G.to} świec.</div>`
  :G.src==='LEGACY'?`<div class="sec"><span>STRATEGIA ${G.sid}</span><span>${M.fam||''}</span></div><div class="ai"><b>Trigger:</b> ${G.trg||'—'}<br><b>Wynik setupu:</b> ${G.sc} / 100 (heurystyka ACTIVE, nie prawdopodobieństwo)<br><b>Powody:</b> ${(G.why||[]).join(', ')||'—'}${(G.miss||[]).length?`<br><b>Braki:</b> ${G.miss.join(', ')}`:''}</div><div class="note">${M.notrade?'Strategia domyślnie bez handlu (tylko analiza). ':''}Walidacja: ${M.val||'—'}.</div>`
  :`<div class="sec"><span>SILNIK SH</span><span>${G.sid.replace('SH_','')}</span></div><div class="ai"><b>Udziały:</b> ${(G.sh||[]).map(x=>Math.round(x*100)+'%').join(' / ')} · <b>BE</b> po ${G.be} · <b>RR netto</b> ${G.rr!=null?G.rr.toFixed(2):'—'} · horyzont ${G.hz} min</div><div class="note">Ocena co zamkniętą świecę M1 (kontekst M5 / M15 / H1). Status instrumentu: ${(M.status||{})[CH.asset]||'—'}.</div>`;
 el.className='ci'+(CH.cardMin?' min':'');el.innerHTML=`<div class="sh" role="button" tabindex="0" aria-expanded="${!CH.cardMin}"><b>PLAN BOTA</b><span class="side" data-s="${G.sd>0?'LONG':'SHORT'}">${G.sid} · ${G.sd>0?'LONG':'SHORT'} · ${G.src==='SH'?'M1':G.tf}</span><span class="chip" data-s="${G.res}">${resPL(G.res)}</span></div>
 <div class="sb"><div class="lv"><span>SYGNAŁ</span><span>${tl}</span><span>${(BK_INFO[G.bk]||[''])[0]}</span><span>WEJŚCIE</span><span>${fmtP(G.e)}</span><span>close świecy potwierdzającej</span><span>SL</span><span>${fmtP(G.sl)}</span><span>ryzyko ${fmtP(R_)}</span>${tps}${G.inv!=null?`<span>UNIEWAŻN.</span><span>${fmtP(G.inv)}</span><span></span>`:''}</div>
 ${why}
 <div class="sec"><span>SZANSE MODELI</span><span>UNIT = PROBABILITY</span></div>${row(P.win,P.win.v)}${row(P.tp2,P.tp2.v)}
 <div class="note">${CH.testTexts?CH.testTexts.cardNote:`Sygnał i plan z API bota. Wynik „${resPL(G.res)}” według cyklu życia sygnału w bocie. Szanse modeli: ${[P.win,P.tp2].map(o=>o.v!=null?`${o.src} (${o.cal})`:`${o.name.split(' · ')[0]} – ${({NOT_TRAINED:'niewytrenowany',DISABLED:'wyłączony',STALE:'nieaktualny',ERROR:'błąd',NO_DATA:'brak w API'}[o.state]||(o.state==='READY'?'niekalibrowany':o.state))}`).join('; ')}.`}</div></div>`;
 const h=el.querySelector('.sh');const tg=()=>{CH.cardMin=!CH.cardMin;el.dataset.key='';};h.addEventListener('click',tg);h.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();tg();}});}
/* ----- rysowanie: wykres Kronos ----- */
function drawKronos(ctx,cms,dt,red){const R0=rectOf('#kr-plot');if(R0.w<40)return;const K=CH.kr,uiA=red?smooth(SUB.p*2-1):smooth(seg(cms,1950,450));
 const off=K.mode==='OFF'||!K.on[K.tf];ctx.save();ctx.beginPath();ctx.rect(R0.l,R0.t,R0.w,R0.h);ctx.clip();ctx.globalAlpha=uiA;ctx.font='10px "Helvetica Neue",Helvetica,Arial,sans-serif';ctx.textBaseline='middle';
 const axW=64,R={l:R0.l+4,r:R0.r-axW,t:R0.t+8,b:R0.b-20},d=K.data.slice(-34),fc=K.fc,H=fc?fc.horizon:0,N=d.length+H+2,cw=(R.r-R.l)/N,X=i=>R.l+(i+.5)*cw;
 if(!fc||!d.length){ctx.restore();if(!CH.frozen){$('#kr-dir').textContent='—';$('#kr-dir').dataset.d='';$('#kr-delta').textContent='';$('#kr-read').textContent=K.emptyTxt||'BRAK PROGNOZY';$('#kr-meta').textContent='';}return;}
 if(!red)K.anim=Math.min(1,K.anim+dt/1.6);const ka=red?1:K.anim;
 const all=[...d.flatMap(b=>[b.h,b.l]),...fc.pred.flatMap(b=>[b.h,b.l]),...fc.paths.flat()];let mn=Math.min(...all),mx=Math.max(...all);const pad=(mx-mn)*.08;mn-=pad;mx+=pad;const Y=v=>R.t+(mx-v)/(mx-mn)*(R.b-R.t);
 const stp=niceStep((mx-mn)/5);for(let v=Math.ceil(mn/stp)*stp;v<mx;v+=stp){const y=Math.round(Y(v))+.5;ctx.strokeStyle='rgba(200,210,230,.06)';ctx.setLineDash([1,5]);ctx.beginPath();ctx.moveTo(R.l,y);ctx.lineTo(R.r,y);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='rgba(137,139,145,.9)';ctx.textAlign='left';ctx.fillText(fmtP(v),R.r+8,y);}
 ctx.strokeStyle='rgba(43,48,59,.9)';ctx.beginPath();ctx.moveTo(R.r+.5,R.t);ctx.lineTo(R.r+.5,R.b);ctx.stroke();
 const nx=X(d.length-1)+cw/2;
 /* pasmo neutralne */
 ctx.fillStyle='rgba(186,170,255,.05)';ctx.fillRect(nx,Y(fc.last_close+fc.neutral_band),R.r-nx,Y(fc.last_close-fc.neutral_band)-Y(fc.last_close+fc.neutral_band));
 ctx.strokeStyle='rgba(186,170,255,.18)';ctx.setLineDash([2,4]);[1,-1].forEach(s=>{const y=Math.round(Y(fc.last_close+s*fc.neutral_band))+.5;ctx.beginPath();ctx.moveTo(nx,y);ctx.lineTo(R.r,y);ctx.stroke();});ctx.setLineDash([]);
 d.forEach((b,i)=>{const x=X(i),up=b.c>=b.o,bw=Math.max(1,cw*.6);ctx.strokeStyle=up?'rgba(236,239,245,.7)':'rgba(138,145,158,.9)';ctx.beginPath();ctx.moveTo(Math.round(x)+.5,Y(b.h));ctx.lineTo(Math.round(x)+.5,Y(b.l));ctx.stroke();const t=Math.min(Y(b.o),Y(b.c)),hh=Math.max(1,Math.abs(Y(b.o)-Y(b.c)));
  if(up){ctx.fillStyle='rgba(236,239,245,.9)';ctx.fillRect(x-bw/2,t,bw,hh);}else{ctx.fillStyle='#000';ctx.fillRect(x-bw/2,t,bw,hh);ctx.strokeRect(Math.round(x-bw/2)+.5,Math.round(t)+.5,Math.max(0,Math.round(bw)-1),Math.max(0,Math.round(hh)-1));}});
 /* linia "teraz" */
 const pulse=.5+.5*Math.sin(performance.now()/500);ctx.strokeStyle=`rgba(220,226,236,${.25+.2*pulse})`;ctx.beginPath();ctx.moveTo(Math.round(nx)+.5,R.t);ctx.lineTo(Math.round(nx)+.5,R.b);ctx.stroke();
 ctx.fillStyle='rgba(137,139,145,.9)';ctx.textAlign='center';ctx.font='9px "Helvetica Neue",Helvetica,Arial,sans-serif';ctx.fillText('TERAZ',nx,R.b+10);ctx.fillText('+'+H+' ŚWIEC',X(d.length+H-1),R.b+10);
 if(!off){/* ścieżki niepewności */ctx.strokeStyle='rgba(186,170,255,.10)';fc.paths.forEach(pth=>{ctx.beginPath();ctx.moveTo(nx,Y(fc.last_close));pth.forEach((v,j)=>{if((j+1)/H<=ka*1.2)ctx.lineTo(X(d.length+j),Y(v));});ctx.stroke();});
  fc.pred.forEach((b,j)=>{const kk=clamp(ka*1.25*H-j);if(kk<=0)return;const x=X(d.length+j),up=b.c>=b.o,bw=Math.max(1,cw*.6),gl=(1-kk)*.8;ctx.globalAlpha=uiA*kk;
   ctx.strokeStyle='rgba(196,182,255,.85)';ctx.setLineDash([2,2]);ctx.beginPath();ctx.moveTo(Math.round(x)+.5,Y(b.h));ctx.lineTo(Math.round(x)+.5,Y(b.l));ctx.stroke();ctx.setLineDash([]);
   const t=Math.min(Y(b.o),Y(b.c)),hh=Math.max(1,Math.abs(Y(b.o)-Y(b.c)));ctx.fillStyle=up?'rgba(196,182,255,.28)':'rgba(0,0,0,.6)';ctx.fillRect(x-bw/2,t,bw,hh);ctx.strokeStyle='rgba(196,182,255,.85)';ctx.strokeRect(Math.round(x-bw/2)+.5,Math.round(t)+.5,Math.max(0,Math.round(bw)-1),Math.max(0,Math.round(hh)-1));
   if(gl>0){const g=ctx.createRadialGradient(x,Y(b.c),0,x,Y(b.c),14);g.addColorStop(0,`rgba(220,210,255,${gl})`);g.addColorStop(1,'rgba(220,210,255,0)');ctx.fillStyle=g;ctx.fillRect(x-14,Y(b.c)-14,28,28);}});
  ctx.globalAlpha=uiA;if(ka>=1){const y=Math.round(Y(fc.pred_close_h))+.5;ctx.strokeStyle='rgba(186,170,255,.6)';ctx.setLineDash([5,4]);ctx.beginPath();ctx.moveTo(nx,y);ctx.lineTo(R.r,y);ctx.stroke();ctx.setLineDash([]);
   ctx.fillStyle='#0b0915';ctx.fillRect(R.r+1,y-10,axW-2,20);ctx.strokeStyle='rgba(186,170,255,.8)';ctx.strokeRect(R.r+1.5,y-9.5,axW-3,19);ctx.fillStyle='#e6e0ff';ctx.textAlign='left';ctx.font='10px "Helvetica Neue",Helvetica,Arial,sans-serif';ctx.fillText(fmtP(fc.pred_close_h),R.r+7,y+.5);}}
 else{ctx.fillStyle='#63666c';ctx.textAlign='center';ctx.font='9px "Helvetica Neue",Helvetica,Arial,sans-serif';ctx.fillText(K.mode==='OFF'?'K R O N O S   W Y Ł Ą C Z O N Y':`K R O N O S   ${K.tf}   W Y Ł Ą C Z O N Y`,(nx+R.r)/2,(R.t+R.b)/2);}
 const kh=CH.khover;if(kh&&kh.x>R.l&&kh.x<R.r&&kh.y>R.t&&kh.y<R.b){const i=Math.floor((kh.x-R.l)/cw);const b=i<d.length?d[i]:fc.pred[i-d.length];if(b){const x=Math.round(X(i))+.5;ctx.strokeStyle='rgba(220,226,236,.3)';ctx.beginPath();ctx.moveTo(x,R.t);ctx.lineTo(x,R.b);ctx.stroke();
  $('#kr-read').innerHTML=`${i<d.length?'RZECZYWISTA':'<b class="kv">PROGNOZA +'+(i-d.length+1)+'</b>'} · ${fmtT(b.t,true,K.tf)} · O ${fmtP(b.o)} H ${fmtP(b.h)} L ${fmtP(b.l)} C ${fmtP(b.c)}`;}}
 else $('#kr-read').innerHTML=off?'PROGNOZA WYŁĄCZONA':`ŚCIEŻKA ${H} ŚWIEC · ${fc.paths.length?fc.paths.length+' ŚCIEŻEK NIEPEWNOŚCI':'BRAK ŚCIEŻEK NIEPEWNOŚCI'} · PASMO NEUTRALNE ±${fmtP(fc.neutral_band)}`;
 ctx.restore();
 const dir={UP:'↗ WZROST',DOWN:'↘ SPADEK',FLAT:'↔ BOCZNIE'}[fc.direction];$('#kr-dir').textContent=off?'—':dir;$('#kr-dir').dataset.d=off?'':fc.direction;
 $('#kr-delta').textContent=off?'—':`${fc.delta>=0?'+':''}${fmtP(fc.delta)} (${fc.delta_pct>=0?'+':''}${fc.delta_pct.toFixed(3)}%) → ${fmtP(fc.pred_close_h)}`;
 $('#kr-meta').textContent=`${fc.is_current?'AKTUALNA':'NIEAKTUALNA'} · ${fmtT(fc.created_at.getTime(),true,'M1')} · horyzont +${H} · ${K.role||'SHADOW, bez zleceń'} · Kronos nie podaje confidence score`;
}
/* ----- rysowanie: HEATMAPA (mapa płynności w stylu Bookmap, chartsHeat.ts) – dane: setHeat (chartsData.ts), tylko GET ----- */
const HEAT={vm:null,st:{yMin:null,yMax:null,img:null,imgKey:null},zoom:1,pan:0,recv:0,geo:null};
let T11=false;   /* tryb testu 1:1 (load): bez elementów HEATMAPY – zrzut zgodny ze wzorcem */
const HWIN=[[300,'5 MIN'],[900,'15 MIN'],[3600,'1 H'],[14400,'4 H']],HSTAT={READY:'NA ŻYWO',STALE:'NIEAKTUALNY',NO_DATA:'BRAK DANYCH',ERROR:'BŁĄD ŹRÓDŁA'};
function heatReset(){HEAT.vm=null;HEAT.st={yMin:null,yMax:null,img:null,imgKey:null};HEAT.zoom=1;HEAT.pan=0;}
function heatSrc(){return CH.asset==='BTC'?'CRYPTO':'MT5';}
function drawHeatMode(ctx,cms,dt,red){const R0=rectOf('#mc-plot');if(R0.w<40)return;const sc=$('#sig-card');if(sc)sc.hidden=true;
 const uiA=red?smooth(SUB.p*2-1):smooth(seg(cms,1900,500)),H=HEAT.vm&&HEAT.vm.src===heatSrc()?HEAT.vm:null;
 const g=drawHeat(ctx,R0,H,HEAT.st,{pal:L.hpal,gain:L.hgain,cob:L.hcob,bbo:L.hbbo,bub:L.hbub,vol:L.hvol,grid:L.grid,zoom:HEAT.zoom,pan:HEAT.pan,hover:SUB.state==='on'?CH.hover:null,uiA,dt,elapsed:performance.now()-HEAT.recv,asset:CH.asset},{fmtP,niceStep,tzShift});
 HEAT.geo=g;const o=$('#mc-read'),f=v=>v==null?'—':fmtP(v),fq=v=>v==null?'—':v>=10?v.toFixed(1):v.toFixed(2);
 if(!H||!H.cols.length)o.innerHTML=`<span>HEATMAPA<b>${H?HSTAT[H.status]:'ŁADOWANIE'}</b></span>${H&&H.reason?`<span>POWÓD<b>${H.reason}</b></span>`:''}`;
 else if(g.hover){const h=g.hover;o.innerHTML=`<span>${h.cob?'ARKUSZ<b>TERAZ</b>':`CZAS<b>${g.fT(h.t,true)}</b>`}</span><span>WIERSZ<b>${f(h.row)}</b></span><span>PŁYNNOŚĆ<b>${fq(h.q)}</b></span><span>BID<b>${f(h.bid)}</b>ASK<b>${f(h.ask)}</b></span>${h.n!=null?`<span>SNAPSHOTY<b>${h.n}</b></span>`:''}`;}
 else o.innerHTML=`<span>BID<b>${f(g.bid)}</b>ASK<b>${f(g.ask)}</b>SPREAD<b>${g.bid!=null&&g.ask!=null?fmtP(g.ask-g.bid):'—'}</b></span><span>ŹRÓDŁO<b>${H.src==='MT5'?'ARKUSZ BROKERA MT5':'HYPERLIQUID'}</b></span><span>STAN<b>${HSTAT[H.status]}</b></span><span>SNAPSHOTY<b>${H.snapshots}</b></span>`;
 $('#mc-title').textContent=`${CH.asset==='BTC'?'BTC · HYPERLIQUID':ASSETS[CH.asset].sym} · ${(HWIN.find(w=>w[0]===L.hwin)||[0,''])[1]}`;}
function syncView(emit=true){const heat=L.view==='heat'&&!T11,el=$('#mc-view');
 if(el){if(T11)el.style.display='none';else{el.style.display='';el.innerHTML=`<button type="button" data-v="chart" aria-pressed="${!heat}" title="Świece / linia z wybranego interwału">WYKRES</button><button type="button" data-v="heat" aria-pressed="${heat}" title="Mapa płynności arkusza (styl Bookmap): historia DOM, bid / ask, COB">HEATMAPA</button>`+
  (heat?`<span class="ch-sep"></span>`+HWIN.map(([w,l])=>`<button type="button" data-w="${w}" aria-pressed="${L.hwin===w}" title="Okno czasu mapy">${l}</button>`).join(''):'');
  el.querySelectorAll('[data-v]').forEach(b=>b.addEventListener('click',()=>{if(L.view===b.dataset.v)return;L.view=b.dataset.v;HEAT.st.yMin=null;syncView();renderOpts();announce(L.view==='heat'?'Widok heatmapy płynności':'Widok wykresu');}));
  el.querySelectorAll('[data-w]').forEach(b=>b.addEventListener('click',()=>{L.hwin=+b.dataset.w;HEAT.st.yMin=null;syncView();renderOpts();}));}}
 const sub=$('#mc-sub'),hint=$('#mc-hint');if(sub)sub.textContent=heat?'MAPA PŁYNNOŚCI':'WYKRES GŁÓWNY';if(hint)hint.textContent=heat?'KÓŁKO = ZOOM · 2× KLIK = RESET':'PRZECIĄGNIJ · KÓŁKO = ZOOM · 2× KLIK = TERAZ';
 if(emit)emitSel('heat');}
function heatInfo(){const H=HEAT.vm&&HEAT.vm.src===heatSrc()?HEAT.vm:null;return `<tr><th>ŹRÓDŁO</th><td>${H?H.source:'—'}</td></tr><tr><th>JAKOŚĆ</th><td>${H?H.quality:'—'}</td></tr><tr><th>WIERSZ CENY</th><td>${H&&H.row?fmtP(H.row):'—'}</td></tr><tr><th>SNAPSHOTY</th><td>${H?H.snapshots:'—'}</td></tr><tr><th>TRANSAKCJE</th><td>${H?(H.trades.status==='NOT_AVAILABLE'?'brak taśmy (broker OTC)':H.trades.status==='NEUTRAL'?'bez strony agresora':H.trades.status==='READY'?'ze stroną agresora':'brak w oknie'):'—'}</td></tr><tr><th>STAN</th><td>${H?HSTAT[H.status]+(H.reason?' · '+H.reason:''):'ładowanie'}</td></tr>`;}
function heatOpts(){const mt=CH.asset!=='BTC',bubDis=mt?'arkusz brokera MT5 (OTC) nie ma taśmy transakcji – bąble nie są szacowane z ticków ani świec':null;
 return `<div class="row"><label>Widok</label>${SEG('view',[['chart','Wykres'],['heat','Heatmapa']])}</div><div class="row"><label>Okno</label>${SEG('hwin',HWIN)}</div>
 <div class="row"><label>Paleta</label>${SEG('hpal',[['classic','Klasyczna'],['apollo','Apollo']])}</div><div class="row"><label>Kontrast</label>${SEG('hgain',[[.7,'Niski'],[1,'Średni'],[1.6,'Wysoki']])}</div>
 <ul>${SW('hcob','Bieżący arkusz (COB) + suma','poziomy DOM teraz – kolumna po prawej')}${SW('hbbo','Najlepszy bid / ask','linie z ostatniego snapshotu kubełka')}${SW('hbub','Bąble transakcji','wielkość = suma wolumenu kubełka × wiersza ceny',{dis:!!bubDis,why:bubDis,note:bubDis?'BRAK TAŚMY':''})}${SW('hvol',mt?'Tick volume M1':'Wolumen transakcji','pasek na dole')}${SW('grid','Siatka','')}</ul>
 <table class="svpt" id="heat-info">${heatInfo()}</table>
 <div class="note">${mt?'Mapa pokazuje płynność oczekującą z arkusza kwotowań brokera (MT5 market depth), który bot zapisuje co sekundę (wskaźniki: book_record, 14 dni). To nie jest giełdowy L2 / MBO – broker może podawać tylko kilka poziomów. Komórka = średnia wielkość wiersza ceny w kubełku czasu; brak zapisu = przerwa, nie zero. Bąble transakcji wymagają taśmy z giełdy – dla XAUUSD u brokera jej nie ma.':'BTC: arkusz i transakcje z Hyperliquid (inny instrument niż symbol MT5). Historia zbierana od otwarcia widoku – bez archiwum. Strona agresora u dostawcy jest niezweryfikowana, więc bąble są neutralne (bez podziału kupno / sprzedaż).'} Widok tylko do odczytu – nie składa zleceń.</div>`;}
function drawChart(cms,dt){const cv=CH.cv,ctx=CH.ctx,{w,h,dpr}=S.view;if(cv.width!==Math.round(w*dpr)){cv.width=Math.round(w*dpr);cv.height=Math.round(h*dpr);}
 ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);if(SUB.p<=0)return;const red=S.reduced;
 const uiA=red?smooth(SUB.p*2-1):smooth(seg(cms,1900,500)),winA=red?smooth(SUB.p*2-1):easeOut3(seg(cms,1850,550));
 $('#ch-head').style.opacity=uiA;$('#mc-read').style.opacity=uiA;$$('.cs-win').forEach((el,i)=>{el.style.opacity=i===0?1:winA;el.style.setProperty('--k',winA);el.style.transform=i===0||winA>=1?'':`translateY(${(1-winA)*14}px)`;});
 $('.cs-win.main').style.setProperty('--k',uiA);
 if(L.view==='heat'&&!T11)drawHeatMode(ctx,cms,dt,red);else drawMain(ctx,cms,dt,red);drawKronos(ctx,cms,dt,red);}
/* ----- UI: nagłówek, okna, zakładki ----- */
function buildChartUI(){
 $('#ch-asset').innerHTML=Object.keys(ASSETS).map(a=>`<button type="button" data-a="${a}" aria-pressed="${a===CH.asset}">${a}</button>`).join('');
 $$('#ch-asset button').forEach(b=>b.addEventListener('click',()=>{CH.asset=b.dataset.a;heatReset();$$('#ch-asset button').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));CH.data=[];applySeries(true);chartsConnect();emitSel();}));
 $('#ch-tf').innerHTML=TFR.map(([t,,role,core])=>`<button type="button" data-tf="${t}" aria-pressed="${t===CH.tf}" title="${t} · rola ${role}${core?'':' · interwał kontekstowy'} · dane OK"><i></i>${t}</button>`).join('');
 $$('#ch-tf button').forEach(b=>b.addEventListener('click',()=>{CH.tf=b.dataset.tf;$$('#ch-tf button').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));applySeries(true);chartsConnect();renderOpts();}));
 $('#ch-tz').addEventListener('change',e=>{CH.tz=e.target.value;});
 $('#kr-tf').innerHTML=KR_TFS.map(t=>`<button type="button" data-k="${t}" aria-pressed="${t===CH.kr.tf}">${t}</button>`).join('');
 $$('#kr-tf button').forEach(b=>b.addEventListener('click',()=>{CH.kr.tf=b.dataset.k;$$('#kr-tf button').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));CH.kr.fc=null;CH.kr.data=[];renderOpts();emitSel('kronos');}));
 $('#kr-refresh').addEventListener('click',()=>{emitSel('kronos');});   /* PRZELICZ = ponowny GET (bez zapisu) */
 $$('#opt-tabs button').forEach(b=>b.addEventListener('click',()=>{$$('#opt-tabs button').forEach(x=>x.setAttribute('aria-selected',String(x===b)));renderOpts();}));
 renderOpts();syncView(false);
 const mp=$('#mc-plot');
 mp.addEventListener('pointermove',e=>{CH.hover={x:e.clientX,y:e.clientY};if(L.sync)CH.khover=null;const dr=CH.drag;if(dr&&L.view==='heat'&&!T11){const g=HEAT.geo,st=HEAT.st;if(g&&st.yMax!=null)HEAT.pan=dr.pan+(e.clientY-dr.y)*(st.yMax-st.yMin)/Math.max(1,g.priceB-g.R.t);}else if(dr&&CH.geo){CH.offset=clamp(Math.round(dr.off+(e.clientX-dr.x)/CH.geo.cw),0,CH.data.length-CH.view);}});
 mp.addEventListener('pointerleave',()=>{CH.hover=null;});mp.addEventListener('pointerdown',e=>{CH.drag={x:e.clientX,y:e.clientY,off:CH.offset,pan:HEAT.pan};mp.setPointerCapture(e.pointerId);mp.style.cursor='grabbing';});
 const end=e=>{const dr=CH.drag;CH.drag=null;mp.style.cursor='crosshair';if(dr&&e&&e.clientX!=null&&Math.abs(e.clientX-dr.x)<4&&L.view!=='heat'){const hs=hitSignal(e.clientX,e.clientY);if(hs){STR.sel=hs.key;pickPlan();announce(`Plan ${hs.sid} ${hs.sd>0?'LONG':'SHORT'}, wejście ${fmtP(hs.e)}, SL ${fmtP(hs.sl)}`);}}};mp.addEventListener('pointerup',end);mp.addEventListener('pointercancel',end);mp.addEventListener('dblclick',()=>{if(L.view==='heat'){HEAT.zoom=1;HEAT.pan=0;}else CH.offset=0;});
 mp.addEventListener('wheel',e=>{e.preventDefault();if(L.view==='heat'&&!T11){HEAT.zoom=clamp(HEAT.zoom*(e.deltaY>0?1.12:1/1.12),.15,8);return;}CH.view=clamp(Math.round(CH.view*(e.deltaY>0?1.12:1/1.12)),30,400);CH.offset=clamp(CH.offset,0,CH.data.length-CH.view);},{passive:false});
 mp.addEventListener('keydown',e=>{if(L.view==='heat'&&!T11){const st=HEAT.st,r=st.yMax!=null?(st.yMax-st.yMin)*.1:0;if(e.key==='ArrowUp')HEAT.pan+=r;else if(e.key==='ArrowDown')HEAT.pan-=r;else if(e.key==='+'||e.key==='=')HEAT.zoom=clamp(HEAT.zoom/1.12,.15,8);else if(e.key==='-')HEAT.zoom=clamp(HEAT.zoom*1.12,.15,8);return;}if(e.key==='ArrowLeft')CH.offset=clamp(CH.offset+5,0,CH.data.length-CH.view);else if(e.key==='ArrowRight')CH.offset=clamp(CH.offset-5,0,CH.data.length-CH.view);else if(e.key==='+'||e.key==='=')CH.view=clamp(Math.round(CH.view/1.12),30,400);else if(e.key==='-'){CH.view=clamp(Math.round(CH.view*1.12),30,400);CH.offset=clamp(CH.offset,0,CH.data.length-CH.view);}});
 const kp=$('#kr-plot');kp.addEventListener('pointermove',e=>{CH.khover={x:e.clientX,y:e.clientY};});kp.addEventListener('pointerleave',()=>{CH.khover=null;});
 $$('#ctl-chart [data-cs]').forEach(b=>b.addEventListener('click',()=>{CH.token++;setChartStatus(b.dataset.cs);}));
}
const SW=(k,label,hint,extra)=>{const un=UNAVAIL[k]||(PROD?UNAVAIL_PROD[k]:null),dis=un||extra?.dis;return `<li class="${dis?'dis':''}" title="${(un||extra?.why||hint||'').replace(/"/g,'&quot;')}"><span>${label}${un?'<small>NIEDOSTĘPNE</small>':extra?.note?`<small>${extra.note}</small>`:''}</span><button type="button" class="sw" data-l="${k}" aria-pressed="${!!L[k]&&!dis}" ${dis?'disabled':''} aria-label="${label}"></button></li>`;};
const SEG=(k,opts)=>`<span class="seg">${opts.map(([v,l])=>`<button type="button" data-seg="${k}" data-v="${v}" aria-pressed="${String(k==='krMode'?CH.kr.mode:L[k])===String(v)}">${l}</button>`).join('')}</span>`;
function renderOpts(){savePref();const tab=$('#opt-tabs [aria-selected="true"]').dataset.t,avOk=['M1','M5'].includes(CH.tf),K=CH.kr;let h='';
 if(tab==='ind')h=`<ul>${SW('ema','EMA silnika','linie EMA z profilu M02I dla tego interwału')}${SW('avwap','AVWAP sesji ±1σ / ±2σ','PMW-IND-1',{dis:!avOk,why:'AVWAP tylko na M1 / M5 (config.indicators.avwap_tfs)',note:avOk?'':'TYLKO M1 / M5'})}${SW('rsi','RSI','okno pod wykresem')}${SW('macd','MACD','okno pod wykresem')}${SW('atr','ATR 14 – odczyt','wartość w pasku odczytu')}${SW('sar','Parabolic SAR','MQ_SAR_WILDER_PROFILE_V1')}${SW('bb','Bollinger Bands','')}${SW('iq','IQ Gold Gann / Star Lines','')}${SW('ai','Poziomy AI','oznaczone „AI:”, osobno od planu silnika')}</ul>`;
 else if(tab==='strat'){const cnt={},tp={},sl={};for(const s of CH.bsig||[]){cnt[s.sid]=(cnt[s.sid]||0)+1;if(s.hit.length)tp[s.sid]=(tp[s.sid]||0)+1;if(s.res.startsWith('SL'))sl[s.sid]=(sl[s.sid]||0)+1;}
  const rowS=m=>{const un=stratAvail(m.id),tf=m.tf||(m.tfs?m.tfs.join('/'):m.id.startsWith('SH_')?'M1':''),onTf=m.bk==='SH'?TFSEC[CH.tf]<=900:m.tf?m.tf===CH.tf:(m.tfs||[]).includes(CH.tf),n=cnt[m.id]||0,on=STR.on.has(m.id)&&!un;
   const info=un?un:!onTf?`sygnały na ${m.bk==='SH'?'M1–M15':tf}`:n?`${n} sygn. · TP ✓ ${tp[m.id]||0} · SL ${sl[m.id]||0}`:'brak sygnału na tych świecach';
   return `<li class="${un?'dis':''}"><span><i class="sdot" style="background:rgb(${BK_COL[m.bk]})"></i>${m.id.replace('FX_','')} · ${m.nm}<small>${tf}${m.notrade?' · BEZ HANDLU':''}</small><em>${info}</em></span>${!un&&!onTf&&m.tf?`<button type="button" class="mini" data-gotf="${m.tf}">→ ${m.tf}</button>`:''}<button type="button" class="sw" data-sid="${m.id}" aria-pressed="${on}" ${un?'disabled':''} aria-label="${m.id}"></button></li>`;};
  h=`<ul>${SW('strat','Sygnały strategii bota','markery ▲▼ przy świecy sygnału; kliknij marker, aby pokazać jego plan')}${SW('plan','Poziomy planu: wejście · SL · TP1–TP3','')}${SW('card','Karta planu','')}</ul><div class="row"><label>Poziomy</label>${SEG('stratLv',[['last','OSTATNI'],['sel','WYBRANY'],['all','WSZYSTKIE']])}</div>`+
   BK_ORDER.map(bk=>{const ms=BOTVM.meta[bk],allOn=ms.every(m=>STR.on.has(m.id)||stratAvail(m.id)),n=ms.reduce((a,m)=>a+(cnt[m.id]||0),0);return `<div class="bk"><div class="bkh"><button type="button" class="bkt" data-bk="${bk}" aria-expanded="${!!STR.open[bk]}"><i class="sdot" style="background:rgb(${BK_COL[bk]})"></i>${BK_INFO[bk][0]}<small>${BK_INFO[bk][1]} · ${ms.length} strategii · ${n} sygn. na ${CH.tf}</small></button><button type="button" class="sw" data-bkall="${bk}" aria-pressed="${allOn}" aria-label="Cały koszyk ${bk}"></button></div>${STR.open[bk]?`<ul>${ms.map(m=>rowS({...m,bk})).join('')}</ul>`:''}</div>`;}).join('')+
   `<div class="note">${CH.testTexts?'Sygnały, SL i TP policzone kodem bota 1.41.0 (baskets/rules.py, strategies/registry.py, sh/replay.scan) na świecach podglądu – DEMO. Każda strategia pokazuje sygnały tylko na swoim TF sygnału. Koszyki FX_SMC / FX_SCALP i S01–S12 mają TP1–TP2 (TP3 nie istnieje w ich kontrakcie planu); TP1–TP3 ma silnik SH. Wynik TP/SL to przebieg na tych świecach, nie walidacja.':'Sygnały, SL i TP z API bota (koszyki FX, S01–S12, silnik SH). Każda strategia pokazuje sygnały tylko na swoim TF sygnału. Koszyki FX_SMC / FX_SCALP i S01–S12 mają TP1–TP2 (TP3 nie istnieje w ich kontrakcie planu); TP1–TP3 ma silnik SH. Wynik według cyklu życia sygnału w bocie – nie walidacja skuteczności.'}</div>`;}
 else if(tab==='zones'){const Z=CH.bzones,cn={};(Z||[]).forEach(z=>{const k=(ZT[z.ty]||['mz'])[0];if(z.st!=='INVALIDATED'&&z.st!=='EXPIRED')cn[k]=(cn[k]||0)+1;});const nz=k=>Z?`${cn[k]||0} żywych · ${CH.tf}`:'';
  const zm=VM.zoneMsg&&VM.zoneMsg.tf===CH.tf&&VM.zoneMsg.a===CH.asset?VM.zoneMsg.t:null;
  h=`${zm?`<div class="note warn">${zm}</div>`:Z?'':PROD&&['M1','M5','M15','M30'].includes(CH.tf)?`<div class="note">Strefy ${CH.tf}: ładowanie z API bota…</div>`:`<div class="note warn">Bot wyznacza strefy rynkowe tylko na M1, M5, M15 i M30. Na ${CH.tf} nie ma stref – nic nie jest przenoszone z innego interwału.</div>`}<ul>${SW('mz',`Strefy wybrane przez silnik · ${CH.tf}`,'zones/market.py – najlepsze żywe strefy tego TF',{dis:!Z,note:Z?(Z.filter(z=>z.v).length+' WIDOCZNYCH'):'BRAK NA TYM TF'})}${SW('fvg','FVG','',{dis:!Z,note:nz('fvg')})}${SW('ob','Order blocks','',{dis:!Z,note:nz('ob')})}${SW('sd','Popyt / podaż','',{dis:!Z,note:nz('sd')})}${SW('sr','Wsparcie / opór','',{dis:!Z,note:nz('sr')})}${SW('liq','Płynność EQH / EQL','hipoteza z OHLC',{dis:!Z,note:nz('liq')})}${SW('mzHist','Historia: unieważnione / wygasłe','',{dis:!Z})}
  ${SW('structure','BOS / CHoCH','struktura na wybranym TF')}${SW('zmap','POC / VAH / VAL poprzedniej sesji','z Session Volume Profile')}${SW('walls','Walls dzienne / Daily','HV_PROXY lub IV z importu; daily open / high / low')}${SW('patterns','Zakres / formacje','')}${SW('sessions','Boksy sesji','okna sesji profilu SVP (strefy IANA, czas letni)')}${SW('heat','Heatmapa likwidacji','')}</ul>
  <div class="note">Strefy liczone wyłącznie ze świec wybranego interwału (${CH.tf}) – po zmianie TF przeliczane są od nowa.</div>`;}
 else if(tab==='vp'){const prof=svpProfile(),PR=SVP_PROFILES[prof],bins=SVP_BINS[CH.asset],bk=CH.asset==='BTC'?'svpBinB':'svpBinX',done=(CH.svpS||[]).slice(-4).reverse();
  h=`<ul>${SW('svpS','Session Volume Profile – sesje','PMW-SVP-1 SESSION / LIVE: osobny profil każdej sesji',{dis:!!CH.svpMsg,note:CH.svpMsg?'TF ≤ H1':''})}${SW('vp','Profil widocznego zakresu','PMW-SVP-1 VISIBLE')}${SW('vpPoc','POC','')}${SW('vpVa',`Value Area ${Math.round(L.svpVa*100)}%`,'')}${SW('vpHvn','HVN','')}${SW('vpLvn','LVN','')}</ul>
  <div class="row"><label>Sesje</label>${SEG('svpProf',[['AUTO','AUTO'],['LAB_XAU_REFERENCE_V1','XAU REF'],['LAB_BTC_REFERENCE_V1','BTC REF'],['SCALP_OPENING_V1','OTWARCIA']])}</div>
  <div class="row"><label></label><span class="seg">${PR.sessions.map(x=>`<button type="button" data-svps="${x[0]}" aria-pressed="${!L.svpOff[x[0]]}" title="${x[1]} ${x[2]}–${x[3]}">${x[0]}</button>`).join('')}</span></div>
  <div class="row"><label>Siatka</label>${SEG(bk,bins.map(b=>[b,b+' t']))}<span class="dimb">bin = ${fmtP(svpBinTicks()*.01)}</span></div><div class="row"><label>Value area</label>${SEG('svpVa',[[.6,'60%'],[.7,'70%'],[.8,'80%']])}</div>
  ${CH.svpMsg?`<div class="note warn">${CH.svpMsg}</div>`:`<table class="svpt"><tr><th>SESJA</th><th>STAN</th><th>POC</th><th>VAH</th><th>VAL</th><th>ŚWIECE</th></tr>${done.map(P=>`<tr><td>${P.session} ${P.local_date.slice(8)}.${P.local_date.slice(5,7)}</td><td>${P.state==='DEVELOPING'?'W TOKU':P.status==='PARTIAL'?'CZĘŚC.':'ZAMKN.'}</td><td>${fmtP(P.poc)}</td><td>${fmtP(P.vah)}</td><td>${fmtP(P.val)}</td><td>${P.bars}/${P.expected_bars}</td></tr>`).join('')}</table>`}
  <div class="note">Algorytm 1:1 z svp/engine.py (histogram, VA, HVN/LVN) – zgodność sprawdzona na 44 profilach. Wolumen: TICK_VOLUME (aktywność brokera, nie wolumen transakcyjny); waga świecy rozkładana równomiernie w [low, high] – estymata, nie footprint. Sesje w strefach ${PR.sessions.map(x=>x[1]).join(', ')} z czasem letnim. Profil liczony ze świec wybranego TF (${CH.tf}).</div>`;}
 else if(tab==='models')h=`<ul>${SW('mcTp','Szansa Monte Carlo przy TP','PMW-MC-1: P(TP przed SL) w H świecach M1')}</ul><div class="row"><label>Kronos</label>${SEG('krMode',[['AUTO','AUTO'],['MANUAL','MANUAL'],['OFF','OFF']])}</div><ul>${KR_TFS.map(t=>SWK(t,'Kronos '+t)).join('')}${SWK('onChart','Prognoza na wykresie głównym')}
  <li><span>Stan inferencji</span><b class="okb">${K.state}</b></li>${SW('granite','Granite TTM','linia prognozy punktowej (bez świec)')}<li><span>Chronos-2</span><b class="dimb">porównanie w AI Consensus</b></li></ul>`;
 else if(L.view==='heat'&&!T11)h=heatOpts();
 else h=(T11?'':`<div class="row"><label>Widok</label>${SEG('view',[['chart','Wykres'],['heat','Heatmapa']])}</div>`)+`<div class="row"><label>Typ</label>${SEG('ctype',[['candles','Świece'],['hollow','Puste'],['heikin','Heikin Ashi'],['line','Linia'],['area','Obszar']])}</div><ul>${SW('grid','Siatka','')}${SW('volume','Wolumen (tick volume)','')}${SW('labels','Etykiety stref i poziomów','')}${SW('sync','Wspólny celownik','wykres główny + Kronos')}</ul>
  <div class="row"><label>Interwał</label><span class="dimb">${CH.tf} · rola ${TFR.find(r=>r[0]===CH.tf)[2]}</span></div>`;
 $('#opt-body').innerHTML=h;
 $$('#opt-body .sw[data-l]').forEach(b=>b.addEventListener('click',()=>{const k=b.dataset.l;L[k]=!L[k];renderOpts();}));
 $$('#opt-body .sw[data-k]').forEach(b=>b.addEventListener('click',()=>{const k=b.dataset.k;if(k==='onChart')CH.kr.onChart=!CH.kr.onChart;else CH.kr.on[k]=!CH.kr.on[k];renderOpts();}));
 $$('#opt-body [data-seg]').forEach(b=>b.addEventListener('click',()=>{const k=b.dataset.seg,v=b.dataset.v;if(k==='krMode'){CH.kr.mode=v;$('#kr-mode').textContent=v;}else L[k]=isNaN(+v)?v:+v;if(k==='stratLv'&&v!=='sel')STR.sel=STR.sel;if(k==='view'||k==='hwin'){HEAT.st.yMin=null;syncView();}svpRecalc();renderOpts();}));
 $$('#opt-body [data-sid]').forEach(b=>b.addEventListener('click',()=>{const id=b.dataset.sid;STR.on.has(id)?STR.on.delete(id):STR.on.add(id);pickPlan();renderOpts();}));
 $$('#opt-body [data-bkall]').forEach(b=>b.addEventListener('click',()=>{const ms=BOTVM.meta[b.dataset.bkall].filter(m=>!stratAvail(m.id)),all=ms.every(m=>STR.on.has(m.id));ms.forEach(m=>all?STR.on.delete(m.id):STR.on.add(m.id));pickPlan();renderOpts();}));
 $$('#opt-body [data-bk]').forEach(b=>b.addEventListener('click',()=>{const k=b.dataset.bk;STR.open[k]=!STR.open[k];renderOpts();}));
 $$('#opt-body [data-gotf]').forEach(b=>b.addEventListener('click',()=>{const x=$(`#ch-tf [data-tf="${b.dataset.gotf}"]`);if(x)x.click();}));
 $$('#opt-body [data-svps]').forEach(b=>b.addEventListener('click',()=>{const k=b.dataset.svps;L.svpOff={...L.svpOff,[k]:!L.svpOff[k]};svpRecalc();renderOpts();}));
 $('#kr-mode').textContent=K.mode;}
function SWK(k,label){const dis=CH.kr.mode==='OFF',v=k==='onChart'?CH.kr.onChart:CH.kr.on[k];return `<li class="${dis?'dis':''}"><span>${label}<small>${k==='onChart'?'':'GOTOWY · +'+KR_H[k]+' ŚWIEC'}</small></span><button type="button" class="sw" data-k="${k}" aria-pressed="${!!v&&!dis}" ${dis?'disabled':''} aria-label="${label}"></button></li>`;}



buildChartUI();
const listeners=[];
function emitSel(what='series'){listeners.forEach(f=>{try{f({what,asset:CH.asset,tf:CH.tf,kr:CH.kr.tf,view:L.view==='heat'&&!T11?'heat':'chart',hw:L.hwin});}catch(e){}});}
function setTfr(items){if(!items||!items.length)return;TFR=items.map(x=>[x.tf,x.seconds,x.role,x.core?1:0]);TFSEC=Object.fromEntries(TFR.map(r=>[r[0],r[1]]));
 $('#ch-tf').innerHTML=TFR.map(([t,,role,core])=>`<button type="button" data-tf="${t}" aria-pressed="${t===CH.tf}" title="${t} · rola ${role}${core?'':' · interwał kontekstowy'} · dane ${(items.find(x=>x.tf===t)||{}).data||'—'}"><i></i>${t}</button>`).join('');
 $$('#ch-tf button').forEach(b=>b.addEventListener('click',()=>{CH.tf=b.dataset.tf;$$('#ch-tf button').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));CH.data=[];applySeries(true);emitSel();chartsConnect();renderOpts();}));}
/** Model widoku (D1 §3) – ta sama postać co fixtures testu 1:1. */
function applyVM(vm){const A=vm.asset||CH.asset;CH.asset=A;if(vm.tf)CH.tf=vm.tf;if(vm.tz)CH.tz=vm.tz;if(vm.serverOff!=null)CH.serverOff=vm.serverOff;
 if(vm.meta){BOTVM.meta={FX_SMC:[],FX_SCALP:[],FX_HEDGE:[],LEGACY:[],SH:[],...vm.meta};rebuildMeta();}
 BOTVM.sig[A]=vm.signals||[];BOTVM.zones[A]=vm.zones||{};BOTVM.states[A]=vm.states||{};
 CH.iprof=vm.iprof||IPROF_REF;CH.data=vm.candles||[];VM.probs=vm.probs||null;if('kronos' in vm)VM.kronos=vm.kronos||null;   /* K5 poprawka: odświeżenie świec nie kasuje prognozy Kronosa (przychodzi osobno przez setKronos) */VM.status=vm.status||(CH.data.length?'live':'loading');VM.zoneMsg=vm.zoneMsg?{tf:CH.tf,a:A,t:vm.zoneMsg}:null;}
/* E5 (O1): koszt rysowania ekranu CHARTS na klatkę (2D canvas + DOM opcji), bez sceny WebGL kuli */
const PERF={n:0,sum:0,max:0};
const api={
 /** wiązanie z silnikiem kuli FOREX (jego S i SUB – czas wejścia, postęp, widok, ograniczenie ruchu) */
 bind(s,sub){S=s;SUB=sub;},
 screen:{inMs:CH_MS.inMs,outMs:CH_MS.outMs,el:'#charts-screen',focus:'#mc-plot',planet:cms=>chartsPlanet(cms),draw:(c,d)=>{const t0=performance.now();drawChart(c,d);const ms=performance.now()-t0;PERF.n++;PERF.sum+=ms;if(ms>PERF.max)PERF.max=ms;},tick:n=>chartTick(n),
  open:()=>{if(!CH.data.length)applySeries(false);chartsConnect();},close:()=>{CH.token++;CH.hover=null;CH.khover=null;},
  say:()=>'CHARTS. '+(ASSETS[CH.asset]?ASSETS[CH.asset].sym:CH.asset)+' '+CH.tf+'.'},
 onSelect(f){listeners.push(f);},
 setTimeframes:setTfr,
 setSymbol(a,sym){if(ASSETS[a]&&sym)ASSETS[a].sym=sym;},
 setQuote(q){if(CH.frozen||!q)return;$('#ch-quote').innerHTML=q.bid!=null?`BID <b>${fmtP(q.bid)}</b> ASK <b>${fmtP(q.ask)}</b> SPREAD <b>${fmtP(q.spread)}</b>`:'BRAK KWOTOWAŃ';},
 setStatus(st){if(!CH.frozen){const s2=CH.data.length||st==='offline'?st:'loading';VM.status=s2;setChartStatus(s2);}},
 setVM(vm,{keepView=true}={}){if(CH.frozen)return;const view=CH.view,off=CH.offset,sel=STR.sel;const first=!PROD&&!!vm.meta;applyVM(vm);
  if(first){PROD=true;const P=loadPref()||{};if(P.L)Object.assign(L,P.L);if(P.open)STR.open={...STR.open,...P.open};const off=new Set(P.off||[]);STR.on=new Set(Object.keys(SMETA).filter(id=>!off.has(id)));if(L.view==='heat')syncView();}
  {const A=CH.asset,k=x=>A+'|'+x.sid+'|'+x.t,fresh=(vm.signals||[]).filter(x=>!seenSig.has(k(x)));const boot=!seenSig.has(A);seenSig.add(A);fresh.forEach(x=>seenSig.add(k(x)));const nw=fresh[fresh.length-1],now=Date.now();
   if(!boot&&nw&&now-lastAnn>=5000){lastAnn=now;announce(`Nowy sygnał ${nw.sid} ${nw.sd>0?'LONG':'SHORT'} ${nw.tf}`);}}applySeries(false);if(keepView){CH.view=view;CH.offset=Math.min(off,Math.max(0,CH.data.length-CH.view));STR.sel=sel;pickPlan();}
  const sc=$('#sig-card');if(sc)sc.dataset.key='';svpRecalc();renderOpts();setChartStatus(VM.status);},
 /** tryb testowy 1:1 – odpowiednik PMW_PREVIEW._chartsLoad wzorca; fixture przez ten sam model widoku */
 load(fx){T11=true;syncView(false);CH.token++;CH.asset=fx.asset;CH.tf=fx.tf;CH.tz=fx.tz;CH.serverOff=fx.serverOff;
  $$('#ch-asset button').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.a===fx.asset)));$$('#ch-tf button').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.tf===fx.tf)));
  Object.keys(L).forEach(k=>delete L[k]);Object.assign(L,fx.L);
  applyVM({...fx,status:'live',kronos:null});
  CH.offset=0;computeAll();CH.probs=fx.probs;botIndex();STR.on=new Set(fx.str.on);STR.open=fx.str.open;STR.sel=fx.str.sel;pickPlan();
  CH.view=fx.view;CH.offset=fx.offset;const sl=CH.data.slice(-CH.view);CH.yMin=Math.min(...sl.map(c=>c.l));CH.yMax=Math.max(...sl.map(c=>c.h));CH.swap=1;CH.cardMin=fx.cardMin;
  const K=CH.kr;Object.assign(K,{tf:fx.kronos.tf,mode:fx.kronos.mode,on:fx.kronos.on,onChart:fx.kronos.onChart,state:fx.kronos.state,data:fx.kronos.candles,
   fc:fx.kronos.forecast?{...fx.kronos.forecast,created_at:new Date(fx.kronos.forecast.created_at)}:null,anim:1});
  $$('#kr-tf button').forEach(x=>x.setAttribute('aria-pressed',String(x.dataset.k===K.tf)));
  $$('#opt-tabs button').forEach(x=>x.setAttribute('aria-selected',String(x.dataset.t===fx.tab)));const sc=$('#sig-card');if(sc)sc.dataset.key='';svpRecalc();renderOpts();setChartStatus('live');CH.frozen=true;
  $('#ch-quote').innerHTML=`BID <b>${fmtP(fx.quote.bid)}</b> ASK <b>${fmtP(fx.quote.ask)}</b> SPREAD <b>${fmtP(fx.quote.spread)}</b>`;
  CH.testTexts=fx.test_texts||null;const tag=$('#ch-right .demo-tag');if(tag){tag.hidden=!(CH.testTexts&&CH.testTexts.headerTag);if(CH.testTexts&&CH.testTexts.headerTag)tag.textContent=CH.testTexts.headerTag;}},
 liveBar(b){if(CH.frozen||!CH.data.length||!b)return;const t=b.t,d=CH.data,last=d[d.length-1];if(t==null||t<last.t)return;
  if(t===last.t){Object.assign(last,{o:b.o,h:b.h,l:b.l,c:b.c,v:b.v,closed:b.closed});}else{last.closed=true;d.push({...b});if(CH.offset>0)CH.offset++;}CH.flash=1;},
 setKronos(k){if(CH.frozen)return;VM.kronos=k;loadKronos();},
 sel:()=>({asset:CH.asset,tf:CH.tf,kr:CH.kr.tf,view:L.view==='heat'&&!T11?'heat':'chart',hw:L.hwin}),
 /** HEATMAPA: model widoku z chartsData.ts (archiwum arkusza MT5 / arkusz dostawcy BTC) */
 setHeat(vm){if(CH.frozen)return;HEAT.vm=vm;HEAT.recv=performance.now();const hi=$('#heat-info');if(hi)hi.innerHTML=heatInfo();},
 perf:()=>{const r={frames:PERF.n,avgMs:PERF.n?+(PERF.sum/PERF.n).toFixed(3):null,maxMs:+PERF.max.toFixed(3)};PERF.n=0;PERF.sum=0;PERF.max=0;return r;},
 state:()=>({asset:CH.asset,tf:CH.tf,candles:CH.data.length,status:CH.status,sel:CH.sig?CH.sig.key:null,cardMin:!!CH.cardMin,
  markers:(CH.bsig||[]).filter(sigVisible).filter(s=>s._mx!=null).map(s=>({key:s.key,x:s._mx,y:s._my}))}),
 dispose(){CH.token++;listeners.length=0;}};
return api;
}
