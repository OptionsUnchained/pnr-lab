(function(root){'use strict';
const months={jan:1,feb:2,mar:3,apr:4,may:5,jun:6,jul:7,aug:8,sep:9,oct:10,nov:11,dec:12};
const norm=s=>String(s).replace(/[−–—]/g,'-').replace(/\$/g,'').trim();
const numeric=s=>/^[-+]?\d+(?:\.\d+)?$/.test(norm(s))?Number(norm(s)):null;
function expiry(month,day,year,asOf,dte){const base=new Date(asOf+'T00:00:00Z'),y=base.getUTCFullYear();if(!Number.isFinite(y))return'';if(!year){year=y;const current=Date.UTC(y,month-1,day);if(current<base.getTime())year++;if(Number.isFinite(dte)){const expected=new Date(base.getTime()+dte*86400000);if(expected.getUTCMonth()+1===month&&Math.abs(expected.getUTCDate()-day)<=1)year=expected.getUTCFullYear();}}if(year<100)year+=2000;const d=new Date(Date.UTC(year,month-1,day));return d.getUTCMonth()+1===month&&d.getUTCDate()===day?d.toISOString().slice(0,10):'';}
function groupLines(words){const lines=[];for(const w of [...words].sort((a,b)=>(a.bbox.y0+a.bbox.y1)-(b.bbox.y0+b.bbox.y1))){const cy=(w.bbox.y0+w.bbox.y1)/2,h=w.bbox.y1-w.bbox.y0;let line=lines.find(l=>Math.abs(l.cy-cy)<Math.max(h,l.h)*.46);if(!line){line={cy,h,words:[]};lines.push(line);}line.words.push(w);}for(const l of lines){l.words.sort((a,b)=>a.bbox.x0-b.bbox.x0);l.text=l.words.map(w=>w.text).join(' ');}return lines.sort((a,b)=>a.cy-b.cy);}
function parseWords(words,width,height,asOf,mode='auto'){
 const clean=words.filter(w=>w.text&&w.bbox).map(w=>({...w,text:norm(w.text)})),lines=groupLines(clean),anchors=[];
 const fullText=lines.map(l=>l.text).join('\n');
 if(/Capital\s+Requirements|Buy\s+to\s+Close|Review\s*&?\s*Send|\bSTO\b|\bBTC\b/i.test(fullText))return{rows:[],symbol:'',spot:'',nlv:'',text:fullText,blocked:true,message:'This is a capital-requirements screen or order ticket, not a holdings quote list. Enter its reference figures separately.'};
 const lastHeader=clean.find(w=>/^Last$/i.test(w.text)),tradeHeader=clean.find(w=>/^Trd$/i.test(w.text));
 const pnlLayout=!!lastHeader||/P\s*\/\s*L|Chg\s*%|Trd\s*Prc/i.test(fullText);
 for(const l of lines){for(let i=0;i<l.words.length;i++){const w=l.words[i],m=w.text.match(/^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*(\d{1,2})?$/i);if(!m)continue;const day=m[2]?+m[2]:numeric(l.words[i+1]?.text);if(!(day>=1&&day<=31))continue;const dte=l.text.match(/\b(\d{1,3})\s*d\b/i),year=l.text.match(/\b(20\d{2})\b/);anchors.push({...l,x:w.bbox.x0,date:expiry(months[m[1].toLowerCase()],day,year?+year[1]:null,asOf,dte?+dte[1]:NaN),inferredYear:!year});break;}}
 const rows=[];for(let i=0;i<anchors.length;i++){const a=anchors[i],end=i+1<anchors.length?anchors[i+1].cy-anchors[i+1].h*.65:Math.min(height,a.cy+(i?anchors[i].cy-anchors[i-1].cy:width*.22));const band=clean.filter(w=>((w.bbox.y0+w.bbox.y1)/2)>=a.cy-a.h*.65&&((w.bbox.y0+w.bbox.y1)/2)<end);
  const type=band.find(w=>/^(P|C|Put|Call)$/i.test(w.text)&&w.bbox.x0>=a.x);
  if(!type)continue;
  const kind=/^(P|Put)$/i.test(type.text)?'put':'call',typeY=(type.bbox.y0+type.bbox.y1)/2;
  const strikes=band.filter(w=>w.bbox.x0>=a.x*.85&&w.bbox.x1<=type.bbox.x0+5&&Math.abs((w.bbox.y0+w.bbox.y1)/2-typeY)<a.h*.8&&numeric(w.text)>0);
  const strike=strikes.length?numeric(strikes[strikes.length-1].text):'';
  const quantities=band.filter(w=>w.bbox.x1<a.x&&Number.isInteger(numeric(w.text))&&numeric(w.text)!==null);
  const qtyWord=quantities.find(w=>/^[-+]\d+$/.test(w.text))||quantities[0];
  const qty=qtyWord&&/^[-+]\d+$/.test(qtyWord.text)?numeric(qtyWord.text):'';
  const right=band.filter(w=>w.bbox.x0>Math.max(type.bbox.x1,width*.42)).sort((a,b)=>a.bbox.x0-b.bbox.x0);
  const quotes=right.filter(w=>/^\d+\.\d+$/.test(w.text));
  const rowPnl=pnlLayout||right.some(w=>/%|,|^-\d/.test(w.text))||quotes.length>2;
  const quoteLayout=!rowPnl&&(mode==='bidask'||quotes.length===2);
  const bid=quoteLayout&&quotes[0]?numeric(quotes[0].text):'',ask=quoteLayout&&quotes[1]?numeric(quotes[1].text):'';
  const column=(head,lo,hi)=>{const center=head?(head.bbox.x0+head.bbox.x1)/2:null;const candidates=quotes.filter(w=>center!=null?Math.abs((w.bbox.x0+w.bbox.x1)/2-center)<width*.06:w.bbox.x0>=lo*width&&w.bbox.x1<=hi*width);return candidates.length===1?numeric(candidates[0].text):'';};
  const last=rowPnl?column(lastHeader,.55,.69):'',entry=rowPnl?column(tradeHeader,.70,.83):'';
  const mark=quoteLayout&&bid!==''&&ask!==''&&ask>=bid?(bid+ask)/2:mode==='last'&&last!==''?last:'';
  const warnings=[];if(a.inferredYear)warnings.push('year inferred');if(qty==='')warnings.push(qtyWord?'quantity sign uncertain — enter manually':'quantity missing');if(rowPnl)warnings.push(mode==='last'?'LAST PRICE PROXY — may be stale; not a midpoint':'P/L / Last / Trade Price view — supply a current midpoint');else if(!quoteLayout)warnings.push('quote columns uncertain — supply bid/ask');if(mark==='')warnings.push('current mark missing');if(bid!==''&&ask!==''&&ask<bid)warnings.push('ask below bid');if(!strike)warnings.push('strike missing');if(band.some(w=>w.confidence!=null&&w.confidence<65))warnings.push('low-confidence text');
  rows.push({kind,qty,expiry:a.date,strike,bid,ask,last,mark,priceSource:quoteLayout?'Bid/ask midpoint':mode==='last'?'LAST proxy — may be stale':'Manual mark required',iv:'',entry,warnings:[...new Set(warnings)],confirmed:false});
 }
 const top=lines.filter(l=>l.cy<(anchors[0]?.cy??height*.2));const topText=top.map(l=>l.text).join('\n');const sym=[...clean].sort((a,b)=>b.bbox.y0-a.bbox.y0).find(w=>w.bbox.x0<width*.25&&w.bbox.y0<(anchors[0]?.cy??height*.2)&&/^[A-Z]{1,6}$/.test(w.text)&&!['ETF','USD','NLV','PNR','EPR','BTC','STO'].includes(w.text));
 const prices=top.flatMap(l=>l.words).filter(w=>/^\d+\.\d{2}$/.test(w.text)).map(w=>+w.text);let spot='';if(!pnlLayout&&prices.length===2&&Math.abs(prices[1]-prices[0])/Math.max(prices[0],1)<.03)spot=(prices[0]+prices[1])/2;
 if(lastHeader&&sym){const sy=(sym.bbox.y0+sym.bbox.y1)/2,lx=(lastHeader.bbox.x0+lastHeader.bbox.x1)/2;const p=clean.find(w=>Math.abs((w.bbox.y0+w.bbox.y1)/2-sy)<sym.bbox.y1-sym.bbox.y0&&Math.abs((w.bbox.x0+w.bbox.x1)/2-lx)<width*.06&&/^\d+\.\d{2}$/.test(w.text));if(p)spot=+p.text;}
 const nlv=topText.match(/(?:Net\s*Liq(?:uidation)?|NLV)\D{0,15}([\d,]+(?:\.\d+)?)/i);
 return{rows,symbol:sym?.text||'',spot,nlv:nlv?+nlv[1].replace(/,/g,''):'',text:lines.map(l=>l.text).join('\n')};
}
function parseText(text,asOf){
 const rows=[],normText=norm(text),lines=normText.split(/\n/);let chunk=[];
 if(/P\s*\/\s*L|\bLast\b|Trd\s*Prc|Capital\s+Requirements|Buy\s+to\s+Close|\bSTO\b|\bBTC\b|\d\s*%/i.test(normText))return{rows:[],symbol:'',spot:'',nlv:'',text,blocked:true,message:'This text includes P/L, Last, account or order columns. Use image column extraction or paste only signed quantity, expiration, strike, type, bid and ask.'};
 function finish(){if(!chunk.length)return;const line=chunk.join(' '),m=line.match(/\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*(\d{1,2})(?:[,\s]+(20\d{2}))?/i),iso=line.match(/\b(20\d{2}-\d{2}-\d{2})\b/);const type=line.match(/\b(\d+(?:\.\d+)?)\s*(P|C|Put|Call)\b/i);if((m||iso)&&type){const prefix=line.slice(0,m?m.index:iso.index),qty=prefix.match(/([-+]\d+|\b\d+)\s*$/),tail=line.slice(type.index+type[0].length),quotes=(tail.match(/\d+\.\d+/g)||[]).map(Number);const bid=quotes[0]??'',ask=quotes[1]??'';rows.push({kind:/^p/i.test(type[2])?'put':'call',qty:qty&&/^[-+]/.test(qty[1])?+qty[1]:'',expiry:iso?iso[1]:expiry(months[m[1].toLowerCase()],+m[2],m[3]?+m[3]:null,asOf,NaN),strike:+type[1],bid,ask,mark:bid!==''&&ask!==''&&ask>=bid?(bid+ask)/2:'',iv:'',entry:'',priceSource:'Bid/ask midpoint (text)',warnings:['review text extraction',...(!qty?['quantity missing']:[]),...(quotes.length<2?['quote missing']:[])],confirmed:false});}chunk=[];}
 for(const line of lines){if(/\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s*\d|\b20\d{2}-\d{2}-\d{2}/i.test(line)){finish();chunk=[line];}else if(chunk.length)chunk.push(line);}finish();return{rows,symbol:'',spot:'',nlv:'',text};
}
const api={parseWords,parseText,groupLines,expiry};if(typeof module!=='undefined'&&module.exports)module.exports=api;root.PNROCR=api;
})(typeof globalThis!=='undefined'?globalThis:this);
