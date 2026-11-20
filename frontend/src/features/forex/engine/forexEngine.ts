// @ts-nocheck
/* Ekran FOREX 1.42 (E2) – port rdzenia wzorca update_1_42/referencje/REF_B_kula_forex_i_ekrany.html: shadery 1:1, stan S, fazy
   menu → dive → forex → surface, oś czasu przelotu, tło (cykl 66 s), panele MODEL A / MODEL B, 4 planety, droga mleczna, pętla.
   Zmiany względem wzorca: brak demonstracyjnego źródła stanu paneli (stan i impulsy przychodzą z API przez setPanel / result),
   brak losowych „wyników”, wybór planety = nawigacja (#/forex?s=…), ekran planety renderuje React w #sub-screen, a silnik rysuje
   przejście planety i tło ekranu na canvasie 2D (#sub-canvas) z danych przekazanych przez setScreenData; nasłuchy przez
   AbortController, dispose zwalnia programy, bufory i kontekst WebGL. Plik celowo bez typowania (kod wzorca 1:1). */
export function mountForex(root, opts){
const $=s=>root.querySelector(s), $$=s=>[...root.querySelectorAll(s)];
const ctl=new AbortController();const listen=(el,type,fn,o={})=>{if(el)el.addEventListener(type,fn,{...o,signal:ctl.signal});};
const clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,x)), lerp=(a,b,t)=>a+(b-a)*t;
const smooth=x=>{x=clamp(x);return x*x*(3-2*x)}, ease4=x=>{x=clamp(x);return 1-Math.pow(1-x,4)};
const easeIO3=x=>{x=clamp(x);return x<.5?4*x*x*x:1-Math.pow(-2*x+2,3)/2}, easeOut3=x=>{x=clamp(x);return 1-Math.pow(1-x,3)};
const seg=(ms,a,d)=>clamp((ms-a)/d);
const CFG=Object.freeze({orbCount:110000,streakCount:24000,starCount:1500,dustCount:9000,dprCap:1.65,
 diveMs:3200,surfaceMs:1600,reducedMs:300,bgCycle:66,filaments:56,filSegs:96,sparks:2500,vortexCount:22000});
const canvas=$('#c');const FIXED_DT=0;
const gl=opts.forceStatic?null:canvas.getContext('webgl',{alpha:false,antialias:false,depth:false,premultipliedAlpha:false,powerPreference:'high-performance'});
if(!gl){opts.onNoWebGL&&opts.onNoWebGL();return {dispose(){},setPanel(){},result(){},openSub(){},closeSub(){},surface(){},state:()=>({phase:'static'})};}

/* ---------- shadery ---------- */
const SHAPE=`
float gA,gSat,gAux;
float h1f(float x){return fract(sin(x*127.1)*43758.5453);}
vec3 rotXf(vec3 q,float a){float c=cos(a),s=sin(a);return vec3(q.x,q.y*c-q.z*s,q.y*s+q.z*c);}
/* FOREX – planeta macierzysta (menu główne v1.1): pasy + pas równikowy, fioletowy pierścień, 4 księżyce. gAux=1: przestrzeń widoku */
vec3 shapeForex(vec3 n,vec3 inf){float t=uTime,seed=inf.x;float lat=asin(clamp(n.y,-1.,1.)),lon=atan(n.z,n.x);vec3 p=n;gA=1.;gSat=0.;gAux=0.;
 if(seed<.10){gAux=1.;float u=fract(inf.y*7.31);float rr=1.30+.45*u;float gap=1.-step(abs(rr-1.56),.022);
  float ang=inf.z*6.2832+t*.10/pow(rr,1.5);p=rotXf(vec3(cos(ang)*rr,(inf.y-.5)*.012,sin(ang)*rr),.30);
  gA=(.5+.6*pow(.5+.5*sin(rr*46.+inf.y*3.),2.))*gap*1.25;gSat=.6;}
 else if(seed<.124){gAux=1.;float id=floor((seed-.10)/.006);float oa=id*1.5708+t*(.17+.035*id);float orr=1.92+.07*id;
  vec3 c=rotXf(vec3(cos(oa)*orr,0.,sin(oa)*orr),.30+.05*id);p=c+n*(.085+.012*id);gA=.95;gSat=.15;}
 else{float l2=lon+t*.05;float b=sin(lat*18.+sin(l2*2.+lat*3.)*.7);float eq=exp(-lat*lat*28.);
  p=n*(1.+.006*b);gA=.16+.95*pow(b*b,1.6)+.7*eq*(.6+.4*sin(l2*6.-t*.4))+.3*pow(sin(lat*37.+l2),8.);}
 return p;}`;
const PART_V=`precision highp float;
attribute vec3 aPos;attribute vec3 aInfo;
uniform float uTime,uDpr,uCamD,uNear,uFocal,uMorph,uOrbOp,uBgOp,uBgT,uDensity,uSparse,uLine,uBgScale;
uniform vec2 uRes,uCenter,uBgCenter;uniform mat3 uRot;uniform vec3 uC0,uC1;
varying vec3 vColor;varying float vAlpha;
float hash(vec3 p){return fract(sin(dot(p,vec3(12.9898,78.233,37.719)))*43758.5453);}
${SHAPE}
vec3 bgDense(vec3 n,vec3 inf,float h,out float a){
 float t=uBgT;vec3 ax=uC1-uC0;float L=max(length(ax),1e-3);vec3 dir=ax/L;
 vec3 side=normalize(cross(dir,vec3(0.,0.,1.))+vec3(1e-4,0.,0.));vec3 up=normalize(cross(dir,side));
 float s1=inf.x,s2=inf.y;vec3 p;
 if(s1<.5){float u=fract(s2+t*(.010+.022*h));float bul=sin(3.14159*u);
  float ang=h*6.2832+u*(4.+s2*9.)+t*.22*(.5+h);float rad=(.012+.42*pow(fract(h*7.13),2.2))*bul*(.45+.55*uDensity);
  p=mix(uC0,uC1,u)+(side*cos(ang)+up*sin(ang))*rad+side*.035*sin(u*21.+h*30.+t*.8)*bul;a=.06*(.45+.55*bul);
 }else if(s1<.82){vec3 c=h<.5?uC0:uC1;float r=.02+.55*pow(fract(s2*3.7+h),2.4);float th=s2*40.+t*(.32/(r+.06));
  vec3 e1=normalize(cross(n,vec3(.31,1.,.17)));vec3 e2=cross(n,e1);
  p=c+(e1*cos(th)+e2*sin(th))*r+dir*sin(th*2.)*r*.55;a=.055*(1.-.6*r);
 }else{vec3 c=h<.5?uC0:uC1;float l=fract(s2+t*.03*(.3+h));p=c+n*pow(l,1.6)*1.35*(.4+.6*uDensity);a=.07*(1.-l);}
 a*=step(fract(h*31.7),uDensity);return p;}
vec3 bgSparse(vec3 n,vec3 inf,float h,out float a,out float sz){
 float t=uBgT;vec3 base=mix(uC0,uC1,inf.y);vec3 m=(uC0+uC1)*.5;
 vec3 dust=base+n*.55*pow(fract(h*5.3),.8)+.04*vec3(sin(t*.11+h*40.),cos(t*.09+h*31.),0.);
 vec3 line=vec3(m.x+(h-.5)*.03+.01*sin(inf.y*40.+t),m.y+mix(-.72,.72,inf.y),0.);
 vec3 p=mix(dust,line,uLine);float lim=mix(.03,.15,uLine);
 a=step(fract(h*13.1),lim)*(.30+.7*pow(fract(h*77.),3.));sz=1.3+2.4*pow(fract(h*19.),4.);return p;}
void main(){
 vec3 n=aPos;float seed=aInfo.x;vec3 p=shapeForex(n,aInfo);if(gAux<.5)p=uRot*p;float depth=uCamD-p.z;
 vec3 nn=normalize(p);float rim=pow(1.-abs(nn.z),1.65);float light=clamp(dot(nn,normalize(vec3(-.65,.8,1.1)))*.5+.5,0.,1.);
 float al=gAux>.5?gA*(.50+.55*light):(.12+rim*.70+light*.34)*gA;
 /* zasłanianie bez siatki-okludera: tył kuli i to, co za tarczą planety, gaśnie */
 if(gAux<.5&&p.z<0.)al*=.10;if(gAux>.5&&p.z<0.&&length(p.xy)<1.)al*=.06;
 vec3 colA=mix(vec3(.77,.80,.87),vec3(.98,.985,1.),light*.8+rim*.2);colA=mix(colA,vec3(.70,.66,1.),gSat);
 vec2 A;float aA=0.,sA=1.;
 if(depth>uNear){A=uCenter+vec2(p.x,-p.y)*uFocal/depth;float base=mix(.60,1.12,aInfo.y)*uDpr;
  sA=clamp(base*3.7/depth,.65,7.*uDpr);aA=al*smoothstep(.05,.3,depth)*min(1.,2.2*uDpr/sA)*uOrbOp*(1.+2.6*(1.-smoothstep(.6,2.2,depth)));}
 else{A=uCenter+normalize(p.xy+vec2(1e-4))*length(uRes)*.8;}
 float h=hash(n*7.31+aInfo);float aD,aS,sS;vec3 qD=bgDense(n,aInfo,h,aD);vec3 qS=bgSparse(n,aInfo,h,aS,sS);
 vec3 q=mix(qD,qS,uSparse);float aB=mix(aD,aS,uSparse)*uBgOp;float pr=4./(4.-q.z);float sB=mix(1.,sS,uSparse)*uDpr*pr;
 vec2 B=uBgCenter+vec2(q.x,-q.y)*uBgScale*pr;
 float k=clamp(uMorph*1.3-aInfo.z*.3,0.,1.);k=k*k*(3.-2.*k);
 vec2 px=mix(A,B,k);vec2 clip=px/uRes*2.-1.;clip.y=-clip.y;gl_Position=vec4(clip,0.,1.);
 gl_PointSize=max(mix(sA,sB,k),.65);
 vColor=mix(colA,mix(vec3(.80,.84,.91),vec3(.97,.98,1.),pow(h,3.)),k);vAlpha=mix(aA,aB,k);}`;
const PART_F=`precision mediump float;varying vec3 vColor;varying float vAlpha;void main(){vec2 d=gl_PointCoord*2.-1.;float r=dot(d,d);if(r>1.)discard;float a=exp(-r*2.8)*vAlpha;gl_FragColor=vec4(vColor*a,a);}`;
const OSTREAK_V=`precision highp float;attribute vec3 aPos;attribute vec3 aInfo;attribute float aEnd;
uniform float uTime,uCamD,uCamD2,uNear,uFocal,uStreak,uOrbOp;uniform vec2 uRes,uCenter;uniform mat3 uRot;varying float vA;
${SHAPE}
void main(){vec3 p=shapeForex(aPos,aInfo);if(gAux<.5)p=uRot*p;float d0=uCamD-p.z,d1=uCamD2-p.z;
 if(d0<uNear||d1<uNear){gl_Position=vec4(2.,2.,0.,1.);vA=0.;return;}
 float d=mix(d0,d1,aEnd);vec2 px=uCenter+vec2(p.x,-p.y)*uFocal/d;vec2 c=px/uRes*2.-1.;c.y=-c.y;gl_Position=vec4(c,0.,1.);
 vA=uStreak*smoothstep(1.8,.35,d0)*smoothstep(.05,.3,d0)*.13*(1.-aEnd*.85)*uOrbOp;}`;
const OSTREAK_F=`precision mediump float;varying float vA;void main(){gl_FragColor=vec4(vec3(.86,.89,.95)*vA,vA);}`;
const STAR_V=`precision highp float;attribute vec3 aPos;attribute vec3 aInfo;uniform vec2 uPointer;uniform float uTime,uDpr,uOpacity,uWarp,uDust;varying float vAlpha;varying vec3 vColor;void main(){vec2 p=aPos.xy;float z=aPos.z;float t=uTime;vec2 drift=vec2(t*.0035*(z+.15),t*.0010*(z+.1));p=mod(p+drift+1.,2.)-1.;p+=uPointer*(z*.012+.002);p*=1.+uWarp*(.1+z*.8);gl_Position=vec4(p,0.,1.);gl_PointSize=(aInfo.x*.9+.45)*uDpr*(.7+z*.45)*(1.+uWarp*.6);float tw=.65+.35*sin(t*(aInfo.y*.4+.2)+aInfo.z*25.);vAlpha=(.085+pow(aInfo.x,6.)*.65)*tw*uOpacity;vColor=mix(vec3(.53,.62,.83),vec3(.95,.95,.93),aInfo.y);if(uDust>.5){float center=exp(-pow((p.y+p.x*.17+.38)*3.9,2.));vAlpha*=center*.11;gl_PointSize*=.65;}}`;
const STAR_F=`precision mediump float;varying float vAlpha;varying vec3 vColor;void main(){vec2 p=gl_PointCoord*2.-1.;float r=dot(p,p);if(r>1.)discard;float a=exp(-r*3.1)*vAlpha;gl_FragColor=vec4(vColor*a,a);}`;
const SSTREAK_V=`precision highp float;attribute vec3 aPos;attribute vec3 aInfo;uniform float uWarp,uOpacity;varying float vAlpha;void main(){vec2 p=aPos.xy;float k=aInfo.x;gl_Position=vec4(p*(1.+uWarp*(.4+aPos.z)*k),0.,1.);vAlpha=uWarp*uOpacity*(1.-k*.65)*.22;}`;
const SSTREAK_F=`precision mediump float;varying float vAlpha;void main(){gl_FragColor=vec4(vec3(.65,.76,1.)*vAlpha,vAlpha);}`;
const QUAD_V=`attribute vec2 aQ;varying vec2 vUv;void main(){vUv=aQ*.5+.5;gl_Position=vec4(aQ,0.,1.);}`;
const SOLID_F=`precision mediump float;uniform vec4 uC;void main(){gl_FragColor=uC;}`;
const COMP_F=`precision highp float;uniform sampler2D uTex;uniform vec2 uRes,uView;uniform float uDpr;uniform vec4 uK0,uK1;varying vec2 vUv;
vec3 glow(vec2 px,vec4 c){vec2 d=(px-c.xy)/uRes.y;float r2=dot(d,d);float g=c.z*(exp(-r2*1600.)*1.1+.0016/(r2+.0016)*.17);
 float rays=c.w*c.z*(exp(-abs(d.y)*260.)*exp(-abs(d.x)*7.)+exp(-abs(d.x)*260.)*exp(-abs(d.y)*9.))*.45;return vec3(.86,.91,1.)*(g+rays);}
void main(){vec3 c=texture2D(uTex,vUv).rgb;vec2 px=vec2(gl_FragCoord.x,uView.y-gl_FragCoord.y)/uDpr;c+=glow(px,uK0)+glow(px,uK1);c=1.-exp(-c*1.6);gl_FragColor=vec4(c,1.);}`;
const HSV=`vec3 hsv(float h,float s,float v){vec3 k=clamp(abs(mod(h*6.+vec3(0.,4.,2.),6.)-3.)-1.,0.,1.);return v*mix(vec3(1.),k,s);}`;
const FIL_V=`precision highp float;attribute vec3 aA;uniform float uT,uB,uSat,uAsp;varying vec3 vC;${HSV}
void main(){float f=aA.x,v=aA.y,s=aA.z,t=uT;float y=v*2.3-1.15;float env=.55+.45*sin(v*2.7+f*6.3+t*.21);
 float x=.23*sin(v*2.4+f*9.7+t*.40)*env+.10*sin(v*7.9-t*.95+f*23.1)+.045*sin(v*19.-t*1.7+f*41.)+.02*sin(v*43.-t*2.6+f*77.);
 float z=sin(v*3.3+f*13.+t*.5);float tw=.3*sin(t*.35+f*3.);x=x*cos(tw)+z*.12*sin(tw);
 gl_Position=vec4(x*1.1625/uAsp,y,0.,1.);float hh=fract(f*3.1+v*.55+t*.045+z*.08);float hue=.48+.26*hh+.16*step(.82,hh)*hh;vec3 c=hsv(hue,.78*uSat,1.);
 if(s>.9)c=mix(c,vec3(1.),.75);float b=.28+.72*pow(.5+.5*sin(v*13.-t*2.2+f*31.),3.);
 b*=(.62+.38*z)*smoothstep(0.,.08,v)*smoothstep(1.,.92,v);vC=c*b*.55*uB;}`;
const RING_V=`precision highp float;attribute vec3 aS;uniform float uT,uB,uDpr,uSat,uAsp,uPulse,uPI;varying vec3 vC;
void main(){float s1=aS.x,s2=aS.y,s3=aS.z;vec2 p;float a;float sz=1.;vec3 col=vec3(.90,.93,1.);const float NL=7.;
 if(s3<.74){float L=floor(s1*NL);float yl=.86-L*(1.72/(NL-1.));float dir=mod(L,2.)<.5?1.:-1.;float th=s2*6.2832+uT*dir*(.22+.05*L);
  float R=(.38+.07*sin(L*1.7+uT*.25))*(1.+(fract(s3*13.)-.5)*.13);float z=sin(th);
  p=vec2(cos(th)*R,yl+z*R*.28+(fract(s3*29.)-.5)*.014);float pl=exp(-pow((yl-(1.-uPulse*2.1))*5.,2.))*uPI;
  a=(.22+.62*(.5+.5*z))*(.7+.3*sin(th*3.+uT*.6+L))*1.25+pl*1.6;sz=1.+1.2*pow(fract(s1*97.),9.)+pl*1.2;
  col=mix(col,vec3(.72,.67,1.),uSat*step(.5,mod(L,2.))*.75);col=mix(col,vec3(1.),min(pl,1.));}
 else if(s3<.93){float u=fract(s1+uT*.06*(.45+s2*.7));float y=.98-u*1.96;float w=.035+.025*sin(y*6.+uT*.7);
  p=vec2((s2-.5)*2.*w+.02*sin(y*9.-uT*1.3+s2*7.),y);float pl=exp(-pow((y-(1.-uPulse*2.1))*9.,2.))*uPI;
  a=(.22+.5*pow(fract(s2*31.),6.))*smoothstep(0.,.08,u)*smoothstep(1.,.9,u)+pl*1.4;sz=1.+pl*1.6;col=mix(col,vec3(.80,.76,1.),.35*uSat);}
 else{vec2 b=vec2(s1*2.-1.,s2*2.-1.)+.02*vec2(sin(uT*.05+s2*30.),cos(uT*.04+s1*20.));p=vec2(b.x*uAsp,b.y);a=.08+.35*pow(fract(s1*91.),10.);sz=1.+1.4*pow(fract(s2*53.),12.);}
 gl_Position=vec4(p.x/uAsp,p.y,0.,1.);gl_PointSize=sz*uDpr;vC=col*a*uB*.8;}`;
const COLOR_F=`precision mediump float;varying vec3 vC;void main(){gl_FragColor=vec4(vC,1.);}`;
const SPARK_V=`precision highp float;attribute vec3 aS;uniform float uT,uB,uDpr,uSat,uAsp;varying vec3 vC;${HSV}
void main(){float x=(aS.x-.5)*(.25+.9*pow(aS.z,1.5))+.03*sin(uT*.8+aS.y*40.);float y=fract(aS.y+uT*.04*(.3+aS.z))*2.4-1.2;
 gl_Position=vec4(x*1.1625/uAsp,y,0.,1.);gl_PointSize=(1.+2.2*pow(fract(aS.z*17.),6.))*uDpr;float tw=.5+.5*sin(uT*3.+aS.x*90.);
 vec3 c=mix(vec3(1.),hsv(.5+.4*aS.y,.6*uSat,1.),step(.6,aS.z));vC=c*tw*.55*uB*(.25+.75*pow(fract(aS.x*51.),4.));}`;
const SPRITE_F=`precision mediump float;varying vec3 vC;void main(){vec2 d=gl_PointCoord*2.-1.;float r=dot(d,d);if(r>1.)discard;gl_FragColor=vec4(vC*exp(-r*2.6),1.);}`;
const VOR_V=`precision highp float;attribute vec3 aS;attribute float aE;uniform float uT,uB,uDpr,uPts,uAsp;uniform vec2 uCore;varying vec3 vC;
void main(){float s1=aS.x,s2=aS.y,s3=aS.z;vec2 p;float a;float sz=1.;vec3 tc=vec3(.95,.95,.93);
 if(s3<.78){float life=fract(s1-uT*.02*(.6+s2*.8));float r=.03+1.25*pow(life,1.35);float w=.55/(r+.07);
  float th=s2*6.2832+uT*w+log(r)*1.9-aE*.045*w*(.6+.4*s3);p=uCore+vec2(cos(th)*r,sin(th)*r*.46);
  a=(.24+.55*exp(-r*2.5))*smoothstep(0.,.06,life)*smoothstep(1.,.8,life);sz=1.+1.3*pow(fract(s1*37.),8.);if(r<.19)a*=sin(th)<0.?.08:.35;tc=mix(vec3(1.,.97,.92),vec3(.66,.62,1.),smoothstep(.12,.9,r));}
 else if(s3<.88){float ct=acos(2.*s1-1.),ph=s2*6.2832+uT*.25;vec3 q=vec3(sin(ct)*cos(ph),cos(ct),sin(ct)*sin(ph));float ti=.35;q=vec3(q.x,q.y*cos(ti)-q.z*sin(ti),q.y*sin(ti)+q.z*cos(ti));float bnd=.5+.5*sin(ct*14.+uT*.2);p=uCore+q.xy*.17;a=(.5+1.3*(.5+.5*q.z))*(.55+.45*bnd)*uPts;sz=1.3;tc=mix(vec3(.80,.78,1.),vec3(1.),.5+.5*q.z);}
 else{vec2 b=vec2(s1*2.-1.,s2*2.-1.)+.03*vec2(sin(uT*.07+s2*30.),cos(uT*.06+s1*20.));p=vec2(b.x*uAsp,b.y);a=(.12+.4*pow(fract(s1*91.),10.))*uPts;sz=1.+1.6*pow(fract(s2*53.),12.);}
 a*=1.-aE*uPts;gl_Position=vec4(p.x/uAsp,p.y,0.,1.);gl_PointSize=sz*uDpr;vC=tc*a*uB*(uPts>.5?.9:.5);}`;
const VOR_F=`precision highp float;varying vec3 vC;uniform float uPts;void main(){float k=1.;if(uPts>.5){vec2 d=gl_PointCoord*2.-1.;float r=dot(d,d);if(r>1.)discard;k=exp(-r*2.4);}gl_FragColor=vec4(vC*k,1.);}`;
const DYN_V=`precision highp float;attribute vec2 aP;attribute float aSz;attribute vec3 aC;varying vec3 vC;uniform float uDpr;void main(){gl_Position=vec4(aP,0.,1.);gl_PointSize=aSz*uDpr;vC=aC;}`;
const FX_F=`precision highp float;uniform vec2 uPos;uniform float uInt,uCoreW,uRays,uStreak,uAspect;uniform vec3 uCol;varying vec2 vUv;
void main(){vec2 q=vUv*2.-1.;vec2 d=(q-uPos)*vec2(uAspect,1.);float r=length(d);float a=atan(d.y,d.x);
 float core=(exp(-r*r*260.)+.012/(r*r+.012)*.22)*uCoreW;float rays=pow(abs(cos(a*3.)),60.)*exp(-r*4.5)*uRays;
 float st=exp(-abs(d.y)*90.)*exp(-abs(d.x)*1.4)*uStreak;gl_FragColor=vec4((uCol*(core+rays)+vec3(.72,.88,1.)*st)*uInt,1.);}`;
const DARK_F=`precision mediump float;uniform float uA,uEdge,uAspect;varying vec2 vUv;void main(){float a=uA;if(uEdge>.5){vec2 q=min(vUv,1.-vUv)*vec2(uAspect,1.);a*=1.-smoothstep(0.,.13,min(q.x,q.y));}gl_FragColor=vec4(0.,0.,0.,a);}`;


const PLANET_V=`precision highp float;attribute vec3 aPos;attribute vec3 aInfo;
uniform float uTime,uKind,uHover,uPulse,uDpr,uOpacity,uRadius;uniform vec2 uRes,uCenter;uniform mat3 uRot;varying vec3 vColor;varying float vAlpha;
float hash(vec3 p){return fract(sin(dot(p,vec3(12.9898,78.233,37.719)))*43758.5453);}
void main(){vec3 n=aPos;float t=uTime;float h=hash(n*5.17+aInfo);float lat=asin(clamp(n.y,-1.,1.));float lon=atan(n.z,n.x);
 vec3 p=n;float am=1.;float aux=0.;vec3 nc=vec3(0.);
 if(uKind<.5){ /* CHARTS: pasmowy gigant z pierścieniem */
  if(h<.30){aux=1.;float u=fract(h*3.3333+aInfo.y*.37);float rr=1.38+.52*u;float gap=1.-step(abs(rr-1.66),.022);
   float ang=aInfo.z*6.2832+t*.07/pow(rr,1.5);vec3 q=vec3(cos(ang)*rr,(aInfo.x-.5)*.01,sin(ang)*rr);float ti=.42;
   p=vec3(q.x,q.y*cos(ti)-q.z*sin(ti),q.y*sin(ti)+q.z*cos(ti));am=(.55+.45*sin(rr*42.+aInfo.x*3.))*gap*(.6+.4*aInfo.y)*.75;}
  else{p=n*vec3(1.,.93,1.);float l2=lon+t*.05;float b=sin(lat*14.+sin(l2*2.+lat*3.)*.6);am=.45+.55*b*b+.25*pow(sin(lat*31.+l2),8.);}
 }else if(uKind<1.5){ /* SIGNALS: rdzeń + rozchodzące się powłoki sygnału */
  if(h<.22){aux=1.;float k=floor(h/.22*3.);float ph=fract(t*.32+k/3.);p=n*(1.05+.95*ph);am=.75*pow(1.-ph,2.)*smoothstep(0.,.08,ph);}
  else{float rel=.045*sin(n.x*7.+n.y*3.+t*.05)+.03*sin(n.y*11.-n.z*6.)+.02*sin(n.z*19.+n.x*13.);p=n*(1.+rel);am=.55+.5*smoothstep(-.02,.05,rel)+.6*pow(.5+.5*sin(lat*9.-t*1.1),16.);}
 }else if(uKind<2.5){ /* MODELS & BACKTEST: siatka południków i równoleżników + księżyc */
  if(h<.05){aux=1.;float ang=t*.38;nc=vec3(cos(ang)*1.7,sin(ang)*.45,sin(ang)*1.7);p=nc+n*.15;am=.9;}
  else{float st=.2618;float dl=abs(fract(lat/st+.5)-.5)*st;float dm=abs(fract((lon+t*.06)/st+.5)-.5)*st*cos(lat);float on=1.-smoothstep(0.,.03,min(dl,dm));
   p=n;am=.10+1.15*on;}
 }else{ /* ROI: burzowa planeta ze spiralnym wirem */
  float l2=lon+t*(.10+.18*sin(lat*3.));float tur=sin(l2*4.+sin(lat*9.)*2.+t*.1)*sin(lat*16.);
  vec2 sp=vec2(mod(l2-1.+3.14159,6.28318)-3.14159,lat-.35);float d=length(sp*vec2(.6,1.));
  float spiral=sin(atan(sp.y,sp.x)*2.+d*30.-t*1.2)*exp(-d*5.);p=n*(1.+.012*tur);am=.7+.55*tur+1.6*max(spiral,0.)+.9*exp(-d*d*60.)+.35*pow(abs(sin(lat*7.+l2*.5)),6.);}
 vec3 nn=normalize(uRot*(aux>0.&&uKind>1.5&&uKind<2.5?n:p));p=uRot*p;vec3 pc=uRot*nc;
 float s=1.+uHover*.04+uPulse*.07;p*=s;
 float rim=pow(1.-abs(nn.z),1.65);float day=smoothstep(-.35,.45,dot(nn,normalize(vec3(-.65,.55,.75))));
 float al;
 if(aux>.5&&!(uKind>1.5&&uKind<2.5)){al=.42*am;if(p.z<0.&&length(p.xy)<s*1.0)al*=.12;}
 else{al=(.24+rim*.62)*am*mix(.30,1.,day)*(.55+.8*aInfo.x);al*=mix(.5,1.,smoothstep(-.3,.2,nn.z));if(aux>.5&&p.z<0.&&length(p.xy)<s)al*=.12;}
 float persp=3.7/(3.7-p.z);vec2 px=uCenter+vec2(p.x,-p.y)*uRadius*persp;vec2 c=px/uRes*2.-1.;c.y=-c.y;gl_Position=vec4(c,0.,1.);
 gl_PointSize=clamp(mix(.85,1.45,aInfo.y)*uDpr*persp*(1.+uHover*.08),.8,4.5);
 vColor=mix(vec3(.80,.83,.90),vec3(1.,1.,1.),day*.8+rim*.2);vAlpha=al*uOpacity*(1.+uHover*.5+uPulse*.8);}`;
const HOLE_F=`precision highp float;uniform vec2 uView;uniform float uDpr;uniform vec4 uH[4];varying vec2 vUv;
void main(){vec2 px=vec2(gl_FragCoord.x,uView.y-gl_FragCoord.y)/uDpr;float a=0.;for(int i=0;i<4;i++){vec4 h=uH[i];vec2 d=(px-h.xy)/vec2(h.z*1.25,h.z);a=max(a,h.w*(1.-smoothstep(.45,1.,length(d))));}gl_FragColor=vec4(0.,0.,0.,a);}`;
const HALO_F=`precision highp float;uniform vec2 uView;uniform float uDpr;uniform vec4 uH[4];varying vec2 vUv;
void main(){vec2 px=vec2(gl_FragCoord.x,uView.y-gl_FragCoord.y)/uDpr;vec3 c=vec3(0.);for(int i=0;i<4;i++){vec4 h=uH[i];float d=length(px-h.xy)/h.z;
 c+=h.w*(exp(-pow((d-1.)*7.,2.))*.16+exp(-max(d-1.,0.)*3.5)*step(1.,d)*.07+exp(-d*d*1.4)*.035);}gl_FragColor=vec4(c*vec3(.82,.88,1.),1.);}`;
const MW_V=`precision highp float;attribute vec4 aM;
uniform vec2 uP[24];uniform float uN,uT,uDpr,uOp,uW,uFlow,uNeb;uniform vec2 uRes;uniform vec4 uPl[4];varying vec3 vC;varying float vA;
void main(){float u=fract(aM.x+uT*uFlow*(.4+aM.z));float f=u*.999*(uN-1.);float fi=floor(f);float k=f-fi;vec2 a=uP[0],b=uP[1];
 for(int j=0;j<24;j++){if(float(j)==fi)a=uP[j];if(float(j)==fi+1.)b=uP[j];}
 vec2 tg=normalize(b-a+vec2(1e-4));vec2 nrm=vec2(-tg.y,tg.x);vec2 c=mix(a,b,k);float off=aM.y;
 float wob=sin(u*23.+aM.z*6.)*.25+sin(u*7.-uT*.05)*.4;vec2 px=c+nrm*(off+wob*.3)*uW;
 float core=exp(-off*off*.5);float rift=1.-.7*exp(-pow((off-.35-.3*sin(u*9.+1.3))/.3,2.));
 float al;float sz;
 if(uNeb>.5){al=.022*core*rift;sz=(22.+38.*aM.w)*uDpr;}
 else{al=(.085+.6*pow(aM.w,9.))*mix(.3,1.,core)*rift*(.7+.3*sin(uT*(1.+aM.z*2.)+aM.z*50.));sz=(.75+2.3*pow(aM.w,10.))*uDpr;}
 for(int i=0;i<4;i++){vec4 pl=uPl[i];float d=length(px-pl.xy);al*=mix(1.,smoothstep(pl.z*.92,pl.z*1.15,d),pl.w);
  float dl=length((px-vec2(pl.x,pl.y+pl.z*1.6))/vec2(pl.z*1.9,pl.z*.6));al*=mix(1.,smoothstep(.55,1.15,dl),pl.w*.85);}
 vA=al*uOp*smoothstep(0.,.04,u)*smoothstep(1.,.96,u);
 vC=mix(vec3(.74,.81,1.),vec3(1.,.94,.84),clamp(aM.z*core*1.2,0.,1.));
 vec2 cl=px/uRes*2.-1.;cl.y=-cl.y;gl_Position=vec4(cl,0.,1.);gl_PointSize=sz;}`;
const MW_F=`precision mediump float;varying vec3 vC;varying float vA;void main(){vec2 d=gl_PointCoord*2.-1.;float r=dot(d,d);if(r>1.)discard;gl_FragColor=vec4(vC*vA*exp(-r*2.6),1.);}`;
let programs={},bufs={},fbo=null,fboTex=null;
function compile(t,src){const s=gl.createShader(t);gl.shaderSource(s,src);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(s)+'\n'+src.slice(0,200));return s;}
function prog(vs,fs,attrs){const p=gl.createProgram();gl.attachShader(p,compile(gl.VERTEX_SHADER,vs));gl.attachShader(p,compile(gl.FRAGMENT_SHADER,fs));gl.linkProgram(p);if(!gl.getProgramParameter(p,gl.LINK_STATUS))throw new Error(gl.getProgramInfoLog(p));
 const o={p,a:{},u:{}};for(const a of attrs)o.a[a]=gl.getAttribLocation(p,a);const n=gl.getProgramParameter(p,gl.ACTIVE_UNIFORMS);for(let i=0;i<n;i++){const info=gl.getActiveUniform(p,i);o.u[info.name]=gl.getUniformLocation(p,info.name);}return o;}
function buf(data,usage=gl.STATIC_DRAW){const b=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.bufferData(gl.ARRAY_BUFFER,data,usage);return b;}
function attr(o,name,b,size,stride,off){const l=o.a[name];if(l<0)return;gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.enableVertexAttribArray(l);gl.vertexAttribPointer(l,size,gl.FLOAT,false,stride*4,off*4);}
function use(o){gl.useProgram(o.p);for(let i=0;i<8;i++)gl.disableVertexAttribArray(i);return o;}
function u1(o,n,v){if(o.u[n])gl.uniform1f(o.u[n],v);}function u2(o,n,a,b){if(o.u[n])gl.uniform2f(o.u[n],a,b);}
function u3(o,n,a,b,c){if(o.u[n])gl.uniform3f(o.u[n],a,b,c);}function u4(o,n,a,b,c,d){if(o.u[n])gl.uniform4f(o.u[n],a,b,c,d);}
function prng(seed){return()=>{seed|=0;seed=(seed+0x6D2B79F5)|0;let t=Math.imul(seed^(seed>>>15),1|seed);t^=t+Math.imul(t^(t>>>7),61|t);return((t^(t>>>14))>>>0)/4294967296;};}
function sphereData(count,seed){const out=new Float32Array(count*6),r=prng(seed),g=Math.PI*(3-Math.sqrt(5));for(let i=0;i<count;i++){const z=1-2*(i+.5)/count,rad=Math.sqrt(1-z*z),a=i*g+(r()-.5)*.008,k=i*6;out[k]=Math.cos(a)*rad;out[k+1]=Math.sin(a)*rad;out[k+2]=z;out[k+3]=r();out[k+4]=r();out[k+5]=r();}return out;}
function randData(count,dim,seed){const out=new Float32Array(count*dim),r=prng(seed);for(let i=0;i<out.length;i++)out[i]=r();return out;}

function setup(){
 programs.part=prog(PART_V,PART_F,['aPos','aInfo']);programs.ostreak=prog(OSTREAK_V,OSTREAK_F,['aPos','aInfo','aEnd']);
 programs.star=prog(STAR_V,STAR_F,['aPos','aInfo']);programs.sstreak=prog(SSTREAK_V,SSTREAK_F,['aPos','aInfo']);
 programs.solid=prog(QUAD_V,SOLID_F,['aQ']);programs.comp=prog(QUAD_V,COMP_F,['aQ']);programs.fx=prog(QUAD_V,FX_F,['aQ']);programs.dark=prog(QUAD_V,DARK_F,['aQ']);
 programs.fil=prog(FIL_V,COLOR_F,['aA']);programs.spark=prog(SPARK_V,SPRITE_F,['aS']);programs.vor=prog(VOR_V,VOR_F,['aS','aE']);programs.ring=prog(RING_V,SPRITE_F,['aS']);
 programs.dynL=prog(DYN_V,COLOR_F,['aP','aSz','aC']);programs.dynP=prog(DYN_V,SPRITE_F,['aP','aSz','aC']);
 const orb=sphereData(CFG.orbCount,8419);bufs.orb=buf(orb);
 const sc=CFG.streakCount,st=new Float32Array(sc*2*7),stride=CFG.orbCount/sc;
 for(let i=0;i<sc;i++){const s=Math.floor(i*stride)*6;for(let e=0;e<2;e++){const k=(i*2+e)*7;for(let j=0;j<6;j++)st[k+j]=orb[s+j];st[k+6]=e;}}bufs.ostreak=buf(st);
 bufs.star=buf(randData(CFG.starCount,6,12));bufs.dust=buf(randData(CFG.dustCount,6,78));
 const r=prng(765),ss=[];for(let i=0;i<500;i++){const x=r()*2-1,y=r()*2-1,z=r();for(let j=0;j<2;j++)ss.push(x,y,z,j,0,0);}bufs.sstreak=buf(new Float32Array(ss));
 bufs.quad=buf(new Float32Array([-1,-1,3,-1,-1,3]));
 const fr=prng(4242),fil=[];for(let f=0;f<CFG.filaments;f++){const fv=fr(),s=fr();for(let j=0;j<CFG.filSegs;j++){fil.push(fv,j/CFG.filSegs,s,fv,(j+1)/CFG.filSegs,s);}}bufs.fil=buf(new Float32Array(fil));bufs.filN=fil.length/3;
 bufs.spark=buf(randData(CFG.sparks,3,991));bufs.ring=buf(randData(16000,3,5151));
 const vr=prng(3131),vo=new Float32Array(CFG.vortexCount*2*4);for(let i=0;i<CFG.vortexCount;i++){const a=vr(),b=vr(),c=vr();for(let e=0;e<2;e++){const k=(i*2+e)*4;vo[k]=a;vo[k+1]=b;vo[k+2]=c;vo[k+3]=e;}}bufs.vor=buf(vo);
 bufs.dyn=gl.createBuffer();
 programs.planet=prog(PLANET_V,PART_F,['aPos','aInfo']);programs.hole=prog(QUAD_V,HOLE_F,['aQ']);programs.halo=prog(QUAD_V,HALO_F,['aQ']);programs.mw=prog(MW_V,MW_F,['aM']);
 const mwData=(n,seed)=>{const r=prng(seed),o=new Float32Array(n*4);for(let i=0;i<n;i++){const g=Math.sqrt(-2*Math.log(Math.max(r(),1e-6)))*Math.cos(6.2832*r());o.set([r(),clamp(g,-3.2,3.2),r(),r()],i*4);}return o;};
 bufs.mwMain=buf(mwData(72000,501));bufs.mwBranch=buf(mwData(24000,502));bufs.nebMain=buf(mwData(1800,503));bufs.nebBranch=buf(mwData(650,504));planets.forEach((q,i)=>q.buffer=buf(sphereData(q.count,2207+i*911)));
 gl.clearColor(0,0,0,1);gl.enable(gl.BLEND);gl.disable(gl.DEPTH_TEST);
}

/* ---------- stan ---------- */
const S={phase:'menu',prog:0,rate:1,reduced:!!opts.reduced,orbT:0,rot:[.11,-.22],vel:[0,0],bgT:0,
 drag:null,last:0,raf:0,hidden:false,view:{w:1,h:1,dpr:1},menuPose:{x:0,y:0,r:1},pointer:[0,0],pointerT:[0,0],token:0,frameAvg:16,focusDone:false,lost:false};
const panels=[{el:$('#panelA'),kind:'filament',name:'MODEL A',desc:'modele predykcji'},{el:$('#panelB'),kind:'vortex',name:'MODEL B',desc:'silnik sygnałów'}];
panels.forEach(p=>Object.assign(p,{status:'nodata',stale:false,t:0,speed:0,bright:.25,sat:1,lastAt:null,err:'',fx:{pulse:2,pi:0,bolts:[],queue:[],flare:0,flareY:0,next:2,chains:[],nextChain:1.5,coreFlash:0},nextResult:0,announced:0,shownStatus:null}));
const STATUS={working:{t:'ANALIZA',speed:1,bright:1,sat:1},idle:{t:'OCZEKUJE',speed:.35,bright:.55,sat:1},error:{t:'BŁĄD',speed:.15,bright:.5,sat:.2},
 loading:{t:'ŁĄCZENIE…',speed:.35,bright:.4,sat:1},offline:{t:'ROZŁĄCZONO',speed:0,bright:.25,sat:.6},nodata:{t:'BRAK DANYCH',speed:0,bright:.25,sat:.6}};


const planets=['CHARTS','SIGNALS','MODELS & BACKTEST','ROI'].map((name,i)=>({name,kind:i,count:[52000,46000,48000,50000][i],rot:[.35-.1*i,i*1.4],vel:[0,0],hover:0,pulse:0,hot:false,focus:false,layout:{x:0,y:0,r:1},el:document.querySelector('.planet[data-i="'+i+'"]')}));
let selectedPlanet=-1,pdrag=null;
function layoutPlanets(){const {w,h}=S.view,narrow=w<760;const r=narrow?Math.min(w*.11,h*.078):Math.min(h*.095,w*.064);
 const pos=narrow?[[.5,.2],[.5,.5],[.24,.78],[.76,.78]]:[[.5,.2],[.5,.52],[.165,.8],[.835,.8]];
 planets.forEach((q,i)=>{q.layout={x:pos[i][0]*w,y:pos[i][1]*h,r:r*(i===0?.82:1)};const hw=q.layout.r*(i===0?3.4:2.5),hh=q.layout.r*2.5;
  Object.assign(q.el.style,{left:(q.layout.x-hw/2)+'px',top:(q.layout.y-hh/2)+'px',width:hw+'px',height:hh+'px'});});layoutMilkyWay();}
let mwPaths={main:new Float32Array(48),branch:new Float32Array(48)};
function catmull(P,n){const out=new Float32Array(n*2),seg=P.length-1;for(let k=0;k<n;k++){const t=k/(n-1)*seg,i=Math.min(Math.floor(t),seg-1),f=t-i;
 const p0=P[Math.max(i-1,0)],p1=P[i],p2=P[i+1],p3=P[Math.min(i+2,seg)];for(let c=0;c<2;c++){out[k*2+c]=.5*((2*p1[c])+(-p0[c]+p2[c])*f+(2*p0[c]-5*p1[c]+4*p2[c]-p3[c])*f*f+(-p0[c]+3*p1[c]-3*p2[c]+p3[c])*f*f*f);}}return out;}
function layoutMilkyWay(){const {w,h}=S.view,L=planets.map(q=>[q.layout.x,q.layout.y]);
 mwPaths.main=catmull([[-.06*w,1.04*h],L[2],L[1],L[3],[1.06*w,1.04*h]],24);
 mwPaths.branch=catmull([L[1],[L[1][0]-.03*w,(L[1][1]+L[0][1])/2],L[0],[L[0][0]+.04*w,-.06*h]],24);}
function drawMilkyWay(op){if(op<.002)return;const {w,h,dpr}=S.view,o=use(programs.mw),PL=new Float32Array(16);
 planets.forEach((q,i)=>PL.set([q.layout.x,q.layout.y,q.layout.r*(1+q.hover*.04),1],i*4));
 u2(o,'uRes',w,h);u1(o,'uDpr',dpr);u1(o,'uT',S.reduced?0:S.orbT);u1(o,'uN',24);gl.uniform4fv(o.u['uPl[0]'],PL);gl.blendFunc(gl.ONE,gl.ONE);
 const run=(path,b,n,wid,flow,neb,a)=>{gl.uniform2fv(o.u['uP[0]'],path);u1(o,'uW',wid);u1(o,'uFlow',flow);u1(o,'uNeb',neb);u1(o,'uOp',op*a);attr(o,'aM',b,4,4,0);gl.drawArrays(gl.POINTS,0,n);};
 run(mwPaths.main,bufs.nebMain,1800,h*.05,.0025,1,1);run(mwPaths.branch,bufs.nebBranch,650,h*.026,.0035,1,.8);
 run(mwPaths.main,bufs.mwMain,72000,h*.045,.0025,0,1);run(mwPaths.branch,bufs.mwBranch,24000,h*.022,.0035,0,1.1);}
function drawPlanets(T,dt){const {w,h,dpr}=S.view;let any=false;
 if(T.planets&&T.planets.some(v=>v>.002)){const o=use(programs.hole),H=new Float32Array(16);planets.forEach((q,i)=>{const L=pose(q,i,T);H.set([L.x,L.y+(i===SUB.pi&&T.c0?0:L.r*.55),L.r*(i===0?2.5:2.15),.9*(T.planets[i]||0)*(i===SUB.pi&&T.c0?T.c0.op:1)],i*4);});
  u2(o,'uView',canvas.width,canvas.height);u1(o,'uDpr',dpr);gl.uniform4fv(o.u['uH[0]'],H);gl.blendFunc(gl.ZERO,gl.ONE_MINUS_SRC_ALPHA);quad(o);gl.blendFunc(gl.ONE,gl.ONE);
  drawMilkyWay(T.planets.reduce((a,b)=>a+b,0)/4*T.mw);
  const g=use(programs.halo),G=new Float32Array(16);planets.forEach((q,i)=>{const L=pose(q,i,T),op=(T.planets[i]||0)*(i===SUB.pi&&T.c0?T.c0.op:1);G.set([L.x+S.pointer[0]*4,L.y+S.pointer[1]*3,L.r*lerp(.6,1,easeOut3(op))*(1+q.hover*.04),op*(1+q.hover*.8+q.pulse*.8)],i*4);});
  u2(g,'uView',canvas.width,canvas.height);u1(g,'uDpr',dpr);gl.uniform4fv(g.u['uH[0]'],G);quad(g);}
 planets.forEach((q,i)=>{const op=T.planets?T.planets[i]:0;q.hover=lerp(q.hover,(q.hot||q.focus||pdrag?.i===i||selectedPlanet===i)&&S.phase==='forex'&&SUB.state==='none'&&!S.reduced?1:0,1-Math.exp(-dt*5));
  q.pulse=Math.max(0,q.pulse-dt/0.9);if(!(pdrag&&pdrag.i===i)){if(!S.reduced){q.rot[0]+=q.vel[0]*dt;q.rot[1]+=q.vel[1]*dt+dt*(.05+i*.01);}const dc=Math.exp(-dt*2.2);q.vel=q.vel.map(v=>v*dc);}q.rot[0]=clamp(q.rot[0],-1.4,1.4);
  if(op<.002)return;any=true;const o=use(programs.planet);
  const bob=S.reduced?0:Math.sin(S.orbT*.3+i*1.7)*2.5,pz=S.reduced?0:Math.sin(Math.PI*clamp(q.pulse))*1;
  u1(o,'uTime',S.reduced?0:S.orbT+i*7.3);u1(o,'uKind',i);u1(o,'uHover',q.hover);u1(o,'uPulse',pz);u1(o,'uDpr',dpr);const L=pose(q,i,T),opx=op*(i===SUB.pi&&T.c0?T.c0.op:1);u1(o,'uOpacity',opx);u1(o,'uRadius',L.r*lerp(.6,1,easeOut3(op)));
  u2(o,'uRes',w,h);u2(o,'uCenter',L.x+S.pointer[0]*4,L.y+bob+S.pointer[1]*3);gl.uniformMatrix3fv(o.u.uRot,false,rotMatrix(q.rot[0],q.rot[1]));
  attr(o,'aPos',q.buffer,3,6,0);attr(o,'aInfo',q.buffer,3,6,3);gl.blendFunc(gl.ONE,gl.ONE);gl.drawArrays(gl.POINTS,0,q.count);});
 planets.forEach((q,i)=>{let op=T.planets?T.planets[i]:0;if(i===SUB.pi&&T.c0)op*=1-smooth(seg(SUB.p*SCREENS[SUB.pi].inMs,0,400));q.el.style.visibility=op>.02?'visible':'hidden';q.el.style.opacity=op;q.el.style.pointerEvents=op>.5&&SUB.state==='none'?'':'none';});}
function pose(q,i,T){const L=q.layout;if(i!==SUB.pi||!T.c0)return L;const c=T.c0;return {x:lerp(L.x,S.view.w*.5,c.move),y:lerp(L.y,S.view.h*.48,c.move),r:L.r*c.rMul};}
function choosePlanet(i){if(S.phase!=='forex'||SUB.state!=='none')return;if(SCREENS[i]){selectedPlanet=-1;opts.onChoose&&opts.onChoose(i);return;}selectedPlanet=i;planets.forEach((q,j)=>q.el.setAttribute('aria-pressed',String(j===i)));planets[i].pulse=1;
 announce('Wybrano '+planets[i].name+'. Ekran tej sekcji nie jest jeszcze zaprojektowany.');
 window.dispatchEvent(new CustomEvent('pmw:forex-section-selected',{detail:Object.freeze({section:planets[i].name,preview:true})}));}
function resize(){
 const w=innerWidth,h=innerHeight,dpr=Math.min(devicePixelRatio||1,S.q==='low'?1:CFG.dprCap);S.view={w,h,dpr};
 canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);
 const r=Math.min(h*.2,w*.16);S.menuPose=S.startPose?{...S.startPose}:{x:w*.5,y:h*.46,r};
 const b=$('#forex'),hit=r*2.3;Object.assign(b.style,{left:(S.menuPose.x-hit/2)+'px',top:(S.menuPose.y-hit/2)+'px',width:hit+'px',height:hit+'px'});
 
 layoutPlanets();
 if(fboTex){gl.deleteTexture(fboTex);gl.deleteFramebuffer(fbo);}
 fboTex=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,fboTex);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,canvas.width,canvas.height,0,gl.RGBA,gl.UNSIGNED_BYTE,null);
 gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
 gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
 fbo=gl.createFramebuffer();gl.bindFramebuffer(gl.FRAMEBUFFER,fbo);gl.framebufferTexture2D(gl.FRAMEBUFFER,gl.COLOR_ATTACHMENT0,gl.TEXTURE_2D,fboTex,0);
 gl.clear(gl.COLOR_BUFFER_BIT);gl.bindFramebuffer(gl.FRAMEBUFFER,null);
}
function rotMatrix(rx,ry){const sx=Math.sin(rx),cx=Math.cos(rx),sy=Math.sin(ry),cy=Math.cos(ry);return new Float32Array([cy,sy*sx,-sy*cx,0,cx,sx,sy,-cy*sx,cy*cx]);}

/* ---------- tło: cykl 66 s (P) ---------- */
function bgPhase(T){T=((T%CFG.bgCycle)+CFG.bgCycle)%CFG.bgCycle;let density,sparse;
 if(T<27){density=.35+.65*smooth(T/27);sparse=0;}else if(T<29.5){density=1;sparse=0;}else if(T<30){density=1;sparse=smooth((T-29.5)/.5);}
 else if(T<63){density=.35;sparse=1;}else{density=.35;sparse=1-smooth((T-63)/3);}
 const line=T<29.5?0:T<30?smooth((T-29.5)/.5):T<34?1-smooth((T-30)/4):0;
 const decay=lerp(.86+.1*density,.55,sparse);return {T,density,sparse,line,decay};}
function cores(T,line){const TAU=Math.PI*2;const mid=[.1*Math.sin(T*.13),.05*Math.cos(T*.17)+.02,0];
 let a=1.2+.9*Math.sin(T*TAU/41),d=.42+.2*Math.sin(T*TAU/23);a=lerp(a,Math.PI/2,line);d=lerp(d,.55,line);
 const v=[Math.cos(a)*d,Math.sin(a)*d,.25*Math.sin(T*.3)*(1-line)];
 return [[mid[0]+v[0],mid[1]+v[1],v[2]],[mid[0]-v[0],mid[1]-v[1],-v[2]]];}

/* ---------- oś czasu przejścia (P) ---------- */
function timeline(){
 const p=S.prog;
 if(S.reduced){const mf=1-smooth(p*2),fx=smooth(p*2-1);return {planets:[fx,fx,fx,fx],menuFade:mf,sideFade:mf,center:0,camD:3.7,fov:1,warp:0,streak:0,orbBright:1,orbOp:mf,morph:p>=.5?1:0,bgOp:fx,field:fx,corners:fx,pA:fx,pB:fx,ret:fx,stars:lerp(1,.35,fx)};}
 const ms=p*CFG.diveMs;const kc=seg(ms,400,1500);
 const camD=lerp(3.7,.15,kc<.75?Math.pow(kc/.75,2.2)*.75:kc);
 const orbBright=lerp(1,.55,smooth(seg(ms,1700,400)));const morph=easeIO3(seg(ms,1800,1100));
 return {menuFade:1-easeOut3(seg(ms,0,400)),center:ease4(seg(ms,0,900)),rotMul:lerp(1,.35,smooth(seg(ms,0,1200))),camD,
  fov:lerp(1,1/1.35,smooth(seg(ms,900,1000))),warp:Math.sin(Math.PI*seg(ms,700,1400))*.72,streak:Math.sin(Math.PI*seg(ms,1300,600)),
  orbBright,orbOp:orbBright,morph,bgOp:1,field:smooth(seg(ms,2400,800)),corners:easeOut3(seg(ms,2400,800)),
  planets:[0,1,2,3].map(i=>smooth(seg(ms,2400+i*100,500))),pA:smooth(seg(ms,2700,500)),pB:smooth(seg(ms,2800,500)),ret:smooth(seg(ms,2900,300)),stars:lerp(1,.35,morph)};
}

/* ---------- fazy ---------- */
function setPhase(ph){S.phase=ph;root.dataset.state=ph;$('#forex-screen').inert=ph!=='forex';$('#fx-menu').inert=ph!=='menu';opts.onPhase&&opts.onPhase(ph);}
function announce(t){$('#fx-announcer').textContent=t;}
function startDive(){if(S.phase!=='menu')return;if(!S.bgStarted){S.bgStarted=true;S.bgT=8;}setPhase('dive');S.focusDone=false;connectModels();wake();}
function surface(){if(SUB.state!=='none')return;if(S.phase==='dive'||S.phase==='forex'){pdrag=null;planets.forEach(q=>{q.hot=false;q.focus=false;});setPhase('surface');disconnectModels();wake();}}

/* ---------- stan paneli z danych bota (S3 §1) – ustawiany z Reacta przez setPanel / result ---------- */
function connectModels(){panels.forEach(p=>{if(p.status==='nodata'&&!p.lastAt)setStatus(p,'loading');});opts.onConnect&&opts.onConnect();}
function disconnectModels(){S.token++;}
function setStatus(p,s,err){p.status=s;p.err=s==='error'?(err||'błąd odczytu z API'):'';updatePanelText(p);}
function tzLabel(){const o=-new Date().getTimezoneOffset()/60;return 'UTC'+(o>=0?'+':'')+o;}
function fmt(d){return d.toLocaleTimeString('pl-PL',{hour:'2-digit',minute:'2-digit',second:'2-digit'})+' '+tzLabel();}
function updatePanelText(p){const st=STATUS[p.status];p.el.classList.toggle('stale',p.stale);p.el.dataset.active=p.status==='working'?'1':'0';
 const label=`${p.name} – ${p.desc}: ${st.t}${p.stale?', nieaktualne':''}, ostatni wynik ${p.lastAt?fmt(p.lastAt):'brak'}${p.err?', '+p.err:''}`;p.el.setAttribute('aria-label',label);
 const now=performance.now();if(S.phase==='forex'&&p.shownStatus!==p.status&&now-p.announced>5000){announce(label);p.announced=now;}p.shownStatus=p.status;}
function triggerResult(p){p.lastAt=new Date();p.stale=false;updatePanelText(p);
 if(p.kind==='filament'){p.fx.pulse=0;p.fx.pi=1;}
 else{spawnChain(p,1);p.fx.coreFlash=1;}}

/* ---------- efekty paneli ---------- */
const CORE=[.12,.06];
function makeBolt(){const pts=[];let x=(Math.random()-.5)*.12;for(let i=0;i<=40;i++){const y=1.15-i/40*2.3;x+=(Math.random()-.5)*.07;x*=.93;pts.push([x+.04*Math.sin(y*5+Math.random()),y]);}return {pts,life:.26,age:0,jit:0};}
function spawnChain(p,forceCore){const r=Math.random(),type=forceCore?1:(r<.4?0:r<.7?1:2);let P;
 if(type===0)P=[[.82,.95],[-.75,.9],CORE];else if(type===1)P=[[CORE[0]-.05,-1.15],[CORE[0]-.18,-.35],CORE];else P=[[-.85,.2],[0,.78],[.85,.5]];
 p.fx.chains.push({P,age:0,dur:2.4,n:22,into:type!==2});}
function bez(P,t){const a=1-t;return [a*a*P[0][0]+2*a*t*P[1][0]+t*t*P[2][0],a*a*P[0][1]+2*a*t*P[1][1]+t*t*P[2][1]];}
function updatePanel(p,dt,nowS){
 const tgt=STATUS[p.status],k=1-Math.exp(-dt*5);p.speed=lerp(p.speed,tgt.speed,k);p.bright=lerp(p.bright,tgt.bright*(p.stale?.6:1),k);p.sat=lerp(p.sat,tgt.sat,k);
 const frozen=S.reduced;const sdt=frozen?0:dt*p.speed;p.t+=sdt;
 const fx=p.fx;
 if(p.kind==='filament'){
  if(p.status==='working'&&!frozen){fx.next-=sdt;if(fx.next<=0&&fx.pulse>1.1){fx.pulse=0;fx.pi=.45;fx.next=3+Math.random()*2;}}
  if(!frozen&&fx.pulse<=1.2)fx.pulse+=dt/1.9;
 }else{
  if(p.status==='working'&&!frozen){fx.nextChain-=sdt;if(fx.nextChain<=0){spawnChain(p,0);fx.nextChain=2.8+Math.random()*1.7;}}
  fx.chains.forEach(c=>{c.age+=frozen?0:(c.into&&p.status!=='working'?dt:sdt);if(c.into&&c.age>=c.dur&&!c.flashed){c.flashed=1;fx.coreFlash=Math.max(fx.coreFlash,.7);}});
  fx.chains=fx.chains.filter(c=>c.age<c.dur+.8);fx.coreFlash=Math.max(0,fx.coreFlash-(frozen?0:dt/1.2));
 }
}
function dynDraw(o,data,mode,count){gl.bindBuffer(gl.ARRAY_BUFFER,bufs.dyn);gl.bufferData(gl.ARRAY_BUFFER,data,gl.DYNAMIC_DRAW);
 attr(o,'aP',bufs.dyn,2,6,0);attr(o,'aSz',bufs.dyn,1,6,2);attr(o,'aC',bufs.dyn,3,6,3);gl.drawArrays(mode,0,count);}
function quad(o){attr(o,'aQ',bufs.quad,2,2,0);gl.drawArrays(gl.TRIANGLES,0,3);}
let PA=.75;
function dark(a,edge){if(a<=0)return;const o=use(programs.dark);u1(o,'uA',a);u1(o,'uEdge',edge?1:0);u1(o,'uAspect',PA);gl.blendFunc(gl.ZERO,gl.ONE_MINUS_SRC_ALPHA);quad(o);gl.blendFunc(gl.ONE,gl.ONE);}
function fx(pos,int,coreW,rays,streak,col){const o=use(programs.fx);u2(o,'uPos',pos[0],pos[1]);u1(o,'uInt',int);u1(o,'uCoreW',coreW);u1(o,'uRays',rays);u1(o,'uStreak',streak);u1(o,'uAspect',PA);u3(o,'uCol',col[0],col[1],col[2]);quad(o);}
function drawPanel(p,op){
 if(op<=.002)return;const r=p.el.querySelector('.view').getBoundingClientRect(),d=S.view.dpr;
 const x=Math.round(r.left*d),y=Math.round((S.view.h-r.bottom)*d),w=Math.round(r.width*d),h=Math.round(r.height*d);
 gl.enable(gl.SCISSOR_TEST);gl.viewport(x,y,w,h);gl.scissor(x,y,w,h);PA=w/h;
 dark(op*.94,false);gl.blendFunc(gl.ONE,gl.ONE);const B=p.bright*op;
 if(p.kind==='filament'){
  const pu=Math.min(p.fx.pulse,1.2),pin=p.fx.pulse<=1.15?p.fx.pi*Math.min(1,(1.15-p.fx.pulse)*6):0;
  let o=use(programs.ring);u1(o,'uT',p.t);u1(o,'uB',B);u1(o,'uDpr',d);u1(o,'uSat',p.sat);u1(o,'uAsp',PA);u1(o,'uPulse',pu);u1(o,'uPI',pin);attr(o,'aS',bufs.ring,3,3,0);gl.drawArrays(gl.POINTS,0,16000);
  if(pin>0)fx([0,1-pu*2.1],pin*op*.8,.7,.35,.5,[.88,.86,1]);
  fx([0,-.98],B*.25,.5,0,.1,[.85,.82,1]);
  for(const b of []){const life=1-b.age/b.life,a=life*op,L=[],P=[];
   for(let off=-1;off<=1;off++)for(let i=0;i<b.pts.length-1;i++){const q0=b.pts[i],q1=b.pts[i+1],ox=off*2/w,c=(off?.35:1)*a;L.push(q0[0]*1.55/PA+ox,q0[1],1,c,c,c,q1[0]*1.55/PA+ox,q1[1],1,c,c,c);}
   for(let i=0;i<b.pts.length;i+=2){const q=b.pts[i],c=.16*a;P.push(q[0]*1.55/PA,q[1],16,c*.8,c*.9,c);}
   dynDraw(use(programs.dynL),new Float32Array(L),gl.LINES,L.length/6);const o2=use(programs.dynP);u1(o2,'uDpr',d);dynDraw(o2,new Float32Array(P),gl.POINTS,P.length/6);
   fx([b.pts[20][0]*1.55/PA,b.pts[20][1]],a*.7,.6,.8,.9,[1,1,1]);}
 }else{
  let o=use(programs.vor);u1(o,'uT',p.t);u1(o,'uB',B);u1(o,'uDpr',d);u2(o,'uCore',CORE[0]*PA/.75,CORE[1]);u1(o,'uAsp',PA);attr(o,'aS',bufs.vor,3,4,0);attr(o,'aE',bufs.vor,1,4,3);
  u1(o,'uPts',0);gl.drawArrays(gl.LINES,0,CFG.vortexCount*2);u1(o,'uPts',1);gl.drawArrays(gl.POINTS,0,CFG.vortexCount*2);
  const P=[];for(const c of p.fx.chains){const head=ease4(c.age/c.dur);for(let k=0;k<c.n;k++){const t=head-k*.028;if(t<0||t>1)continue;const q=bez(c.P,t),f=1-k/c.n,fade=c.age>c.dur?clamp(1-(c.age-c.dur)/.8):1,a=.9*Math.sqrt(f)*fade*B;P.push(q[0]/.75,q[1],1.2+4.2*f,a,a,a*.97);}}
  if(P.length){const o2=use(programs.dynP);u1(o2,'uDpr',d);dynDraw(o2,new Float32Array(P),gl.POINTS,P.length/6);}
  fx([CORE[0]/.75,CORE[1]],B*(.38+p.fx.coreFlash*.9),1,.25+p.fx.coreFlash,.06,[1,1,.98]);
 }
 dark(op,true);gl.disable(gl.SCISSOR_TEST);gl.viewport(0,0,canvas.width,canvas.height);
}

/* ---------- pętla ---------- */
function wake(){if(!S.raf&&!S.hidden&&!S.lost){S.last=performance.now();S.raf=requestAnimationFrame(tick);}}
function tick(now){
 S.raf=0;if(S.hidden||S.lost||S.disposed)return;const dt=FIXED_DT||Math.min((now-(S.last||now))/1000,.1);S.last=now;S.frameAvg=lerp(S.frameAvg,dt*1000,.05);
 const {w,h,dpr}=S.view;
 if(S.phase==='dive'){S.prog+=dt*S.rate/((S.reduced?CFG.reducedMs:CFG.diveMs)/1000);if(S.prog>=1){S.prog=1;setPhase('forex');panels.forEach(p=>updatePanelText(p,true));
  if(SUB.state==='none')planets[0].el.focus({preventScroll:true});announce('Tryb FOREX. Sekcje: CHARTS, SIGNALS, MODELS & BACKTEST, ROI.');opts.onForexReady&&opts.onForexReady();}}
 else if(S.phase==='surface'){S.prog-=dt*S.rate/((S.reduced?CFG.reducedMs:CFG.surfaceMs)/1000);if(S.prog<=0){S.prog=0;setPhase('menu');opts.onSurfaced&&opts.onSurfaced();}}
 const T=timeline();T.mw=1;
 const SCR=SCREENS[SUB.pi];
 if(SUB.state==='in'){SUB.p+=dt*S.rate/((S.reduced?CFG.reducedMs:SCR.inMs)/1000);if(SUB.p>=1){SUB.p=1;SUB.state='on';root.dataset.sub='on';$(SCR.el).inert=false;const fe=$(SCR.focus);if(fe)fe.focus({preventScroll:true});announce(SCR.say());opts.onSubState&&opts.onSubState('on',SUB.pi);}}
 else if(SUB.state==='out'){SUB.p-=dt*S.rate/((S.reduced?CFG.reducedMs:SCR.outMs)/1000);if(SUB.p<=0){SUB.p=0;SUB.state='none';root.dataset.sub='none';planets[SUB.pi].el.focus({preventScroll:true});opts.onSubState&&opts.onSubState('none',SUB.pi);if(S.pendingSurface){S.pendingSurface=false;surface();}else if(S.pendingSub!=null){const n=S.pendingSub;S.pendingSub=null;subOpen(n);}}}
 const cms=SUB.p*SCR.inMs;
 if(SUB.p>0){const of=S.reduced?1-smooth(SUB.p*2):1-smooth(seg(cms,0,650)),dimB=S.reduced?smooth(SUB.p):smooth(seg(cms,600,900));
  T.planets=T.planets.map((v,i)=>i===SUB.pi?v:v*of);T.pA*=of;T.pB*=of;T.corners*=of;T.mw=of;T.c0=SCR.planet(cms);
  T.warp=Math.max(T.warp||0,S.reduced?0:Math.sin(Math.PI*seg(cms,350,1300))*.55);T.bgOp*=lerp(1,.3,dimB);T.stars*=lerp(1,.55,dimB);}
 SCR.tick(now);
 S.pointer=S.pointer.map((v,i)=>lerp(v,S.reduced?0:S.pointerT[i],1-Math.exp(-dt*4)));
 if(!S.reduced)S.orbT+=dt;
 if(!S.drag){if(!S.reduced){S.rot[0]+=S.vel[0]*dt;S.rot[1]+=S.vel[1]*dt+dt*.065*(T.rotMul??1);}const dc=Math.exp(-dt*2.2);S.vel=S.reduced?[0,0]:S.vel.map(v=>v*dc);}
 S.rot[0]=clamp(S.rot[0],-1.8,1.8);
 if(T.morph>0&&!S.reduced)S.bgT+=dt;
 const nowS=now/1000;panels.forEach(p=>updatePanel(p,dt,nowS));
 /* DOM */
 const mf=T.menuFade;
 panels[0].el.style.opacity=T.pA;panels[1].el.style.opacity=T.pB;panels.forEach(p=>p.el.style.setProperty('--k',T.corners));
 panels.forEach(p=>p.el.querySelectorAll('.corner').forEach(c=>c.style.setProperty('--k',T.corners)));
 $('#fx-return').style.opacity=T.ret;
 /* 1) trail FBO */
 const BP=bgPhase(S.bgT),[c0,c1]=cores(BP.T,BP.line);
 gl.bindFramebuffer(gl.FRAMEBUFFER,fbo);gl.viewport(0,0,canvas.width,canvas.height);
 const decay=S.reduced?0:Math.pow(BP.decay,dt*60)*T.morph;
 let o=use(programs.solid);gl.blendFunc(gl.ZERO,gl.SRC_COLOR);u4(o,'uC',decay,decay,decay,1);quad(o);
 if(decay>0){gl.blendEquation(gl.FUNC_REVERSE_SUBTRACT);gl.blendFunc(gl.ONE,gl.ONE);u4(o,'uC',1.5/255,1.5/255,1.5/255,0);quad(o);gl.blendEquation(gl.FUNC_ADD);}
 gl.blendFunc(gl.ONE,gl.ONE);
 const mp=S.menuPose,cx=lerp(mp.x+S.pointer[0]*5*mf,w*.5,T.center),cy=lerp(mp.y+S.pointer[1]*3*mf,h*.5,T.center),focal=mp.r*3.7*T.fov,rm=rotMatrix(S.rot[0],S.rot[1]);
 const bgScale=h*.34,bgC=[w*.5,h*.42];
 o=use(programs.part);u1(o,'uTime',S.orbT);u1(o,'uDpr',dpr);u1(o,'uCamD',T.camD);u1(o,'uNear',.02);u1(o,'uFocal',focal);u1(o,'uMorph',T.morph);
 u1(o,'uOrbOp',T.orbOp);u1(o,'uBgOp',T.bgOp*(.6+.4*T.field)*lerp(1,.42,T.morph));u1(o,'uBgT',S.bgT);u1(o,'uDensity',BP.density);u1(o,'uSparse',BP.sparse);u1(o,'uLine',BP.line);u1(o,'uBgScale',bgScale);
 u2(o,'uRes',w,h);u2(o,'uCenter',cx,cy);u2(o,'uBgCenter',bgC[0],bgC[1]);gl.uniformMatrix3fv(o.u.uRot,false,rm);u3(o,'uC0',...c0);u3(o,'uC1',...c1);
 attr(o,'aPos',bufs.orb,3,6,0);attr(o,'aInfo',bufs.orb,3,6,3);gl.drawArrays(gl.POINTS,0,CFG.orbCount);
 if(T.streak>.001){o=use(programs.ostreak);u1(o,'uTime',S.orbT);u1(o,'uCamD',T.camD);u1(o,'uCamD2',T.camD+.35*T.streak);u1(o,'uNear',.02);u1(o,'uFocal',focal);u1(o,'uStreak',T.streak);u1(o,'uOrbOp',T.orbOp);
  u2(o,'uRes',w,h);u2(o,'uCenter',cx,cy);gl.uniformMatrix3fv(o.u.uRot,false,rm);attr(o,'aPos',bufs.ostreak,3,7,0);attr(o,'aInfo',bufs.ostreak,3,7,3);attr(o,'aEnd',bufs.ostreak,1,7,6);gl.drawArrays(gl.LINES,0,CFG.streakCount*2);}
 /* 2) ekran */
 gl.bindFramebuffer(gl.FRAMEBUFFER,null);gl.viewport(0,0,canvas.width,canvas.height);gl.clear(gl.COLOR_BUFFER_BIT);gl.blendFunc(gl.ONE,gl.ONE);
 o=use(programs.star);u2(o,'uPointer',S.pointer[0],S.pointer[1]);u1(o,'uTime',S.orbT);u1(o,'uDpr',dpr);u1(o,'uOpacity',T.stars);u1(o,'uWarp',T.warp);
 u1(o,'uDust',0);attr(o,'aPos',bufs.star,3,6,0);attr(o,'aInfo',bufs.star,3,6,3);gl.drawArrays(gl.POINTS,0,CFG.starCount);
 u1(o,'uDust',1);attr(o,'aPos',bufs.dust,3,6,0);attr(o,'aInfo',bufs.dust,3,6,3);gl.drawArrays(gl.POINTS,0,CFG.dustCount);
 if(T.warp>.005){o=use(programs.sstreak);u1(o,'uWarp',T.warp);u1(o,'uOpacity',T.stars);attr(o,'aPos',bufs.sstreak,3,6,0);attr(o,'aInfo',bufs.sstreak,3,6,3);gl.drawArrays(gl.LINES,0,1000);}
 const proj=c=>{const pr=4/(4-c[2]);return [bgC[0]+c[0]*bgScale*pr,bgC[1]-c[1]*bgScale*pr];};
 const gI=T.morph*T.bgOp*(.4+.6*T.field)*lerp(.5+.7*BP.density,.85,BP.sparse),rays=lerp(BP.density,.12,BP.sparse);
 const k0=proj(c0),k1=proj(c1);
 o=use(programs.comp);gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,fboTex);if(o.u.uTex)gl.uniform1i(o.u.uTex,0);
 u2(o,'uRes',w,h);u2(o,'uView',canvas.width,canvas.height);u1(o,'uDpr',dpr);u4(o,'uK0',k0[0],k0[1],gI*.32,rays*.4);u4(o,'uK1',k1[0],k1[1],gI*.27,rays*.4);quad(o);
 /* 3) panele */
 drawPlanets(T,dt);
 drawPanel(panels[0],T.pA);drawPanel(panels[1],T.pB);
 {const on=SUB.p>0,own=!!SCR.own;$('#sub-screen').style.opacity=on&&!own?(S.reduced?smooth(SUB.p):smooth(seg(cms,SCR.inMs*.72,500))):0;subDraw(on&&!own?SUB.pi:-1,cms,dt);
 for(const k in SCREENS){if(!SCREENS[k].own)continue;const o=SUB.p>0&&+k===SUB.pi;$(SCREENS[k].el).style.opacity=o?1:0;if(o)SCREENS[k].draw(cms,dt);}}
 if(S.phase!=='dive'&&S.phase!=='surface'&&S.prog>=1&&!S.focusDone){S.focusDone=true;}
 quality(dt);
 S.raf=requestAnimationFrame(tick);
}
/* ---------- ekrany planet: przejścia planety (z REF_B) i tło ekranu (canvas 2D) ---------- */
const SUB={state:'none',p:0,pi:0};
const PLANET_FN=[
 cms=>({move:easeIO3(seg(cms,0,800)),rMul:1+Math.pow(seg(cms,450,1050),2.2)*9,op:1-smooth(seg(cms,900,600))}),
 cms=>({move:easeIO3(seg(cms,0,800)),rMul:1+easeOut3(seg(cms,300,900))*1.4,op:1-smooth(seg(cms,800,700))}),
 cms=>({move:easeIO3(seg(cms,0,800)),rMul:1+easeOut3(seg(cms,300,1000))*1.8,op:1-smooth(seg(cms,900,600))}),
 cms=>{const k=seg(cms,250,1100);return {move:easeIO3(seg(cms,0,800)),rMul:1+Math.pow(k,2.2)*2.6,op:1-smooth(seg(cms,550,450))};}];
const NAMES=['CHARTS','SIGNALS','MODELS & BACKTEST','ROI'];
const SCREENS={};[2400,2600,2600,2700].forEach((inMs,i)=>{SCREENS[i]={inMs,outMs:1500,el:'#sub-screen',tick:()=>{},focus:'#sub-screen [data-autofocus]',
 planet:cms=>S.reduced?{move:0,rMul:1,op:1-smooth(SUB.p*2)}:PLANET_FN[i](cms),say:()=>NAMES[i]+'. '+(DATA[i]&&DATA[i].say?DATA[i].say:'')};});
/* pakiet CHARTS 1:1: ekran z własną implementacją (jak SCREENS[0] we wzorcu REF_B: el, planet, draw, tick, open, close, say) */
for(const k in (opts.screens||{})){const impl=opts.screens[k];impl.bind&&impl.bind(S,SUB);SCREENS[k]={...impl.screen,own:true};}
const DATA={};
const sub2=$('#sub-canvas'),sctx=sub2.getContext('2d');let subSeed=1;
function srnd(){subSeed=(subSeed*16807)%2147483647;return subSeed/2147483647;}
let NEB=null;
function nebula(w,h,cols){if(NEB&&NEB.w===w&&NEB.h===h&&NEB.cols===cols)return NEB.c;const c=document.createElement('canvas');c.width=w;c.height=h;const g=c.getContext('2d');subSeed=77;
 for(let k=0;k<24;k++){const x=srnd()*w,y=srnd()*h,rad=60+srnd()*200,col=cols[k%cols.length],a=.04+srnd()*.08,gr=g.createRadialGradient(x,y,0,x,y,rad);gr.addColorStop(0,col.replace('A',a));gr.addColorStop(1,col.replace('A',0));g.fillStyle=gr;g.fillRect(x-rad,y-rad,rad*2,rad*2);}
 for(let k=0;k<1300;k++){g.fillStyle=`rgba(230,236,255,${srnd()*srnd()*.5})`;const s=srnd()<.03?1.5:.8;g.fillRect(srnd()*w,srnd()*h,s,s);}NEB={c,w,h,cols};return c;}
function subDraw(i,cms,dt){const {w,h,dpr}=S.view;if(sub2.width!==Math.round(w*dpr)){sub2.width=Math.round(w*dpr);sub2.height=Math.round(h*dpr);}
 sctx.setTransform(dpr,0,0,dpr,0,0);sctx.clearRect(0,0,w,h);if(i<0||SUB.p<=0)return;const red=S.reduced,tt=performance.now()/1000;
 const F=(a,d)=>red?smooth(SUB.p*2-1):smooth(seg(cms,a,d));const q=planets[i],L0=q.layout,mv=red?0:easeIO3(seg(cms,0,800)),pc=[lerp(L0.x,w*.5,mv),lerp(L0.y,h*.48,mv)],diag=Math.hypot(w,h);
 const ctx=sctx;
 if(i===0){ /* CHARTS: pasy planety → siatka wykresu */
  const g=F(1100,900);if(g>0){ctx.strokeStyle=`rgba(200,210,235,${.06*g})`;ctx.lineWidth=1;for(let x=0;x<w;x+=80){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke();}for(let y=0;y<h;y+=60){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();}}}
 else if(i===1){ /* SIGNALS: fala sygnału z planety → konstelacja */
  if(!red)for(const st of [400,650,900]){const k=seg(cms,st,1100);if(k<=0||k>=1)continue;const rad=lerp(L0.r*1.2,diag*.75,easeOut3(k)),a=(1-k)*.7;ctx.strokeStyle=`rgba(210,200,255,${a})`;ctx.lineWidth=1.4;ctx.beginPath();ctx.arc(pc[0],pc[1],rad,0,6.283);ctx.stroke();}
  const R=rectOf('#sg-orbit');if(R&&R.w>50){const nA=F(1150,700);ctx.save();ctx.beginPath();ctx.rect(R.l,R.t,R.w,R.h);ctx.clip();ctx.globalAlpha=nA;ctx.drawImage(nebula(Math.round(R.w),Math.round(R.h),['rgba(70,58,150,A)','rgba(30,90,120,A)','rgba(110,60,140,A)','rgba(40,50,110,A)']),R.l,R.t);ctx.globalAlpha=1;
   const cx=R.l+R.w/2,cy=R.t+R.h*.5,Rx=Math.min(R.w*.5,R.h*.95)-16,Ry=Math.min(Rx*.68,R.h*.45),rings=[.32,.62,.92];
   rings.forEach((rr,k)=>{const oa=red?1:easeIO3(seg(cms,1250+k*160,700));ctx.strokeStyle=`rgba(200,206,230,${.22*oa})`;ctx.beginPath();ctx.ellipse(cx,cy,Rx*rr,Ry*rr,0,0,6.283);ctx.stroke();});
   const cA=F(1300,600),cg=ctx.createRadialGradient(cx,cy,0,cx,cy,60);cg.addColorStop(0,`rgba(240,244,255,${.55*cA})`);cg.addColorStop(1,'rgba(120,140,255,0)');ctx.fillStyle=cg;ctx.fillRect(cx-60,cy-60,120,120);
   const D=DATA[1]||{},list=D.stars||[],sA=F(1500,700);const nodes=[];
   list.forEach(s=>{const ring=rings[s.ring]||.92,an=-Math.PI/2+s.angle+(red?0:tt*.01),x=cx+Math.cos(an)*Rx*ring,y=cy+Math.sin(an)*Ry*ring,rad=s.sel?5:3;
    const a=sA*(s.live?1:.45);ctx.fillStyle=s.dir==='SELL'?`rgba(224,179,179,${a})`:s.dir==='BUY'?`rgba(207,232,218,${a})`:`rgba(220,224,235,${a*.7})`;ctx.beginPath();ctx.arc(x,y,rad,0,6.283);ctx.fill();
    if(s.sel){ctx.strokeStyle=`rgba(255,255,255,${.8*sA})`;ctx.beginPath();ctx.arc(x,y,rad+5+Math.sin(tt*3),0,6.283);ctx.stroke();}nodes.push({x,y,r:rad+6,id:s.id});});
   D.nodes=nodes;ctx.globalAlpha=cA;ctx.fillStyle='#e6e9f4';ctx.font='11px "Helvetica Neue",Helvetica,Arial,sans-serif';ctx.textAlign='center';ctx.fillText(D.center||'',cx,cy+4);ctx.globalAlpha=1;ctx.restore();}}
 else if(i===2){ /* MODELS: siatka → eliptyczny tunel → obserwatorium */
  if(!red){const k=seg(cms,350,1400),fa=(1-smooth(seg(cms,1300,500)))*smooth(seg(cms,300,200));if(fa>0&&k>0){const z=Math.pow(k,1.6);ctx.strokeStyle=`rgba(200,214,255,${.35*fa})`;
   for(let n=0;n<14;n++){const rr=(L0.r*1.6)*Math.pow(1.38,n)*(1+z*6)%(diag*1.1);ctx.globalAlpha=fa*(1-rr/(diag*1.1));ctx.beginPath();ctx.ellipse(pc[0],pc[1],rr,rr*.62,0,0,6.283);ctx.stroke();}
   ctx.globalAlpha=fa;for(let n=0;n<24;n++){const a=n/24*6.283+tt*.05,r0=L0.r*1.2,r1=diag*z;ctx.beginPath();ctx.moveTo(pc[0]+Math.cos(a)*r0,pc[1]+Math.sin(a)*r0*.62);ctx.lineTo(pc[0]+Math.cos(a)*r1,pc[1]+Math.sin(a)*r1*.62);ctx.stroke();}ctx.globalAlpha=1;}}
  const R=rectOf('#mb-obs');if(R&&R.w>50){const nA=F(1150,700),cA=F(1300,600);ctx.save();ctx.beginPath();ctx.rect(R.l,R.t,R.w,R.h);ctx.clip();ctx.globalAlpha=nA;ctx.drawImage(nebula(Math.round(R.w),Math.round(R.h),['rgba(40,90,140,A)','rgba(70,60,150,A)','rgba(30,110,130,A)']),R.l,R.t);ctx.globalAlpha=1;
   const cx=R.l+R.w/2,cy=R.t+R.h*.5,Rx=R.w*.43,Ry=R.h*.40,D=DATA[2]||{};const cg=ctx.createRadialGradient(cx,cy,0,cx,cy,70);cg.addColorStop(0,`rgba(230,240,255,${.5*cA})`);cg.addColorStop(.3,`rgba(120,170,255,${.12*cA})`);cg.addColorStop(1,'rgba(80,120,220,0)');ctx.fillStyle=cg;ctx.fillRect(cx-70,cy-70,140,140);
   ctx.strokeStyle=`rgba(200,214,255,${.25*cA})`;for(let n=0;n<6;n++){ctx.beginPath();ctx.ellipse(cx,cy,24,24*.62,n/6*Math.PI+tt*.1,0,6.283);ctx.stroke();}
   if(D.jobProgress!=null){ctx.strokeStyle=`rgba(181,168,255,${.25*cA})`;ctx.lineWidth=2;ctx.beginPath();ctx.ellipse(cx,cy,44,44*.62,0,0,6.283);ctx.stroke();ctx.strokeStyle=`rgba(240,244,255,${.9*cA})`;ctx.beginPath();ctx.ellipse(cx,cy,44,44*.62,0,-Math.PI/2,-Math.PI/2+D.jobProgress*6.283);ctx.stroke();ctx.lineWidth=1;}
   ctx.globalAlpha=cA;ctx.textAlign='center';ctx.fillStyle='#e6e9f4';ctx.font='10px "Helvetica Neue",Helvetica,Arial,sans-serif';ctx.fillText('CENTRUM TRENINGU',cx,cy+50);ctx.globalAlpha=1;
   const groups=D.groups||[],GN=groups.length,nodes=[];groups.forEach((g,k)=>{const a=k/Math.max(1,GN)*6.283-Math.PI/2+(red?0:tt*.008),gx=cx+Math.cos(a)*Rx*.78,gy=cy+Math.sin(a)*Ry*.78,gA=F(1450+k*60,500);
    ctx.globalAlpha=gA*.8;ctx.fillStyle='#9aa0aa';ctx.font='8px "Helvetica Neue",Helvetica,Arial,sans-serif';ctx.fillText(g.name,gx,gy-24);
    g.models.forEach((m,j)=>{const b=j/Math.max(1,g.models.length)*6.283+k,rr=6+((j*37)%17),x=gx+Math.cos(b)*rr*1.4,y=gy+Math.sin(b)*rr,bright=m.bright,sz=m.sel||m.hl?3.6:2.2;
     ctx.globalAlpha=gA*(.25+.75*bright);ctx.fillStyle=m.training?'#b5a8ff':'#eef1f8';ctx.beginPath();ctx.arc(x,y,sz,0,6.283);ctx.fill();
     if(m.sel||m.hl){ctx.strokeStyle='rgba(255,255,255,.8)';ctx.beginPath();ctx.arc(x,y,sz+5+Math.sin(tt*3),0,6.283);ctx.stroke();}
     if(m.training){ctx.strokeStyle=`rgba(181,168,255,${.35*gA})`;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(cx,cy);ctx.stroke();}nodes.push({x,y,r:sz+6,id:m.id});});});
   D.nodes=nodes;ctx.globalAlpha=1;ctx.restore();}}
 else{ /* ROI: przelot przez wir → galaktyka spiralna z okiem */
  if(!red){const k=seg(cms,300,1300);if(k>0&&k<1){ctx.strokeStyle=`rgba(210,220,255,${(1-k)*.35})`;for(let n=0;n<60;n++){const a=n/60*6.283+k*4,r0=L0.r*(1+k*3),r1=r0+diag*k*.6;ctx.beginPath();ctx.moveTo(pc[0]+Math.cos(a)*r0,pc[1]+Math.sin(a)*r0);ctx.lineTo(pc[0]+Math.cos(a+.4*k)*r1,pc[1]+Math.sin(a+.4*k)*r1);ctx.stroke();}}}
  const R=rectOf('#ro-hero');if(R&&R.w>50){const gA=F(1300,900),cx=R.l+R.w/2,cy=R.t+R.h/2,Rm=Math.min(R.w,R.h)*.47,D=DATA[3]||{};ctx.save();
   if(!D.dust){subSeed=9;D.dust=[];for(let k=0;k<2600;k++){const arm=k%2,t=Math.pow(srnd(),.65),th=t*7.2+arm*Math.PI+(srnd()-.5)*.55;D.dust.push([t,th,srnd()]);}}
   for(const d of D.dust){const t=d[0],th=d[1]+(red?0:tt*(.05+.25*(1-t))),r=t*Rm,x=cx+Math.cos(th)*r,y=cy+Math.sin(th)*r*.55;ctx.fillStyle=`rgba(225,230,250,${gA*(.08+.5*d[2]*(1-t))})`;ctx.fillRect(x,y,1.2,1.2);}
   const eg=ctx.createRadialGradient(cx,cy,0,cx,cy,Rm*.28);eg.addColorStop(0,'rgba(0,0,0,.95)');eg.addColorStop(.7,'rgba(0,0,0,.85)');eg.addColorStop(.92,`rgba(220,226,255,${.35*gA})`);eg.addColorStop(1,'rgba(220,226,255,0)');ctx.fillStyle=eg;ctx.beginPath();ctx.arc(cx,cy,Rm*.28,0,6.283);ctx.fill();
   const moons=D.moons||[],nodes=[];moons.forEach((m,k)=>{const a=k/Math.max(1,moons.length)*6.283+(red?0:tt*.06),x=cx+Math.cos(a)*Rm*.72,y=cy+Math.sin(a)*Rm*.72*.55,sz=4+Math.min(14,Math.sqrt(m.trades||0)*1.6);
    ctx.fillStyle=m.net>0?`rgba(207,232,218,${gA})`:m.net<0?`rgba(224,179,179,${gA})`:`rgba(200,204,214,${gA*.6})`;ctx.beginPath();ctx.arc(x,y,sz,0,6.283);ctx.fill();ctx.globalAlpha=gA;ctx.fillStyle='#9aa0aa';ctx.font='9px "Helvetica Neue",Helvetica,Arial,sans-serif';ctx.textAlign='center';ctx.fillText(m.name,x,y+sz+12);ctx.globalAlpha=1;nodes.push({x,y,r:sz+6,id:m.id});});
   D.nodes=nodes;ctx.restore();}}
}
function rectOf(sel){const e=$(sel);if(!e)return null;const r=e.getBoundingClientRect();return {l:r.left,t:r.top,w:r.width,h:r.height};}
function subOpen(i){if(!SCREENS[i])return;if(S.phase!=='forex'&&S.phase!=='dive'){S.pendingSub=i;return;}if(SUB.state==='out'){S.pendingSub=i;return;}if(SUB.state!=='none'&&SUB.pi===i)return;
 if(SUB.state!=='none'){S.pendingSub=i;subClose();return;}SUB.pi=i;SUB.state='in';root.dataset.sub='in';$(SCREENS[i].el).inert=true;SCREENS[i].open&&SCREENS[i].open();opts.onSubState&&opts.onSubState('in',i);wake();}
function subClose(){if(SUB.state==='in'||SUB.state==='on'){SUB.state='out';root.dataset.sub='out';$(SCREENS[SUB.pi].el).inert=true;SCREENS[SUB.pi].close&&SCREENS[SUB.pi].close();opts.onSubState&&opts.onSubState('out',SUB.pi);wake();}}
function quality(dt){if(S.q==='low')return;if(S.frameAvg>28){S.slow=(S.slow||0)+dt;if(S.slow>3){S.q='low';const w=innerWidth,h=innerHeight;S.view={w,h,dpr:1};canvas.width=w;canvas.height=h;resize();}}else S.slow=0;}
const btn=$('#forex');let suppress=false;
listen(btn,'pointerdown',e=>{if(S.phase!=='menu'||(e.pointerType==='mouse'&&e.button!==0))return;suppress=false;S.drag={id:e.pointerId,sx:e.clientX,sy:e.clientY,x:e.clientX,y:e.clientY,t:performance.now(),moved:false};S.vel=[0,0];btn.setPointerCapture(e.pointerId);});
listen(btn,'pointermove',e=>{const d=S.drag;if(!d||d.id!==e.pointerId)return;const dx=e.clientX-d.x,dy=e.clientY-d.y,dt=Math.max((performance.now()-d.t)/1000,.008);
 if(Math.hypot(e.clientX-d.sx,e.clientY-d.sy)>6)d.moved=true;if(d.moved){S.rot[0]+=dy*.006;S.rot[1]+=dx*.006;S.vel=[clamp(dy*.006/dt,-2,2),clamp(dx*.006/dt,-3,3)];}d.x=e.clientX;d.y=e.clientY;d.t=performance.now();});
const endDrag=e=>{const d=S.drag;if(!d||d.id!==e.pointerId)return;suppress=d.moved||e.type==='pointercancel';S.drag=null;};
listen(btn,'pointerup',endDrag);listen(btn,'pointercancel',endDrag);
listen(btn,'click',()=>{if(suppress){suppress=false;return;}startDive();});

planets.forEach((q,i)=>{let sup=false;const b=q.el;
 listen(b,'pointerenter',()=>q.hot=true);listen(b,'pointerleave',()=>q.hot=false);listen(b,'focus',()=>q.focus=true);listen(b,'blur',()=>q.focus=false);
 listen(b,'pointerdown',e=>{if(S.phase!=='forex'||(e.pointerType==='mouse'&&e.button!==0))return;sup=false;pdrag={i,id:e.pointerId,sx:e.clientX,sy:e.clientY,x:e.clientX,y:e.clientY,t:performance.now(),moved:false};q.vel=[0,0];b.setPointerCapture(e.pointerId);});
 listen(b,'pointermove',e=>{const d=pdrag;if(!d||d.i!==i||d.id!==e.pointerId)return;const dx=e.clientX-d.x,dy=e.clientY-d.y,dt=Math.max((performance.now()-d.t)/1000,.008);if(Math.hypot(e.clientX-d.sx,e.clientY-d.sy)>6)d.moved=true;
  if(d.moved){q.rot[0]+=dy*.008;q.rot[1]+=dx*.008;q.vel=[clamp(dy*.008/dt,-2,2),clamp(dx*.008/dt,-3,3)];}d.x=e.clientX;d.y=e.clientY;d.t=performance.now();});
 const end=e=>{const d=pdrag;if(!d||d.i!==i||d.id!==e.pointerId)return;sup=d.moved||e.type==='pointercancel';pdrag=null;};listen(b,'pointerup',end);listen(b,'pointercancel',end);
 listen(b,'click',()=>{if(sup){sup=false;return;}choosePlanet(i);});
 listen(b,'keydown',e=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();const d=(e.key==='ArrowLeft'||e.key==='ArrowUp')?-1:1;planets[(i+d+4)%4].el.focus();}});});
listen($('#fx-return'),'click',()=>{if(SUB.state!=='none')opts.onBackFromSub&&opts.onBackFromSub();else surface();});
listen(window,'keydown',e=>{if(e.key==='Escape'){if(opts.escBlocked&&opts.escBlocked())return;if(SUB.state==='in'||SUB.state==='on'){opts.onBackFromSub&&opts.onBackFromSub();return;}if(SUB.state==='out')return;if(S.phase==='dive'||S.phase==='forex')surface();}});
listen(window,'pointermove',e=>{S.pointerT=[e.clientX/S.view.w*2-1,e.clientY/S.view.h*2-1];});
listen(window,'resize',resize);
listen(document,'visibilitychange',()=>{S.hidden=document.hidden;if(S.hidden){cancelAnimationFrame(S.raf);S.raf=0;}else wake();});
listen(canvas,'webglcontextlost',e=>{e.preventDefault();S.lost=true;cancelAnimationFrame(S.raf);S.raf=0;opts.onContextLost&&opts.onContextLost();});
/* ---------- API dla Reacta ---------- */
function dispose(){S.disposed=true;cancelAnimationFrame(S.raf);ctl.abort();try{for(const k in programs)gl.deleteProgram(programs[k].p);for(const k in bufs){const b=bufs[k];if(b&&typeof b==='object')gl.deleteBuffer(b);}planets.forEach(q=>q.buffer&&gl.deleteBuffer(q.buffer));if(fboTex)gl.deleteTexture(fboTex);if(fbo)gl.deleteFramebuffer(fbo);gl.getExtension('WEBGL_lose_context')?.loseContext();}catch(e){}}
const api={dispose,
 setPanel(i,status,err){const p=panels[i];if(!p)return;if(p.status!==status||p.err!==(err||'')){setStatus(p,status,err);if(S.phase!=='forex'&&S.phase!=='dive')updatePanelText(p);}},
 result(i){const p=panels[i];if(p)triggerResult(p);},
 stale(i,v){const p=panels[i];if(p&&p.stale!==!!v){p.stale=!!v;updatePanelText(p);}},
 openSub:subOpen,closeSub:subClose,
 /* haki testu 1:1 (jak PMW_PREVIEW._seek / _charts wzorca) – używane wyłącznie przez tryb testowy */
 testSeek(ph,prog){setPhase(ph);S.prog=prog;wake();},
 testSub(i,p){SUB.pi=i;SUB.state=p>=1?'on':'in';SUB.p=p;root.dataset.sub=SUB.state;$(SCREENS[i].el).inert=SUB.state!=='on';SCREENS[i].open&&SCREENS[i].open();wake();},surface(){if(SUB.state!=='none'){S.pendingSurface=true;subClose();return;}surface();},
 setScreenData(i,d){DATA[i]=Object.assign(DATA[i]||{},d);},nodeAt(i,x,y){const n=(DATA[i]&&DATA[i].nodes)||[];return (n.find(n=>Math.hypot(n.x-x,n.y-y)<n.r)||{}).id;},
 setReduced(v){S.reduced=!!v;wake();},state:()=>({phase:S.phase,prog:S.prog,sub:SUB.state,subIndex:SUB.pi,frameAvg:S.frameAvg,dpr:S.view.dpr,quality:S.q||'full',panels:panels.map(p=>({name:p.name,status:p.status,lastAt:p.lastAt}))})};
try{setup();resize();
 if(opts.startPose){S.startPose=opts.startPose;resize();}
 if(opts.fromMenu&&!S.reduced){setPhase('menu');S.bgStarted=false;startDive();}
 else{S.bgStarted=true;S.bgT=8;setPhase('dive');S.prog=opts.fromMenu?0:(2250/CFG.diveMs);connectModels();wake();}
}catch(e){console.error('PMW forex renderer:',e);opts.onNoWebGL&&opts.onNoWebGL();}
return api;}
