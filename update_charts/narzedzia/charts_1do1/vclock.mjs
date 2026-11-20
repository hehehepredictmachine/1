// 1.42.5 (decyzja użytkownika: szum wzorca = 0 %): wirtualny zegar stron testu. Czas (performance.now, Date.now, znacznik klatki rAF)
// stoi i przesuwa się WYŁĄCZNIE przez window.__pmwRun(n) o n klatek po 100 ms; Math.random z ziarnem. Każdy krok scenariusza startuje
// w tym samym czasie wirtualnym, więc animacje (przejścia, pulsowanie, tło WebGL) są w tej samej fazie we wzorcu i w aplikacji.
export const VCLOCK = `(()=>{let vt=0,budget=0,last=-1,waiters=[];const STEP=100,dn=1768478400000,raf=window.requestAnimationFrame.bind(window);
 performance.now=()=>vt; Date.now=()=>dn+vt; let s=12345; Math.random=()=>{s=(s*1103515245+12345)&0x7fffffff;return s/0x7fffffff};
 window.requestAnimationFrame=cb=>raf(t=>{if(t!==last){last=t;if(budget>0){vt+=STEP;budget--;if(!budget){const w=waiters;waiters=[];setTimeout(()=>w.forEach(f=>f()),0);}}}cb(vt);});
 window.__pmwRun=n=>new Promise(r=>{budget+=n;waiters.push(r);}); window.__pmwVt=()=>vt;})();`;
