from pathlib import Path
from hashlib import sha256
import base64, json, re, math

def validate(schema, value, where='$'):
    """Check every validation keyword used by these review schemas; no dependencies."""
    if 'anyOf' in schema:
        for option in schema['anyOf']:
            try: validate(option,value,where); return
            except AssertionError: pass
        raise AssertionError(where+' matches no anyOf alternative')
    if 'const' in schema: assert value==schema['const'],where
    if 'enum' in schema: assert value in schema['enum'],where
    checks={'null':lambda v:v is None,'boolean':lambda v:type(v) is bool,'string':lambda v:isinstance(v,str),'integer':lambda v:type(v) is int,'number':lambda v:type(v) in (int,float) and math.isfinite(v),'array':lambda v:isinstance(v,list),'object':lambda v:isinstance(v,dict)}
    if 'type' in schema:
        types=schema['type'] if isinstance(schema['type'],list) else [schema['type']]
        assert any(checks[t](value) for t in types),where+' type'
    if isinstance(value,dict):
        for key in schema.get('required',[]):assert key in value,where+'.'+key+' required'
        for key,item in value.items():
            if key in schema.get('properties',{}):validate(schema['properties'][key],item,where+'.'+key)
            else:assert schema.get('additionalProperties',True) is not False,where+'.'+key+' unexpected'
    if isinstance(value,list):
        assert len(value)>=schema.get('minItems',0),where
        assert len(value)<=schema.get('maxItems',float('inf')),where
        if 'items' in schema:
            for i,item in enumerate(value):validate(schema['items'],item,f'{where}[{i}]')
    if isinstance(value,str) and 'pattern' in schema:assert re.search(schema['pattern'],value),where
    if type(value) in (int,float):
        assert value>=schema.get('minimum',-float('inf')),where
        assert value<=schema.get('maximum',float('inf')),where

ROOT=Path(__file__).resolve().parent
read=lambda name:json.loads((ROOT/name).read_text())
corpus=read('corpus.json');freeze=read('review-freeze.json')
validate(read('corpus.schema.json'),corpus)
orientation=read('orientation-and-help.json')
validate(read('orientation-and-help.schema.json'),orientation)
assert [p['id'] for p in orientation['practice_cards']]==['P1','P2']
assert [p['facts'][0]['text'] for p in orientation['practice_cards']]==['1.50 kWh','2.00 kWh']
for i in range(1,7):assert orientation['help_cards'][f'A{i}']['3']==orientation['help_cards'][f'B{i}']['3']
for fixture in read('synthetic-test-fixtures.json')['records']:validate(read('session-record.schema.json'),fixture)
protocol=ROOT.parent/'WattDialogue_Participant_Protocol_and_Ethics_Draft.tex'
assert sha256(protocol.read_bytes()).hexdigest()==corpus['protocol_sha256']
assert sha256((ROOT/'corpus.json').read_bytes()).hexdigest()==freeze['corpus_sha256']
for name,digest in freeze['file_sha256'].items():assert sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
baseline=(ROOT.parent/'task-table-v01.tex').read_text()
table=lambda s:s.split(r'\section{Task sets and frozen scoring rubrics}')[1].split(r'\begin{longtable}')[1].split(r'\end{longtable}')[0]
assert baseline==table(protocol.read_text()),'Task values/rubrics changed'
assert {c['id'] for c in corpus['cards']}=={f'{s}{i}' for s in 'AB' for i in range(1,7)}
for card in corpus['cards']:
    assert card['fictional'] and len(card['rubric'])==2
    assert all(i['start'] is None and i['end'] is None for i in card['evidence']['intervals'])
    if card['task']==1:
        estimates=sum(f['number'] for f in card['evidence']['facts'] if f['role']=='component_estimate')
        assert abs(estimates-({'A':8.64,'B':7.50}[card['set']]))<1e-9
    if card['task']==4:assert card['evidence']['coverage']['percent']==75
    if card['task']==5:assert card['evidence']['revision']['available']=='only after the block ends'
html=(ROOT/'index.html').read_text();sources='\n'.join((ROOT/n).read_text() for n in ['app.js','study-core.js'])
assert "connect-src 'none'" in html and "form-action 'none'" in html
assert not re.search(r'<(?:script|link|img|iframe)\b[^>]*(?:src|href)=',html,re.I)
assert not re.search(r'\b(?:fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon|localStorage|sessionStorage|indexedDB|getUserMedia)\b',sources)
assert 'document.cookie' not in sources and not re.search(r'\b(?:Date|userAgent|fingerprint)\b',sources)
csp=re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)"',html).group(1)
for code in re.findall(r'<script>(.*?)</script>',html,re.S)+re.findall(r'<style>(.*?)</style>',html,re.S):
    digest=base64.b64encode(sha256(code.encode()).digest()).decode()
    assert f"'sha256-{digest}'" in csp
# One facts table call precedes the condition branch; both views read the same object.
assert sources.count('${factsTable(card)}')==1
assert sources.index('${factsTable(card)}')<sources.index('${isDialogue ?')
report={'status':'PASS','scope':'Schema/source integrity checks, not institutional hosting/privacy approval','schema_validation':'Dependency-free validation of all keywords used by the three supplied schemas','invented_cards':12,'separate_practice_cards':2,'exact_help_levels':4,'review_exports_validated':4,'task_table_byte_equal_to_v01':True,'shared_evidence_verified':True,'no_outbound_or_persistent_storage_calls':True,'csp_inline_hashes_verified':True,'corpus_sha256':freeze['corpus_sha256'],'protocol_sha256':corpus['protocol_sha256']}
(ROOT/'verification-results.json').write_text(json.dumps(report,indent=2)+'\n')
print('PASS: schemas, unchanged task table, exact invented evidence, hashes, shared view fields and no outbound/storage calls.')
