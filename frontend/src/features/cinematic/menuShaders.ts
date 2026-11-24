// Shadery GLSL menu głównego – przeniesione 1:1 ze wzorca update_1_42/referencje/REF_A_menu_glowne_v1_1.html (stałe tekstowe, bez zmian matematyki).
// Nie edytuj ręcznie: zmiana kształtu planet wymaga zmiany wzorca i ponownego przeniesienia.
// 1.46 (jedyne odstępstwo od tekstu wzorca, bez zmiany kształtu): pow() z możliwie ujemną podstawą jest niezdefiniowane w GLSL ES
// (ANGLE/D3D w WebView2 i Metal liczą exp2(y*log2(x)) = NaN → czarne kropki planety FOREX i pyłu). pow(sin(..),8.) → pow(abs(sin(..)),8.)
// i pow(x,2.) → x*x dają te same wartości co wzorzec tam, gdzie są zdefiniowane – tak samo liczy renderer CPU (Math.pow w menuEngine.ts).

export const vertexShared = `
 precision highp float;
 attribute vec3 aPos;attribute vec3 aInfo;
 uniform float uTime,uKind,uHover,uDpr,uOpacity,uRadius,uBurst,uMesh;
 uniform vec2 uResolution,uCenter,uMouse;
 uniform mat3 uRotation;
 varying vec3 vColor;varying float vAlpha;
 float gA,gSat,gAux;
 float h1(float x){return fract(sin(x*127.1)*43758.5453);}
 vec3 rotX(vec3 q,float a){float c=cos(a),s=sin(a);return vec3(q.x,q.y*c-q.z*s,q.y*s+q.z*c);}
 /* Planety menu – ten sam język co planety ekranu FOREX: kropkowana kula + pierścienie/księżyce.
    gAux=1: elementy w przestrzeni widoku (pierścień, księżyce, łańcuch) – nie obracają się przy przeciąganiu. */
 vec3 shape(vec3 n,vec3 inf){
   float t=uTime,seed=inf.x;float lat=asin(clamp(n.y,-1.,1.)),lon=atan(n.z,n.x);vec3 p=n;gA=1.;gSat=0.;gAux=0.;
   if(uKind<.5){ /* FOREX: planeta macierzysta z pierścieniem i czterema księżycami (CHARTS · SIGNALS · MODELS · ROI) */
     if(seed<.10){gAux=1.;float u=fract(inf.y*7.31);float rr=1.30+.45*u;float gap=1.-step(abs(rr-1.56),.022);
       float ang=inf.z*6.2832+t*.10/pow(rr,1.5);p=rotX(vec3(cos(ang)*rr,(inf.y-.5)*.012,sin(ang)*rr),.30);
       gA=(.5+.6*pow(.5+.5*sin(rr*46.+inf.y*3.),2.))*gap*1.25;gSat=.6;}
     else if(seed<.124){gAux=1.;float id=floor((seed-.10)/.006);float oa=id*1.5708+t*(.17+.035*id);float orr=1.92+.07*id;
       vec3 c=rotX(vec3(cos(oa)*orr,0.,sin(oa)*orr),.30+.05*id);p=c+n*(.085+.012*id);gA=.95;gSat=.15;}
     else{float l2=lon+t*.05;float b=sin(lat*18.+sin(l2*2.+lat*3.)*.7);float eq=exp(-lat*lat*28.);
       p=n*(1.+.006*b);gA=.16+.95*pow(b*b,1.6)+.7*eq*(.6+.4*sin(l2*6.-t*.4))+.3*pow(abs(sin(lat*37.+l2)),8.);}
   }else if(uKind<1.5){ /* CRYPTO: planeta z bloków – pasy siatki obracają się naprzemiennie, bloki zapalają się jak potwierdzenia; łańcuch bloków na orbicie */
     if(seed<.11){gAux=1.;float k=floor(inf.z*20.);float ang;vec3 c;
       if(fract(inf.y*5.)<.28){ang=(k+fract(inf.y*71.))/20.*6.2832+t*.10;c=vec3(cos(ang)*1.62,0.,sin(ang)*1.62);gA=.32;}
       else{ang=(k+.5)/20.*6.2832+t*.10;vec3 bx=(vec3(fract(inf.y*13.),fract(inf.y*29.),fract(inf.y*47.))-.5)*.12;c=vec3(cos(ang)*1.62,0.,sin(ang)*1.62)+bx;
         float lit=step(.75,h1(k+floor(t*.5)*7.));gA=.7+.9*lit;gSat=.5*(1.-lit);}
       p=rotX(c,.28);}
     else{float st=.2618;float bd=floor((lat+1.5708)/st);float dir=mod(bd,2.)<.5?1.:-1.;float l2=lon+t*.11*dir;
       float cu=l2/st,cv=(lat+1.5708)/st;float fu=fract(cu),fv=fract(cv);float e=min(min(fu,1.-fu)*cos(lat),min(fv,1.-fv));float ln=1.-smoothstep(0.,.07,e);
       float id=floor(mod(cu,24.))+bd*37.;float lit=step(.88,h1(id+floor(t*.6+h1(id)*5.)*13.));p=n*(1.+.028*lit*(1.-ln));
       gA=.10+.95*ln+.75*lit*(1.-ln);gSat=.45*lit;}
   }else{ /* TraderLifeGame (1.45): rdzeń w powłoce – świecący rdzeń i cienka powłoka z południków, po których biegną impulsy */
     if(seed<.40){p=n*.56;gA=.30+.75*pow(.5+.5*sin(lat*9.-t*.8+sin(lon*3.)*1.2),4.);gSat=.1;}
     else{float sec=6.2832/9.;float lm=lon+t*.05;float dm=abs(fract(lm/sec+.5)-.5)*sec*cos(lat);float seam=1.-smoothstep(0.,.03,dm);
       float sid=floor(lm/sec+.5);float pulse=pow(.5+.5*sin(lat*2.5-t*1.5+sid*1.9),14.);float eq=1.-smoothstep(0.,.02,abs(lat));
       p=n*(1.+.015*sin(t*.5));gA=.035+seam*(.45+1.1*pulse)+eq*.55;gSat=.55*seam*(1.-pulse);}
   }
   return p;
 }
 void main(){
   vec3 n=aPos;float seed=aInfo.x;vec3 p;
   if(uMesh>.5){p=uRotation*(n*(uKind>1.5?.555:.985));gAux=0.;gA=1.;gSat=0.;}
   else{p=shape(n,aInfo);if(gAux<.5)p=uRotation*p;}
   vec2 delta=p.xy-uMouse;float dist=length(delta);
   float ripple=exp(-dist*dist*2.8)*uHover;
   p.xy+=delta* .045*ripple;
   p.z+=.13*ripple*sin(dist*8.-uTime*1.7);
   p*=1.+uHover*.035;
   p+=normalize(p+vec3(.001))*(sin(aInfo.z*6.283+uTime)*.04+1.)*uBurst;
   float persp=3.7/(3.7-p.z*.55);
   vec2 px=uCenter+vec2(p.x,-p.y)*uRadius*persp;
   vec2 clip=px/uResolution*2.-1.;clip.y=-clip.y;
   gl_Position=vec4(clip,-p.z*.2,1.);
   vec3 nn=normalize(p);float rim=pow(1.-abs(nn.z),1.65);
   float light=clamp(dot(nn,normalize(vec3(-.65,.8,1.1)))*.5+.5,0.,1.);
   float alpha=gAux>.5?gA*(.50+.55*light):(.12+rim*.70+light*.34)*gA*(uKind>1.5?1.35:1.);
   vColor=mix(vec3(.77,.80,.87),vec3(.98,.985,1.),light*.8+rim*.2);vColor=mix(vColor,vec3(.70,.66,1.),gSat);
   vAlpha=alpha*uOpacity*(1.+uHover*.45);
   if(uMesh>.5){vColor=vec3(.0004,.0005,.0008)*(light+.1);vAlpha=uOpacity;}
   float sz=mix(.60,1.12,fract(aInfo.y*3.7));
   if(gAux>.5)sz*=1.1;
   gl_PointSize=clamp(sz*uDpr*persp*(1.+uHover*.08),.65,4.);
 }
`;

export const particleFrag = `precision mediump float;varying vec3 vColor;varying float vAlpha;void main(){vec2 d=gl_PointCoord*2.-1.;float r=dot(d,d);if(r>1.)discard;float a=exp(-r*2.8)*vAlpha;gl_FragColor=vec4(vColor*a,a);}`;

export const meshFrag = `precision mediump float;varying vec3 vColor;varying float vAlpha;void main(){gl_FragColor=vec4(vColor*vAlpha,vAlpha);}`;

export const starVert = `precision highp float;attribute vec3 aPos;attribute vec3 aInfo;uniform vec2 uResolution,uPointer;uniform float uTime,uDpr,uOpacity,uWarp,uDust;varying float vAlpha;varying vec3 vColor;void main(){vec2 p=aPos.xy;float z=aPos.z;float t=uTime;vec2 drift=vec2(t*.00035*(z+.15),t*.00010*(z+.1));p=mod(p+drift+1.,2.)-1.;p+=uPointer*(z*.012+.002);p*=1.+uWarp*(.1+z*.8);gl_Position=vec4(p,0.,1.);gl_PointSize=(aInfo.x*.9+.45)*uDpr*(.7+z*.45)*(1.+uWarp*.6);float tw=.65+.35*sin(t*(aInfo.y*.4+.2)+aInfo.z*25.);vAlpha=(.085+pow(aInfo.x,6.)*.65)*tw*uOpacity;vColor=mix(vec3(.53,.62,.83),vec3(.95,.95,.93),aInfo.y);if(uDust>.5){float cd=(p.y+p.x*.17+.38)*3.9;float center=exp(-cd*cd);vAlpha*=center*.11;gl_PointSize*=.65;}}`;

export const starFrag = `precision mediump float;varying float vAlpha;varying vec3 vColor;void main(){vec2 p=gl_PointCoord*2.-1.;float r=dot(p,p);if(r>1.)discard;float a=exp(-r*3.1)*vAlpha;gl_FragColor=vec4(vColor*a,a);}`;

export const streakVert = `precision highp float;attribute vec3 aPos;attribute vec3 aInfo;uniform float uWarp,uOpacity;varying float vAlpha;void main(){vec2 p=aPos.xy;float k=aInfo.x;vec2 end=p*(1.+uWarp*(.4+aPos.z)*k);gl_Position=vec4(end,0.,1.);vAlpha=uWarp*uOpacity*(1.-k*.65)*.22;}`;

export const streakFrag = `precision mediump float;varying float vAlpha;void main(){gl_FragColor=vec4(vec3(.65,.76,1.)*vAlpha,vAlpha);}`;
