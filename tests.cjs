const assert=require('node:assert/strict');const P=require('./core.js');
const cfg={spot:630,nlv:500000,asOf:'2026-10-02',evaluateOn:'2026-10-02',evaluateSpot:630,epr:25,rate:4,yield:.5,ivScale:1};
const r=(kind,qty,expiry,strike,mark)=>({kind,qty,expiry,strike,mark,iv:''});
const original=[r('put',-15,'2026-10-16',430,.085),r('call',-15,'2026-10-16',715,.39),r('put',-30,'2026-11-20',390,.525),r('call',-30,'2026-11-20',740,4.625),r('put',-20,'2026-12-18',355,.89),r('call',-20,'2026-12-18',795,4.3),r('put',-20,'2027-01-15',350,1.255),r('call',-20,'2027-01-15',910,1.835)];
const near=(a,b,t=.02)=>assert.ok(Math.abs(a-b)<t,`${a} vs ${b}`);
const legs=P.compile(original,cfg),base=P.evaluate(legs,cfg);near(base.equity,500000,.001);near(base.up.move,26.9375);near(base.down.move,47.0012);near(base.upLoss,435131.51,10);
for(const leg of legs)near(leg.base,leg.mark,.00001);
near(base.equityAt(base.up.price),0,.01);near(base.legResults.reduce((a,l)=>a+l.upLoss,0),base.upLoss,.01);
const reduced=original.slice(2).map(x=>({...x,qty:x.expiry==='2026-11-20'?-20:x.qty}));const closed=P.evaluate(P.compile(reduced,cfg),cfg,100000);near(closed.equity,600000,.001);near(closed.up.move,39.4336);
const future=P.evaluate(P.compile(reduced,cfg),{...cfg,evaluateOn:'2026-10-09'},100000);near(future.equity,606108.60,10);near(future.up.move,39.8984);
const roll=[...reduced.filter(x=>x.expiry!=='2026-11-20'),r('put',-20,'2026-12-18',400,1.565),r('call',-20,'2026-12-18',805,3.52)];const rolled=P.evaluate(P.compile(roll,cfg),cfg,100000);near(rolled.equity,600000,.001);near(rolled.up.move,42.7480);
const noEntryEffect=P.evaluate(P.compile(original.map(x=>({...x,entry:999})),cfg),cfg);near(noEntryEffect.up.move,base.up.move,.000001);
const cost=P.evaluate(legs,cfg,0,100);near(cost.equity,499900,.001);assert.ok(cost.up.move<base.up.move);
const empty=P.evaluate([],cfg);assert.equal(empty.up,null);assert.equal(empty.down,null);near(empty.equity,500000);
const stockcfg={...cfg,spot:100,evaluateSpot:100,nlv:5000};const stock=P.evaluate(P.compile([{kind:'stock',qty:100}],stockcfg),stockcfg);near(stock.down.move,50,.001);assert.equal(stock.up,null);
const hedge=P.evaluate(P.compile([r('call',-1,'2026-11-20',740,4.625),r('call',1,'2026-11-20',740,4.625)],cfg),cfg);assert.equal(hedge.up,null);near(hedge.upLoss,0,.001);
assert.throws(()=>P.compile([r('call',-1,'2026-09-01',740,4)],cfg),/Expiration/);assert.throws(()=>P.compile([r('call',-1,'2026-11-20',740,-1)],cfg),/midpoint/);
const expired=P.evaluate(legs,{...cfg,evaluateOn:'2026-10-17'});assert.equal(expired.expired,true);
const shock=P.evaluate(legs,{...cfg,ivScale:1.25});assert.ok(shock.equity<base.equity);assert.ok(shock.up.move<base.up.move);
near(P.price(100,100,1,.2,'call',.05,0)-P.price(100,100,1,.2,'put',.05,0),100-100*Math.exp(-.05),.000001);
console.log('PASS: calibration, PNR roots, original/reduced/rolled portfolios, future NLV, entry-premium independence, fees, stocks, hedges, expiration, IV sensitivity, put-call parity.');
// Broker screenshot cross-check: observations must not be treated as model targets.
const screenshotCfg={...cfg,spot:630.75,evaluateSpot:630.75,nlv:501978.34};
const sc= P.evaluate(P.compile(original,screenshotCfg),screenshotCfg);
near(sc.up.move,26.881722,.0001);near(sc.up.price,800.30646,.001);
near(sc.equityAt(sc.up.price),0,.01);near(sc.upLoss,438654.48,1);
near(-sc.base,32722.50,.01);near(32765.71+sc.base,43.21,.01);
assert.ok(sc.upLoss>203026.77); // EPR loss is NOT the broker's requirement.
near(P.evaluate(P.compile(original,{...screenshotCfg,epr:15}),{...screenshotCfg,epr:15}).up.move,sc.up.move,.00001); // EPR does not determine PNR.
assert.equal(original.reduce((n,l)=>n+Math.abs(l.qty),0),170);
const screenshotCash=P.evaluate(P.compile(original,screenshotCfg),screenshotCfg,100000);
near(screenshotCash.equity,601978.34,.01);assert.ok(screenshotCash.up.move>sc.up.move);
console.log('PASS: SMH screenshot NLV/spot, 170 contracts, liability reference gap, PNR root, EPR independence, cash and separation from observed margin.');
