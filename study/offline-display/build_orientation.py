"""Prepare separate invented orientation and exact help REVIEW text. No inference."""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parent
cards=json.loads((ROOT/'corpus.json').read_text())['cards']
practice=[]
for i,(energy,hours) in enumerate([(1.50,3),(2.00,4)],1):
    practice.append({'id':f'P{i}','fictional':True,'status':'REVIEW; PI approval pending','title':'Find a value in an invented example','facts':[
        {'label':'Illustrative energy value','text':f'{energy:.2f} kWh'},
        {'label':'Relative example period','text':f'{hours} hours; no actual date or home'},
        {'label':'Source and status','text':'Invented orientation illustration; measurement provenance is not supplied.'}],
        'prompt':'What energy value is shown? Enter the number and unit; this practice is not scored.',
        'questions':[{'id':'primary','label':'What energy value is shown?','response':f'The invented illustration shows {energy:.2f} kWh for a relative {hours}-hour period.'},
                     {'id':'followup1','label':'How long is the example period?','response':f'The relative period is {hours} hours. No actual date is provided.'},
                     {'id':'followup2','label':'Is this my household?','response':'No. This is a separate invented orientation illustration, not a real home or NILM identity result.'}],
        'feedback':f'The illustrated value is {energy:.2f} kWh. In either format, the same value appears in the evidence table. This answer is not scored or retained.'})
help_cards={}
locations={
    1:'Look at the component-estimate rows and the separate aggregate meter total, then the label status and uncertainty. The aggregate and component values describe different evidence types.',
    2:'Look at the earlier and later energy values and their complete, comparable 24-hour windows. Measurement provenance is not supplied.',
    3:'Look at the recurring-power description, the two candidate names and the unconfirmed label status. The identity has no occupant or reference confirmation.',
    4:'Look at observed energy, observed hours, expected hours and 75% coverage. Six hours are missing.',
    5:'Look at the immediate and revised estimates for the same block and the revision-availability statement. Block duration and absolute boundaries are not supplied.',
    6:'Look at the minimum occupied-room temperature, latest permitted activity start, food-storage requirement and three options. Then check uncertainty about savings.'}
for card in cards:
    help_cards[card['id']]={
        '1':card['prompt']+' Enter a short answer in the answer box. Hold the answer to give confidence, or choose Skip task, Pause, or Exit and discard.',
        '2':'The evidence table precedes the answer form. In dialogue, question buttons open prepared explanations; in the dashboard, explanations follow the evidence table. Both show the same underlying information.',
        '3':locations[card['task']],
        '4':card['questions'][0]['response']}
out={'schema_version':'1.0','status':'INVENTED REVIEW MATERIALS; not approved or issued','practice_cards':practice,'practice_assignment':'P1 before the first format; P2 before the second, regardless of condition order','practice_retention':'No practice answer or correctness retained; completion/skip and relative events only','help_levels':{'1':'Repeat task/input instructions','2':'Navigation guidance','3':'Locate evidence','4':'Show prepared energy explanation'},'help_cards':help_cards,'help_retention':'Requested level and relative time only; no observed assistance claim'}
(ROOT/'orientation-and-help.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print('Prepared two separate invented practice cards and four exact help levels for all twelve scored cards.')
