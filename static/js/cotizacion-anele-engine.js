(function(root){
 'use strict';
 const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toUpperCase().replace(/(\d),(\d)/g,'$1.$2').replace(/\s+/g,' ').trim();
 const num=s=>Number(String(s).replace(',','.'));
 let knownLabs=['VALMAX','SAVANT','KLONAL','VANNIER','BIOTENK','ROSPAW','TEVA','DUNCAN','FABRA','ECZANE','MICROSULES','DENVER'];
 let profileCache=new WeakMap(),candidateCache=new WeakMap();
 const packaging=/\b(ESTUCHADO|ESTUCHADA|HOSPITALARIO|HOSPITALARIA|HOSP|CORTO VENCIMIENTO)\b/g;
 function registerLabs(items){knownLabs=[...new Set([...knownLabs,...items.flatMap(p=>norm(p.lab).split(/[\/;,]/).map(s=>s.replace(packaging,'').trim()).filter(s=>s.length>2))])].sort((a,b)=>b.length-a.length);profileCache=new WeakMap();candidateCache=new WeakMap();}
 function profile(item){
  const signature=[item.name,item.description,item.lab].join('|'),cached=profileCache.get(item);if(cached?.signature===signature)return cached.value;
  let text=norm(item.name+' '+(item.description||''));
  const pack=text.match(/\bX\s*(\d+(?:\.\d+)?)\s*(COMP\w*|COMPR\w*|CAP\w*|PAST\w*|CB|GRAGEAS|UNIDADES|ML|G(?:RS)?\b)?/);
  const unit=pack?.[2]||'';
  let form=/CREMA|POMADA|GEL\b/.test(text)?'crema':/GOTAS/.test(text)?'gotas':/JARABE|JBE|SUSPENSION/.test(text)?'líquido':/AER\b|AEROSOL/.test(text)?'aerosol':/AMPOLLA|INYECT/.test(text)?'inyectable':/COMP|PASTILL|GRAGEA/.test(text)?'comprimidos':/CAPS|\bCB\b/.test(text)?'cápsulas':null;
  let dose=[],explicit=false;
  const before=(pack?text.slice(0,pack.index):text).replace(/\b\d+(?:\.\d+)?\s*ML\b/g,'');
  for(const m of before.matchAll(/(\d+(?:\.\d+)?)\s*(MG\b|MCG\b|GRAMOS\b|GR\b|G\b|%)/g)){
   explicit=true;dose.push({v:num(m[1])*(m[2]==='G'||m[2]==='GR'||m[2]==='GRAMOS'?1000:m[2]==='MCG'?0.001:1),u:m[2]==='%'?'%':'mg'});
  }
  if(!dose.length){const numbers=[...before.matchAll(/\b\d+(?:\.\d+)?\b/g)];dose=numbers.map(m=>({v:num(m[0]),u:'mg'}));}
  const lab=norm(item.lab).replace(packaging,'').trim();let labs=lab.length>1?lab.split(/[\/;,]/).map(norm).filter(Boolean):[];
  let name=before,inferredLab=false;for(const l of knownLabs){const rx=new RegExp('\\b'+l.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'\\b','g');if(rx.test(name)){if(!labs.length){labs=[l];inferredLab=true;}name=name.replace(rx,' ');}}
  const variants=(name.match(/\b(SODICO|POTASICO|RETARD|XR|LP|CR|EFERVESC\w*)\b/g)||[]);
  const strength=name.replace(/\d+(?:\.\d+)?\s*(MG|MCG|GRAMOS|GR|G|%)?\b/g,' ').replace(/\b(COMP\w*|CAP\w*|CB|CAJA|BLISTER|POR|X|DE|AC|MG|ML|JARABE|JBE|SUSPENSION|GOTAS|CREMA|POMADA|GEL|AER|AEROSOL|AMPOLLA|SODICO|POTASICO|RETARD|XR|LP|CR|EFERVESC\w*)\b/g,' ').replace(packaging,' ').replace(/[^A-Z+ ]/g,' ').replace(/\bIBU\b/g,'IBUPROFENO').replace(/\bAMOXI\b/g,'AMOXICILINA').replace(/\s+/g,' ').trim();
  const value={text,base:strength,words:strength.split(/\s+/).filter(Boolean),dose,explicit,pack:pack?num(pack[1]):null,packUnit:/ML/.test(unit)?'ml':/^G(?:RS)?$/.test(unit)?'g':unit?'unidades':pack?'unidades':null,form,labs,lab,inferredLab,variants};profileCache.set(item,{signature,value});return value;
 }
 function similarity(a,b){
  if(a===b)return 1;if(!a||!b)return 0;
  const d=Array.from({length:a.length+1},(_,i)=>[i]);for(let j=1;j<=b.length;j++)d[0][j]=j;
  for(let i=1;i<=a.length;i++)for(let j=1;j<=b.length;j++)d[i][j]=Math.min(d[i-1][j]+1,d[i][j-1]+1,d[i-1][j-1]+(a[i-1]===b[j-1]?0:1));
  return 1-d[a.length][b.length]/Math.max(a.length,b.length);
 }
 function compare(q,p){
  const a=profile(q),b=profile(p),conflicts=[],missing=[];
  const first=similarity(a.words[0],b.words[0]);
  const coverage=a.words.length? a.words.reduce((s,w)=>s+Math.max(0,...b.words.map(v=>similarity(w,v))),0)/a.words.length:0;
  const reverse=b.words.length? b.words.reduce((s,w)=>s+Math.max(0,...a.words.map(v=>similarity(w,v))),0)/b.words.length:0;
  if(first<.86||coverage<.84||reverse<.70)conflicts.push('Nombre o composición diferente');
  if(a.dose.length&&b.dose.length){if(JSON.stringify(a.dose)!==JSON.stringify(b.dose))conflicts.push('Dosis diferente');else if(!a.explicit||!b.explicit)missing.push('Unidad de dosis inferida: confirmar mg');}else missing.push('Dosis incompleta');
  if(a.pack!==null&&b.pack!==null){if(a.pack!==b.pack||a.packUnit!==b.packUnit)conflicts.push('Cantidad o tamaño de envase diferente');}else missing.push('Cantidad por envase sin confirmar');
  if(a.form&&b.form){if(a.form!==b.form)conflicts.push('Forma diferente');}else missing.push('Forma sin confirmar');
  if(a.variants.length&&b.variants.length){if(JSON.stringify(a.variants)!==JSON.stringify(b.variants))conflicts.push('Variante o liberación diferente');}else if(a.variants.length||b.variants.length)missing.push('Variante o liberación sin confirmar');
  if(a.labs.length&&b.labs.length){if(!a.labs.some(x=>b.labs.includes(x)))conflicts.push('Laboratorio diferente');}else missing.push('Laboratorio sin confirmar');
  if(a.inferredLab||b.inferredLab)missing.push('Laboratorio extraído del nombre: confirmar');
  const score=Math.round((coverage*.65+reverse*.15+(a.dose.length&&b.dose.length?.1:0)+(a.pack!==null&&b.pack!==null?.05:0)+(a.labs.length&&b.labs.length?.05:0))*100);
  return {id:p.id,score,conflicts,missing,compatible:!conflicts.length,level:conflicts.length?'Incompatible':missing.length?'Revisar':'Coincidencia completa'};
 }
 function candidates(q,products){let cache=candidateCache.get(products);if(!cache){cache=new WeakMap();candidateCache.set(products,cache);}if(cache.has(q))return cache.get(q);const result=products.map(p=>compare(q,p)).filter(c=>!c.conflicts.includes('Nombre o composición diferente')).sort((a,b)=>Number(b.compatible)-Number(a.compatible)||b.score-a.score).slice(0,6);cache.set(q,result);return result;}
 function sale(cost,margin){const cents=Math.round(Number(cost)*(1+Number(margin)/100)*100);return Math.ceil(cents/50)*.5;}
 function margin(cost,price){return cost>0?Math.round((price/cost-1)*10000)/100:null;}
 function apply(products,quotes,entries,mode){
  const result=JSON.parse(JSON.stringify(products)),used=new Set(),changes=[];
  if(!['update','add'].includes(mode))throw Error('Modo inválido');
  if(!entries.length)throw Error('Seleccioná al menos un producto');
  for(const e of entries){
   const q=quotes.find(q=>q.id===e.quoteId);if(!q||!Number.isFinite(q.cost)||q.cost<=0)throw Error('Cotización sin costo válido');
   if(!Number.isFinite(e.price)||e.price<0)throw Error('Precio de venta inválido');
   if(!e.confirmed)throw Error('Confirmá la correspondencia de cada producto seleccionado');
   let p=result.find(p=>p.id===e.productId);
   if(e.productId){if(!p)throw Error('Producto de Sirona inexistente');if(used.has(p.id))throw Error('Dos filas apuntan al mismo producto');if(!compare(q,p).compatible)throw Error('La presentación elegida es incompatible');used.add(p.id);}
   else{if(mode!=='add')throw Error('Actualizar costos no permite crear productos');if(!e.name?.trim()||!e.lab?.trim())throw Error('Completá nombre y laboratorio para el alta');
    if(result.some(p=>p.id==='trial-'+q.id))throw Error('Esta fila de cotización ya fue agregada en la prueba');
    if(!compare(q,{name:e.name,lab:e.lab}).compatible)throw Error('El alta debe conservar el producto y presentación de la cotización');
    const parsed=profile({name:e.name,lab:e.lab});if(!parsed.dose.length||parsed.pack===null)throw Error('Completá dosis y cantidad o tamaño del envase antes del alta');
    if(result.some(p=>norm(p.name)===norm(e.name)&&norm(p.lab)===norm(e.lab)))throw Error('Ese producto ya existe en la copia de Sirona');
    p={id:'trial-'+q.id,name:e.name.trim(),lab:e.lab.trim(),code:'PRUEBA',cost:0,price:0,margin:30,stock:0,enabled:true,priceList:!!e.priceList};result.push(p);
   }
   const before={...p};p.cost=q.cost;p.price=e.price;p.margin=margin(q.cost,e.price);if(mode==='add')p.priceList=!!e.priceList;
   changes.push({quote:q.name,product:p.name,id:p.id,before,after:{...p},new:!products.some(x=>x.id===p.id)});
  }
  return {products:result,changes};
 }
 const api={norm,profile,compare,candidates,sale,margin,apply,registerLabs};if(typeof module!=='undefined')module.exports=api;else root.TrialEngine=api;
})(typeof window==='undefined'?{}:window);
