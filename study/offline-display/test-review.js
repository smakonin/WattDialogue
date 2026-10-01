'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {Session,evidenceFor,preparedResponse} = require('./study-core.js');
const corpus = JSON.parse(fs.readFileSync(path.join(__dirname,'corpus.json'),'utf8'));
const freeze = JSON.parse(fs.readFileSync(path.join(__dirname,'review-freeze.json'),'utf8'));
let assertions = 0;
const check = (a,b) => {assert.deepEqual(a,b);assertions++;};
const eligible = {adult:'yes',canadian_billpayer:'yes',english_understanding:'yes',excluded_relationship:'no'};
const fixtures = [];
for (const allocation of corpus.assignments) {
  let now = 0;
  const s = new Session(corpus,allocation.id,() => now);
  s.eligibility = {...eligible};
  assert.throws(() => s.simulateSubmission()); assertions++;
  for (let phase=0;phase<2;phase++) {
    assert.throws(()=>s.startTask());assertions++;
    s.completePractice(phase===0?'completed':'skipped');
    for (let task=1;task<=6;task++) {
      check(s.card.id,allocation.conditions[phase].set+task);
      check(s.condition.view,allocation.conditions[phase].view);
      check(evidenceFor(corpus,s.card.id),s.card.evidence);
      s.startTask();now+=1200;
      check(s.ask('primary'),s.card.questions[0].response);
      check(preparedResponse(corpus,s.card.id,'unavailable'),corpus.unknown_question_response);
      s.pause('page hidden');now+=7000;
      check(s.timing().activeMs,1200);check(s.timing().elapsedMs,8200);
      s.resume();now+=800;
      const r = s.finishTask('completed',{answer:s.card.questions[0].response,confidence:task===1 ? null : 80,note:'Invented testing only.'});
      check(r.active_ms,2000);check(r.elapsed_ms,9000);
      check(r.status,'completed');
    }
    s.rate({find:null,understand:4,uncertainty:4});
    if(phase===0) {now+=6000;s.nextCondition();}
  }
  check(s.records.length,12);check(s.ratings.length,2);check(s.stage,'finished');
  check(s.records.filter(r=>r.condition==='dashboard').length,6);
  check(s.records.filter(r=>r.condition==='dialogue').length,6);
  check(new Set(s.records.map(r=>r.card_id)).size,12);
  s.simulateSubmission();const snapshot=s.snapshot(freeze.corpus_sha256);
  check(snapshot.complete,true);check(snapshot.submission_simulated,true);
  check(snapshot.consent.action,'I agree to take part');
  fixtures.push(snapshot);
  s.stop();check(s.records,[]);check(s.ratings,[]);check(s.events,[]);check(s.consent,null);check(s.eligibility,{});check(s.stage,'discarded');
}
let now=0;const s=new Session(corpus,1,()=>now);s.eligibility={...eligible};s.completePractice();s.startTask();
now=180001;check(s.tick(),true);check(s.current.status,'time_limit');
assert.throws(()=>s.finishTask('completed',{answer:'x'}));assertions++;
s.extend();check(s.current.status,'paused');check(s.timing().limitMs,240000);
s.resume();now+=2000;s.assistance(3);check(s.current.assistanceMax,3);
assert.throws(()=>s.finishTask('completed',{answer:'x',confidence:101}));assertions++;
s.finishTask('skipped');check(s.records[0].answer,null);check(s.records[0].confidence,null);
s.startTask();s.finishTask('technical_fault');check(s.records[1].status,'technical_fault');
s.startTask();now+=180001;s.tick();s.finishTask('timed_out');check(s.records[2].status,'timed_out');
s.stop();check(s.records.length,0);check(s.events.length,0);
for (const record of fixtures) {
  const forbidden=/^(name|email|session_code|review_slot|ip|ip_address|user_agent|timestamp|created_at|withdrawal_code|device_fingerprint)$/i;
  function visit(value) {if(value&&typeof value==='object')for(const [k,v]of Object.entries(value)){assert(!forbidden.test(k),k);visit(v);}}
  visit(record);assertions++;
}
fs.writeFileSync(path.join(__dirname,'synthetic-test-fixtures.json'),JSON.stringify({status:'INVENTED_RESEARCHER_TESTS_ONLY',records:fixtures},null,2)+'\n');
fs.writeFileSync(path.join(__dirname,'test-results.json'),JSON.stringify({status:'PASS',scope:'Pure offline logic; invented researcher fixtures, no participant evidence',assertions,allocations_checked:4,scheduled_tasks_checked:48,network_calls:0,participant_records:0},null,2)+'\n');
process.stdout.write(`PASS: ${assertions} logic checks, four paths, 48 invented task outcomes.\n`);
