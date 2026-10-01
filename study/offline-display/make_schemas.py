"""Document the invented corpus and anonymous-flow REVIEW export structures."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent
S = {'type': 'string'}
NULLABLE_S = {'type': ['string', 'null']}
NULLABLE_N = {'type': ['number', 'null']}
def obj(properties, required=None, extra=False):
    return {'type': 'object', 'properties': properties, 'required': list(properties) if required is None else required, 'additionalProperties': extra}
def array(item, **kw): return {'type': 'array', 'items': item, **kw}
def choice(*values): return {'enum': list(values)}
fact = obj({'label': S, 'text': S, 'role': S, 'number': NULLABLE_N, 'unit': NULLABLE_S})
interval = obj({'name': S, 'start': {'type': 'null'}, 'end': {'type': 'null'}, 'duration_hours': NULLABLE_N, 'boundary_status': S})
coverage = {'anyOf': [{'type': 'null'}, obj({'observed_hours': {'type':'number'}, 'expected_hours': {'type':'number'}, 'percent': {'type':'number','minimum':0,'maximum':100}, 'scope': S})]}
evidence = obj({'facts': array(fact, minItems=1), 'intervals': array(interval), 'coverage': coverage, 'label_status': S, 'uncertainty': S,
    'revision': {'anyOf': [{'type':'null'}, obj({'immediate_kwh': {'type':'number'}, 'revised_kwh': {'type':'number'}, 'available': S, 'same_period': {'const':True}})]},
    'comfort': {'anyOf':[{'type':'null'},obj({'minimum_temperature_c': {'type':'number'}, 'latest_start': S, 'proposed_delay': S, 'must_remain_powered': S, 'options': array(S,minItems=3,maxItems=3)})]},
    'bars': array(obj({'label':S,'value':{'type':'number'},'unit':S,'role':S})), 'boundary_note':S})
card = obj({'id':{'type':'string','pattern':'^[AB][1-6]$'},'set':choice('A','B'),'task':{'type':'integer','minimum':1,'maximum':6},'title':S,'prompt':S,'fictional':{'const':True},
    'source':obj({'document':S,'appendix':S,'row':{'type':'integer','minimum':1,'maximum':6}}),'evidence':evidence,
    'questions':array(obj({'id':choice('primary','followup1','followup2'),'label':S,'response':S}),minItems=1,maxItems=3),
    'rubric':array(S,minItems=2,maxItems=2),'review_status':S})
allocation=obj({'id':{'type':'integer','minimum':1,'maximum':4},'conditions':array(obj({'view':choice('dashboard','dialogue'),'set':choice('A','B')}),minItems=2,maxItems=2)})
corpus=obj({'schema_version':{'const':'1.0'},'artifact_status':S,'fictional':{'const':True},'protocol_file':S,'protocol_sha256':S,'appendix_sha256':S,'prepared_by':S,'live_inference':{'const':False},'unknown_question_response':S,
    'assignments':array(allocation,minItems=4,maxItems=4),'review_allocation':obj({'seed':{'type':'integer'},'algorithm':S,'sequence':array({'type':'integer','minimum':1,'maximum':4},minItems=20,maxItems=20),'status':S}),
    'cards':array(card,minItems=12,maxItems=12),'review_decisions':array(S)})
corpus={'$schema':'https://json-schema.org/draft/2020-12/schema','title':'WattDialogue invented STUDY REVIEW corpus',**corpus}
confidence={'anyOf':[{'type':'null'},{'type':'integer','minimum':0,'maximum':100}]}
task=obj({'card_id':S,'task':{'type':'integer','minimum':1,'maximum':6},'set':choice('A','B'),'condition':choice('dashboard','dialogue'),'condition_number':choice(1,2),'status':choice('completed','skipped','technical_fault','timed_out','stopped_session'),
    'answer':NULLABLE_S,'confidence':confidence,'active_ms':{'type':'integer','minimum':0},'elapsed_ms':{'type':'integer','minimum':0},'limit_ms':{'type':'integer','minimum':180000},'help_max':{'type':'integer','minimum':0,'maximum':4},
    'help_events':array(obj({'level':{'type':'integer','minimum':0,'maximum':4},'elapsed_ms':{'type':'integer','minimum':0}})), 'optional_task_note':S,
    'prepared_questions_opened':array(S),'accommodation_extensions':array(obj({'additional_ms':{'type':'integer','minimum':1},'elapsed_ms':{'type':'integer','minimum':0}}))})
rating={'anyOf':[{'type':'null'},{'type':'integer','minimum':1,'maximum':5}]}
record=obj({'schema_version':{'const':'1.0'},'record_kind':{'const':'synthetic_researcher_test'},'study_status':{'const':'REVIEW_NOT_APPROVED'},'export_notice':S,'assignment_id':{'type':'integer','minimum':1,'maximum':4},'corpus_sha256':S,'stage':S,'complete':{'type':'boolean'},
    'consent':obj({'version':S,'action':{'const':'I agree to take part'}}),'eligibility':obj({'adult':{'const':'yes'},'canadian_billpayer':{'const':'yes'},'english_understanding':{'const':'yes'},'excluded_relationship':{'const':'no'}}),
    'background':obj({'digital_confidence':NULLABLE_S,'device_access':NULLABLE_S,'internet_access':NULLABLE_S,'prior_energy_display_use':NULLABLE_S},required=[]),'tasks':array(task,maxItems=12),
    'condition_ratings':array(obj({'condition':choice('dashboard','dialogue'),'set':choice('A','B'),'find':rating,'understand':rating,'uncertainty':rating}),maxItems=2),
    'events':array(obj({'type':S,'elapsed_ms':{'type':'integer','minimum':0}},required=['type','elapsed_ms'],extra=True)),
    'practice_completion':array(obj({'practice_id':choice('P1','P2'),'condition':choice('dashboard','dialogue'),'condition_number':choice(1,2),'status':choice('completed','skipped')}),maxItems=2),'feedback':obj({f'item_{i}':NULLABLE_S for i in range(1,6)},required=[]),'submission_simulated':{'type':'boolean'}})
record={'$schema':'https://json-schema.org/draft/2020-12/schema','title':'WattDialogue anonymous-flow synthetic researcher-testing export',**record}
practice=obj({'id':choice('P1','P2'),'fictional':{'const':True},'status':S,'title':S,'facts':array(obj({'label':S,'text':S}),minItems=3,maxItems=3),'prompt':S,'questions':array(obj({'id':choice('primary','followup1','followup2'),'label':S,'response':S}),minItems=3,maxItems=3),'feedback':S})
help_text=obj({str(i):S for i in range(1,5)})
orientation={'$schema':'https://json-schema.org/draft/2020-12/schema','title':'WattDialogue separate invented orientation and requested-help REVIEW materials',**obj({'schema_version':{'const':'1.0'},'status':S,'practice_cards':array(practice,minItems=2,maxItems=2),'practice_assignment':S,'practice_retention':S,'help_levels':help_text,'help_cards':obj({f'{s}{i}':help_text for s in 'AB' for i in range(1,7)}),'help_retention':S})}
for name,data in [('corpus.schema.json',corpus),('session-record.schema.json',record),('orientation-and-help.schema.json',orientation)]:
    (ROOT/name).write_text(json.dumps(data,indent=2)+'\n')
print('Wrote corpus and anonymous-flow REVIEW export JSON schemas.')
