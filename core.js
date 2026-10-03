(function(root){
'use strict';
const DAY=86400000;
function cdf(x){const a=Math.abs(x),t=1/(1+0.2316419*a);const z=Math.exp(-a*a/2)/Math.sqrt(2*Math.PI);const y=1-z*t*(0.319381530+t*(-0.356563782+t*(1.781477937+t*(-1.821255978+t*1.330274429))));return x<0?1-y:y;}
function price(s,k,t,v,kind,r=0,q=0){
 if(kind==='stock')return s;
 const intrinsic=Math.max(kind==='call'?s-k:k-s,0);
 if(t<=0)return intrinsic;
 if(s<=0)return kind==='put'?k*Math.exp(-r*t):0;
 if(v<=0)return Math.max(kind==='call'?s*Math.exp(-q*t)-k*Math.exp(-r*t):k*Math.exp(-r*t)-s*Math.exp(-q*t),0);
 const d1=(Math.log(s/k)+(r-q+v*v/2)*t)/(v*Math.sqrt(t)),d2=d1-v*Math.sqrt(t);
 return Math.max(0,kind==='call'?s*Math.exp(-q*t)*cdf(d1)-k*Math.exp(-r*t)*cdf(d2):k*Math.exp(-r*t)*cdf(-d2)-s*Math.exp(-q*t)*cdf(-d1));
}
function bisect(fn,lo,hi){let fl=fn(lo);for(let i=0;i<90;i++){const mid=(lo+hi)/2,fm=fn(mid);if(Math.abs(fm)<1e-7)return mid;if(fl*fm<=0)hi=mid;else{lo=mid;fl=fm;}}return(lo+hi)/2;}
function dateDays(a,b){return (Date.parse(b+'T00:00:00Z')-Date.parse(a+'T00:00:00Z'))/DAY;}
function calibrate(row,cfg){
 if(!['call','put','stock'].includes(row.kind))throw Error('Choose Call, Put or Shares.');
 if(row.qty===''||row.qty==null||!Number.isInteger(+row.qty))throw Error('Quantity must be a signed whole number.');
 if(+row.qty===0)return {...row,qty:0,iv:0,days:0,base:0};
 if(row.kind==='stock')return {...row,iv:0,days:0,base:cfg.spot,mult:1};
 const days=dateDays(cfg.asOf,row.expiry);if(!Number.isFinite(days)||days<=0)throw Error('Expiration must be after the snapshot date.');
 if(!(row.strike>0))throw Error('Strike must be positive.');
 const mark=+row.mark,t=days/365;
 if(!(mark>0))throw Error('Enter a positive current midpoint for active options.');
 let iv;
 if(row.iv!==''&&row.iv!=null){iv=+row.iv/100;if(!(iv>0&&iv<=5))throw Error('IV must be between 0 and 500%.');}
 else {const f=v=>price(cfg.spot,+row.strike,t,v,row.kind,cfg.rate/100,cfg.yield/100)-mark;
  if(f(0.00001)>0.00001||f(5)<0)throw Error('Midpoint cannot be fitted: check price, strike, date and carry assumptions.');
  iv=bisect(f,0.00001,5);
 }
 const base=price(cfg.spot,+row.strike,t,iv,row.kind,cfg.rate/100,cfg.yield/100);
 return {...row,qty:+row.qty,strike:+row.strike,mark,iv,days,base,mult:100,fitDifference:base-mark};
}
function compile(rows,cfg){return rows.map((row,i)=>{try{return calibrate(row,cfg);}catch(e){throw Error('Row '+(i+1)+': '+e.message);}});}
function modelValue(leg,s,elapsed,scale,cfg){
 if(!leg.qty)return 0;
 return leg.qty*(leg.mult||100)*price(s,leg.strike,Math.max(0,leg.days-elapsed)/365,leg.iv*scale,leg.kind,cfg.rate/100,cfg.yield/100);
}
function snapshotValue(legs){return legs.reduce((a,l)=>a+l.qty*(l.mult||100)*l.base,0);}
function value(legs,s,elapsed,scale,cfg){return legs.reduce((a,l)=>a+modelValue(l,s,elapsed,scale,cfg),0);}
function findRoot(fn,spot,up){
 if(fn(spot)<=0)return {price:spot,move:0};
 // Search outward and return the first sampled sign change, including hedged portfolios.
 let prev=spot,fp=fn(prev);const maxMove=10,minRatio=0.000001;
 for(let i=1;i<=2400;i++){
  const next=up?spot*(1+maxMove*i/2400):spot*(1-(1-minRatio)*i/2400),f=fn(next);
  if(f<=0&&fp>0){const p=bisect(fn,Math.min(prev,next),Math.max(prev,next));return{price:p,move:Math.abs(p/spot-1)*100};}
  prev=next;fp=f;
 }
 return null;
}
function evaluate(legs,cfg,deposit=0,cost=0){
 const elapsed=dateDays(cfg.asOf,cfg.evaluateOn);if(elapsed<0||!Number.isFinite(elapsed))throw Error('Evaluation date must be on or after the snapshot date.');
 if(!(cfg.spot>0&&cfg.evaluateSpot>0&&cfg.nlv>0))throw Error('Spot prices and snapshot NLV must be positive.');
 if(!(cfg.epr>0&&cfg.epr<100))throw Error('EPR must be between 0 and 100%.');
 if(!(cfg.ivScale>0&&cfg.ivScale<=5))throw Error('IV multiplier must be between 0 and 5.');
 const base=snapshotValue(legs), equityAt=s=>cfg.nlv+deposit-cost+value(legs,s,elapsed,cfg.ivScale,cfg)-base;
 const equity=equityAt(cfg.evaluateSpot),up=findRoot(equityAt,cfg.evaluateSpot,true),down=findRoot(equityAt,cfg.evaluateSpot,false);
 const stressUp=cfg.evaluateSpot*(1+cfg.epr/100),stressDown=cfg.evaluateSpot*(1-cfg.epr/100);
 const upLoss=equity-equityAt(stressUp),downLoss=equity-equityAt(stressDown);
 const legResults=legs.filter(l=>l.qty).map(l=>{const now=modelValue(l,cfg.evaluateSpot,elapsed,cfg.ivScale,cfg),u=modelValue(l,stressUp,elapsed,cfg.ivScale,cfg),d=modelValue(l,stressDown,elapsed,cfg.ivScale,cfg);return{...l,upLoss:now-u,downLoss:now-d,perContractUp:(now-u)/Math.abs(l.qty),upPrice:price(stressUp,l.strike,Math.max(0,l.days-elapsed)/365,l.iv*cfg.ivScale,l.kind,cfg.rate/100,cfg.yield/100),dayPL:now-l.qty*(l.mult||100)*l.base};});
 return{equity,equityAt,up,down,upLoss,downLoss,stressUp,stressDown,legResults,expired:legs.some(l=>l.qty&&l.kind!=='stock'&&l.days<=elapsed),fitMismatch:legs.some(l=>Math.abs(l.fitDifference||0)>.02),elapsed,base};
}
const api={cdf,price,bisect,dateDays,compile,evaluate,value,snapshotValue};
if(typeof module!=='undefined'&&module.exports)module.exports=api;root.PNR=api;
})(typeof globalThis!=='undefined'?globalThis:this);
