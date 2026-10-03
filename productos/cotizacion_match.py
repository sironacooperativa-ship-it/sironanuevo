"""Presentación y correspondencias. No realiza altas ni escrituras."""
import re,unicodedata,hashlib

def normal(value):
    value=''.join(c for c in unicodedata.normalize('NFD',str(value or '')) if not unicodedata.combining(c)).upper()
    return ' '.join(re.sub(r'(\d),(\d)',r'\1.\2',value).split())

PACKAGING=r'\b(?:ESTUCHADO|ESTUCHADA|HOSPITALARIO|HOSPITALARIA|HOSP|CORTO VENCIMIENTO)\b'
DEFAULT_LABS=['VALMAX','SAVANT','KLONAL','VANNIER','BIOTENK','ROSPAW','TEVA','DUNCAN','FABRA','ECZANE','MICROSULES','DENVER']

def labs_for(products):
    values=[re.sub(PACKAGING,'',s).strip() for p in products for s in re.split(r'[/;,]',normal(p['lab']))]
    return sorted(set(DEFAULT_LABS+[s for s in values if len(s)>2]),key=len,reverse=True)

def profile(item,labs):
    text=normal(item['name']+' '+item.get('description',''))
    pack=re.search(r'\bX\s*(\d+(?:\.\d+)?)\s*(COMP\w*|COMPR\w*|CAP\w*|PAST\w*|CB|GRAGEAS|UNIDADES|ML|G(?:RS)?\b)?',text)
    unit=(pack[2] or '') if pack else ''
    form=next((v for rx,v in [(r'CREMA|POMADA|GEL\b','crema'),(r'GOTAS','gotas'),(r'JARABE|JBE|SUSPENSION','líquido'),(r'AER\b|AEROSOL','aerosol'),(r'AMPOLLA|INYECT','inyectable'),(r'COMP|PASTILL|GRAGEA','comprimidos'),(r'CAPS|\bCB\b','cápsulas')] if re.search(rx,text)),None)
    before=re.sub(r'\b\d+(?:\.\d+)?\s*ML\b','',text[:pack.start()] if pack else text)
    dose=[]
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*(MG\b|MCG\b|GRAMOS\b|GR\b|G\b|%)',before):
        dose.append((float(m[1])*(1000 if m[2] in ('G','GR','GRAMOS') else .001 if m[2]=='MCG' else 1),'%' if m[2]=='%' else 'mg'))
    if not dose:dose=[(float(n),'mg') for n in re.findall(r'\b\d+(?:\.\d+)?\b',before)]
    lab=re.sub(PACKAGING,'',normal(item.get('lab',''))).strip()
    laboratory=[s.strip() for s in re.split(r'[/;,]',lab)] if len(lab)>1 else []
    name=before
    for known in labs:
        if re.search(r'\b'+re.escape(known)+r'\b',name):
            if not laboratory:laboratory=[known]
            name=re.sub(r'\b'+re.escape(known)+r'\b',' ',name)
    variants=re.findall(r'\b(?:SODICO|POTASICO|RETARD|XR|LP|CR|EFERVESC\w*)\b',name)
    name=re.sub(r'\d+(?:\.\d+)?\s*(MG|MCG|GRAMOS|GR|G|%)?\b',' ',name)
    name=re.sub(r'\b(?:COMP\w*|CAP\w*|CB|CAJA|BLISTER|POR|X|DE|AC|MG|ML|JARABE|JBE|SUSPENSION|GOTAS|CREMA|POMADA|GEL|AER|AEROSOL|AMPOLLA|SODICO|POTASICO|RETARD|XR|LP|CR|EFERVESC\w*)\b',' ',name)
    name=re.sub(PACKAGING,' ',name);name=re.sub(r'[^A-Z+ ]',' ',name)
    name=re.sub(r'\bIBU\b','IBUPROFENO',name);name=re.sub(r'\bAMOXI\b','AMOXICILINA',name)
    return dict(words=name.split(),dose=dose,pack=float(pack[1]) if pack else None,unit='ml' if 'ML' in unit else 'g' if unit in ('G','GRS') else 'unidades' if pack else None,form=form,lab=laboratory,variants=variants)

def similarity(a,b):
    if a==b:return 1
    if not a or not b:return 0
    prev=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        row=[i]
        for j,y in enumerate(b,1):row.append(min(row[-1]+1,prev[j]+1,prev[j-1]+(x!=y)))
        prev=row
    return 1-prev[-1]/max(len(a),len(b))

def compatible(q,p,labs):
    a,b=profile(q,labs),profile(p,labs)
    aw,bw=a['words'],b['words']
    if not aw or not bw or similarity(aw[0],bw[0])<.86:return False
    coverage=sum(max(similarity(x,y) for y in bw) for x in aw)/len(aw)
    reverse=sum(max(similarity(x,y) for x in aw) for y in bw)/len(bw)
    if coverage<.84 or reverse<.7:return False
    if a['dose'] and b['dose'] and a['dose']!=b['dose']:return False
    if a['pack'] is not None and b['pack'] is not None and (a['pack']!=b['pack'] or a['unit']!=b['unit']):return False
    for field in ['form','variants']:
        if a[field] and b[field] and a[field]!=b[field]:return False
    if a['lab'] and b['lab'] and not set(a['lab'])&set(b['lab']):return False
    return True

def source_key(q):
    return hashlib.sha256(normal(q['name']+'|'+q.get('description','')+'|'+q.get('lab','')).encode()).hexdigest()
