const assert=require('node:assert/strict'),O=require('./ocr.js');
const word=(text,x,y,w=55)=>({text,confidence:96,bbox:{x0:x,y0:y,x1:x+w,y1:y+30}});
const words=[word('SMH',25,20),word('629.96',340,20,100),word('630.59',530,20,100)];
const fixtures=[['Oct',16,'14d',-15,430,'P',.01,.16],['Oct',16,'14d',-15,715,'C',.33,.45],['Nov',20,'49d',-30,390,'P',.26,.79],['Nov',20,'49d',-30,740,'C',4.3,4.95],['Dec',18,'77d',-20,355,'P',.16,1.62],['Dec',18,'77d',-20,795,'C',4,4.6],['Jan',15,'105d',-20,350,'P',.96,1.55],['Jan',15,'105d',-20,910,'C',1.19,2.48]];
for(let i=0;i<fixtures.length;i++){const[m,d,dte,q,k,c,b,a]=fixtures[i],y=145+i*120;words.push(word(m,125,y),word(String(d),190,y),word(dte,260,y),word(String(q),40,y+30),word(String(k),145,y+60),word(c,280,y+60,30),word(b.toFixed(2),390,y+30),word(a.toFixed(2),570,y+30));}
const p=O.parseWords(words,742,1119,'2026-10-02');assert.equal(p.rows.length,8);assert.equal(p.symbol,'SMH');assert.ok(Math.abs(p.spot-630.275)<1e-8);assert.deepEqual(p.rows.map(r=>r.strike),[430,715,390,740,355,795,350,910]);assert.deepEqual(p.rows.map(r=>r.mark),[.085,.39,.525,4.625,.89,4.3,1.255,1.835]);assert.equal(p.rows[6].expiry,'2027-01-15');assert.equal(p.rows.every(r=>!r.confirmed),true);
const lostSign=words.map(w=>w.text==='-15'?{...w,text:'15'}:w);assert.equal(O.parseWords(lostSign,742,1119,'2026-10-02').rows[0].qty,'');
const t=O.parseText('-15 Oct 16 2026 715 C 0.33 0.45\n-20 Jan 15 2027 350 P 0.96 1.55','2026-10-02');assert.equal(t.rows.length,2);assert.equal(t.rows[0].qty,-15);assert.equal(t.rows[0].mark,.39);assert.equal(t.rows[1].expiry,'2027-01-15');
const missing=O.parseText('Oct 16 2026 715 C 0.33 0.45','2026-10-02');assert.equal(missing.rows[0].qty,'');
assert.equal(O.expiry(2,30,2027,'2026-10-02',NaN),'');assert.equal(O.expiry(1,15,null,'2026-10-02',105),'2027-01-15');
assert.equal(O.parseWords([],742,1119,'2026-10-02').rows.length,0);
console.log('PASS: screenshot word geometry, eight leg rows, strike/type/quote pairing, midpoint math, next-year expiration, missing quantities, lost signs, text fallback and invalid dates.');
// P/L-view regression: never turn P/L and Last or Trade Price into bid/ask.
const pnlWords=[word('Symbol',25,15),word('NX',220,15),word('Last',750,15,110),word('Trd',975,15,70),word('Prc',1050,15,70),word('SMH',25,180,110),word('630.75',750,180,130),word('36.93',975,180,110),word('Oct',125,300),word('16',190,300),word('14d',260,300),word('-15',40,330),word('430',145,365),word('P',280,365,30),word('83.0%',350,330,120),word('585.00',550,330,130),word('0.05',750,330,110),word('0.47',975,330,110),word('-44.44%',1150,330,130)];
const parsedPL=O.parseWords(pnlWords,1320,480,'2026-10-02');assert.equal(parsedPL.rows.length,1);assert.equal(parsedPL.symbol,'SMH');assert.equal(parsedPL.spot,630.75);assert.equal(parsedPL.rows[0].mark,'');assert.equal(parsedPL.rows[0].bid,'');assert.equal(parsedPL.rows[0].ask,'');assert.equal(parsedPL.rows[0].last,.05);assert.equal(parsedPL.rows[0].entry,.47);
assert.equal(O.parseWords(pnlWords,1320,480,'2026-10-02','bidask').rows[0].mark,'');
assert.equal(O.parseWords(pnlWords,1320,480,'2026-10-02','last').rows[0].mark,.05);
assert.equal(O.parseText('P/L Open Last Trd Prc\n-15 Oct 16 2026 430 P 585.00 0.05 0.47','2026-10-02').rows.length,0);
assert.equal(O.parseText('15 Oct 16 2026 430 P 0.01 0.16','2026-10-02').rows[0].qty,'');
assert.equal(O.parseWords([...words,word('Capital Requirements',20,0,350)],742,1119,'2026-10-02').blocked,true);
console.log('PASS: P/L column guard, Last proxy opt-in, entry extraction, symbol/spot columns, unsigned text and capital-screen exclusion.');
