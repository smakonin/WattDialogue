"""Build invented REVIEW materials from the protocol; no network or API access."""
from pathlib import Path
from hashlib import sha256
import json
import random

ROOT = Path(__file__).resolve().parent
PROTOCOL = ROOT.parent / 'WattDialogue_Participant_Protocol_and_Ethics_Draft.tex'
text = PROTOCOL.read_text()
appendix = text.split('\\section{Task sets and frozen scoring rubrics}')[1].split('\\section{Public recruitment notice draft}')[0]
cards = []

def fact(label, value, role='context', number=None, unit=None):
    return {'label': label, 'text': value, 'role': role, 'number': number, 'unit': unit}

def question(qid, label, response):
    return {'id': qid, 'label': label, 'response': response}

def add(set_id, task, title, prompt, facts, interpretation, followups, rubric, **kw):
    card = {
        'id': f'{set_id}{task}', 'set': set_id, 'task': task,
        'title': title, 'prompt': prompt,
        'fictional': True,
        'source': {'document': PROTOCOL.name, 'appendix': 'Task sets and frozen scoring rubrics', 'row': task},
        'evidence': {
            'facts': facts,
            'intervals': kw.pop('intervals', []),
            'coverage': kw.pop('coverage', None),
            'label_status': kw.pop('label_status', 'No appliance identity is supplied for this task.'),
            'uncertainty': kw.pop('uncertainty'),
            'revision': kw.pop('revision', None),
            'comfort': kw.pop('comfort', None),
            'bars': kw.pop('bars', []),
            'boundary_note': 'Absolute timestamps were not supplied in the protocol. Relative durations and availability are shown without invented dates.'
        },
        'questions': [question('primary', prompt, interpretation)] + [question(f'followup{i+1}', *v) for i, v in enumerate(followups)],
        'rubric': rubric,
        'review_status': 'Software checked against Appendix A; PI review and final study freeze pending.'
    }
    assert not kw, kw
    cards.append(card)

def interval(name, duration=None, status='Not specified in the protocol'):
    return {'name': name, 'start': None, 'end': None, 'duration_hours': duration, 'boundary_status': status}

for s in ['A', 'B']:
    a = s == 'A'
    first = '7' if a else '8'
    name = 'dryer' if a else 'dishwasher'
    second = '3' if a else '4'
    values = [4.80, 2.40, .84, .60] if a else [4.20, 2.10, .72, .48]
    total = 9.20 if a else 8.00
    labels = [f'Load {first} ({name})', f'Load {second}', 'Load 12', 'Other components']
    f = [fact('Window', 'Six hours; absolute start and end are not supplied.', 'interval', 6, 'h')]
    f += [fact(l, f'{v:.2f} kWh · component estimate', 'component_estimate', v, 'kWh') for l, v in zip(labels, values)]
    f += [fact('Whole-home meter total', f'{total:.2f} kWh · directly metered aggregate', 'aggregate_meter', total, 'kWh'),
          fact('Appliance name', f'Load {first} is occupant-named {name}. Other load names are not supplied.', 'identity')]
    add(s, 1, 'Estimated loads and the meter', 'Which estimated load used most? Is its value directly metered?', f,
        f'Load {first}, occupant-named {name}, has the largest component estimate: {values[0]:.2f} kWh. That component value is estimated, not directly metered. The {total:.2f} kWh whole-home meter total is the directly measured aggregate.',
        [('What does the meter total mean?', f'The {total:.2f} kWh total is measured for the whole home. The individual load values are component estimates. The protocol does not require their displayed sum to equal that total.'),
         ('What is known about the names?', f'An occupant supplied the name {name} for load {first}. Reference verification is not specified. Names for the remaining components are not supplied.')],
        [f'Identifies load {first} / {name}.', 'States that the component value is an estimate; only the aggregate is directly metered.'],
        intervals=[interval('Six-hour window', 6, 'Relative six-hour duration only')],
        label_status=f'Occupant-named {name}; reference verification not specified. Other components unlabelled.',
        uncertainty='Component energy is estimated. Names are distinct from measured energy. Coverage and reconciliation of the component sum with the meter are not specified.',
        bars=[{'label': l, 'value': v, 'unit': 'kWh', 'role': 'component_estimate'} for l, v in zip(labels, values)])

    earlier, later = (4.80, 6.00) if a else (6.00, 7.50)
    delta = later - earlier
    add(s, 2, 'Comparing complete windows', 'Did use rise or fall, and by how many kWh?',
        [fact('Earlier window', f'{earlier:.2f} kWh · reported energy', 'reported_energy', earlier, 'kWh'),
         fact('Later window', f'{later:.2f} kWh · reported energy', 'reported_energy', later, 'kWh'),
         fact('Comparison', 'Comparable complete 24-hour windows.', 'interval', 24, 'h'),
         fact('Measurement source', 'The protocol does not specify component versus aggregate measurement.', 'provenance')],
        f'Use rose by {delta:.2f} kWh: {later:.2f} minus {earlier:.2f} kWh. Both windows are complete and cover 24 hours. These values show a change, but do not identify its cause.',
        [('How was the difference found?', f'Subtract the earlier value from the later value: {later:.2f} − {earlier:.2f} = +{delta:.2f} kWh.'),
         ('Does the change explain its cause?', 'No. The task supplies comparable energy values, without an appliance cause, tariff or saving model.')],
        ['Identifies an increase.', f'Gives +{delta:.2f} kWh, accepting a difference within 0.01 kWh.'],
        intervals=[interval('Earlier window', 24, 'Earlier complete window; absolute dates absent'), interval('Later window', 24, 'Later complete window; absolute dates absent')],
        coverage={'observed_hours': 24, 'expected_hours': 24, 'percent': 100, 'scope': 'each window'},
        uncertainty='The change is calculable from the supplied values. Measurement provenance and the cause of change are not supplied.',
        bars=[{'label': 'Earlier window', 'value': earlier, 'unit': 'kWh', 'role': 'reported_energy'}, {'label': 'Later window', 'value': later, 'unit': 'kWh', 'role': 'reported_energy'}])

    power = 100 if a else 120
    add(s, 3, 'A name that remains uncertain', 'Can it be called the refrigerator with certainty? What further information would help?',
        [fact('Component', 'Load 12', 'component'),
         fact('Power pattern', f'Recurring {power} W spans; span times and durations are not supplied.', 'component_power', power, 'W'),
         fact('Candidate names', 'Refrigerator or freezer', 'identity'),
         fact('Occupant confirmation', 'None', 'identity'), fact('Reference check', 'None', 'identity')],
        f'No. Load 12 has recurring {power} W spans, but refrigerator and freezer are both candidates. It is not a confirmed refrigerator. An occupant check or a controlled observation of the appliance could help; confidence alone does not establish identity.',
        [('What could help confirm the name?', 'An occupant check or controlled observation could provide more evidence. A confident label without confirmation is still a candidate.'),
         ('What does the power pattern tell us?', f'Only that load 12 has recurring {power} W spans. This example supplies no span timestamps, duty cycle or energy total that could establish a unique appliance identity.')],
        ['Says identity is uncertain and refrigeration is only a candidate.', 'Suggests suitable extra evidence, such as an occupant check or controlled observation; confidence alone is insufficient.'],
        intervals=[interval('Recurring spans')],
        label_status='Candidate refrigerator / freezer; no occupant confirmation or reference check.',
        uncertainty='The physical appliance identity remains uncertain. No probability of a correct name is supplied.')

    observed = 4.80 if a else 6.30
    add(s, 4, 'A day with missing hours', f'Is {observed:.2f} kWh the complete day’s measured consumption?',
        [fact('Observed energy', f'{observed:.2f} kWh over the observed 18 hours', 'observed_energy', observed, 'kWh'),
         fact('Expected window', '24 hours', 'interval', 24, 'h'), fact('Observed duration', '18 hours', 'coverage', 18, 'h'),
         fact('Missing duration', '6 hours', 'coverage', 6, 'h'), fact('Coverage', '75%', 'coverage', 75, '%')],
        f'No. The {observed:.2f} kWh value covers the observed 18 hours, which is 75% of the 24-hour window. Six hours are missing. A complete-day total cannot be established from this evidence, so an exact extrapolated total is not justified.',
        [('Can the missing hours be filled exactly?', 'No. This example supplies no use for the missing six hours. A complete-day energy total cannot be established from the observed value alone.'),
         ('How much of the day is covered?', '18 of 24 hours are observed: 75% coverage. The remaining six hours are missing; their positions in the day are not supplied.')],
        ['States that the value covers observed 18 hours, not the entire day.', 'Says the complete-day total cannot be established; no exact extrapolation is accepted.'],
        intervals=[interval('Expected day', 24, 'Relative 24-hour window only'), interval('Observed duration', 18, 'Missing-hour positions not supplied')],
        coverage={'observed_hours': 18, 'expected_hours': 24, 'percent': 75, 'scope': 'day'},
        uncertainty='The complete-day total and the use during the missing six hours are unknown. Measurement source and missing-hour positions are not supplied.')

    original, revised = (3.20, 3.60) if a else (2.40, 2.80)
    add(s, 5, 'An estimate revised after the block', 'Does the difference mean additional measured energy? Could the revised value have been shown before the block ended?',
        [fact('Component', f'Load {first}; appliance name not supplied for this independent example.', 'component'),
         fact('Immediate estimate', f'{original:.2f} kWh', 'immediate_estimate', original, 'kWh'),
         fact('Post-block revised estimate', f'{revised:.2f} kWh', 'revised_estimate', revised, 'kWh'),
         fact('Availability', 'The revision is available only after the same block ends.', 'availability'),
         fact('Block bounds', 'Completed block; start, end and duration are not supplied.', 'interval')],
        f'No. The change from {original:.2f} to {revised:.2f} kWh revises the estimate for the same block. It is not additional measured energy. The revised value was available only after the block ended and could not have been shown beforehand.',
        [('When was the revised value available?', f'Only after the block ended. Before that point, the {revised:.2f} kWh revision was unavailable.'),
         ('What changed between the two values?', f'The component estimate for the same block changed from {original:.2f} to {revised:.2f} kWh. Neither value is an additional directly measured energy amount.')],
        ['Revision changes the estimate for the same period, not additional measured consumption.', 'States the revised value was unavailable before the block ended.'],
        intervals=[interval('Same completed block')],
        revision={'immediate_kwh': original, 'revised_kwh': revised, 'available': 'only after the block ends', 'same_period': True},
        uncertainty='These are two estimates for one block. No measured component energy, appliance name or block duration is supplied.')

    minimum = 20 if a else 21
    proposed_temp = 17 if a else 18
    latest = '21:00' if a else '22:00'
    delay = '20:00' if a else '21:00'
    activity = 'laundry' if a else 'dishwashing'
    cold = 'refrigerator' if a else 'freezer'
    options = [f'Lower occupied rooms to {proposed_temp} °C.', f'Delay optional {activity} to {delay}.', f'Turn off the {cold}.']
    add(s, 6, 'Comfort and possible savings', 'Which option respects every stated limit? Can a saving be guaranteed?',
        [fact('Minimum occupied-room temperature', f'{minimum} °C', 'comfort', minimum, '°C'),
         fact(f'Latest {activity} start', latest, 'comfort'), fact('Food-storage constraint', f'The {cold} must remain powered.', 'comfort')]
        + [fact(f'Option {i+1}', v, 'option') for i, v in enumerate(options)],
        f'Delaying optional {activity} to {delay} respects all the stated limits. Lowering occupied rooms to {proposed_temp} °C violates the {minimum} °C minimum, and turning off the {cold} violates the food-storage constraint. An energy or cost saving is not guaranteed because no effect or tariff model is supplied.',
        [('Does delaying the activity guarantee a saving?', 'No. This example supplies no energy-effect or tariff model. A permitted schedule change does not establish an energy or cost saving.'),
         ('Which choices conflict with comfort or food storage?', f'{proposed_temp} °C is below the {minimum} °C occupied-room minimum. Turning off the {cold} violates the requirement to keep it powered.')],
        [f'Chooses optional {activity} at {delay} within the latest start.', 'Says an energy/cost saving is not guaranteed without an effect/tariff model and preserves all limits.'],
        label_status='Appliance words are part of an invented comfort card; this is not a NILM identity test.',
        uncertainty='Comfort constraints identify a permitted option. No energy effect, tariff or guaranteed saving is supplied.',
        comfort={'minimum_temperature_c': minimum, 'latest_start': latest, 'proposed_delay': delay, 'must_remain_powered': cold, 'options': options})

assignments = [
    {'id': 1, 'conditions': [{'view': 'dashboard', 'set': 'A'}, {'view': 'dialogue', 'set': 'B'}]},
    {'id': 2, 'conditions': [{'view': 'dialogue', 'set': 'A'}, {'view': 'dashboard', 'set': 'B'}]},
    {'id': 3, 'conditions': [{'view': 'dashboard', 'set': 'B'}, {'view': 'dialogue', 'set': 'A'}]},
    {'id': 4, 'conditions': [{'view': 'dialogue', 'set': 'B'}, {'view': 'dashboard', 'set': 'A'}]}
]
rng = random.Random(20260930)
sequence = []
for _ in range(5):
    block = [1, 2, 3, 4]
    rng.shuffle(block)
    sequence.extend(block)
corpus = {
    'schema_version': '1.0', 'artifact_status': 'STUDY REVIEW — not approved for participant collection',
    'fictional': True, 'protocol_file': PROTOCOL.name,
    'protocol_sha256': sha256(PROTOCOL.read_bytes()).hexdigest(),
    'appendix_sha256': sha256(appendix.encode()).hexdigest(),
    'prepared_by': 'Codex-assisted software preparation; PI review pending',
    'live_inference': False, 'unknown_question_response': 'This study example cannot answer that question.',
    'assignments': assignments,
    'review_allocation': {'seed': 20260930, 'algorithm': 'Python random.Random; shuffle each block of four', 'sequence': sequence, 'status': 'Researcher path-testing only; web design uses browser-side equal-probability allocation, not this enrolment queue'},
    'cards': cards,
    'review_decisions': [
        'No absolute dates/times or unprovided block durations are invented; interval bounds remain null.',
        'Task 1 retains the exact component estimates and aggregate meter totals; no closed energy balance is asserted.',
        'Task 2 energy measurement provenance is not supplied and is not relabelled as directly metered.',
        'Every task is its own invented evidence card, not one continuous household timeline.',
        'Separate P1/P2 orientation and exact help are prepared in orientation-and-help.json; PI review and approval remain required.',
        'The assigned sequence is a REVIEW artifact and does not establish a final participant-study freeze.'
    ]
}
(ROOT / 'corpus.json').write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + '\n')
print(f'Wrote {len(cards)} invented cards and four exact counterbalanced assignments.')
