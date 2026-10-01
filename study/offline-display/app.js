/* Standalone display for invented researcher testing. Data stays in this page's memory. */
'use strict';
const corpus = window.WATT_STUDY_CORPUS;
const app = document.getElementById('app');
const modal = document.getElementById('modal');
let session = null;
let selectedAllocation = 0;
let textScale = 1;
let timeoutModalOpen = false;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const byId = id => document.getElementById(id);
const listen = (id, event, fn) => byId(id)?.addEventListener(event, fn);
const viewName = view => view === 'dashboard' ? 'Readable dashboard' : 'Prepared dialogue';
const formatTime = ms => `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}`;
function announce(text) { byId('announcements').textContent = text; }
function focusHeading() { app.querySelector('h1')?.focus(); }
function showModal(html, setup) {
  if (modal.open) modal.close();
  modal.innerHTML = html;
  modal.showModal();
  if (setup) setup();
}
function closeModal() { modal.close(); }
function error(message) { showModal(`<h2>Please check this entry</h2><p>${esc(message)}</p><button id="dismiss-error" class="primary">Return</button>`, () => listen('dismiss-error', 'click', closeModal)); }
function setupScreen() {
  session = null;
  app.innerHTML = `<section class="panel narrow">
    <div class="eyebrow">Anonymous online study · local REVIEW</div><h1 tabindex="-1">Study information and choice</h1>
    <div class="notice"><strong>Researcher testing only.</strong> Use invented responses. This local review has no approved host or collection backend and sends no answers. It is not open for participant collection.</div>
    <p>Compare two formats using the same invented evidence. The proposed web study is unpaid and uses your own device and connection. Planning estimate: 30–45 minutes, potentially an hour or longer with full allowances and breaks.</p>
    <details class="consent-information" open><summary>Full information and consent REVIEW draft</summary>${window.WATT_CONSENT_REVIEW.metadata.map(text => `<p>${esc(text)}</p>`).join('')}${window.WATT_CONSENT_REVIEW.sections.map(section => `<section><h2>${esc(section.heading)}</h2>${section.paragraphs.map(text => `<p>${esc(text)}</p>`).join('')}</section>`).join('')}</details>
    <div class="notice"><strong>Before final submission:</strong> answers stay in page memory; Exit or closing discards them. <strong>After actual anonymous submission:</strong> individual answers could not be located and removed. The REVIEW button later only simulates that step without a network request. Hosting anonymity is still unverified.</div>
    <form id="consent-form"><div class="field checkbox"><input id="synthetic-only" type="checkbox" required><label for="synthetic-only">I am a researcher testing this REVIEW flow with invented responses, not a participant.</label></div>
    <div class="actions"><button class="primary" type="submit">I agree to take part · REVIEW</button><button id="decline-consent" type="button">I do not agree · exit</button><button id="print-consent" type="button">Print information</button></div></form>
  </section>`;
  listen('consent-form','submit',e => {e.preventDefault(); eligibilityScreen();});
  listen('decline-consent','click',discardScreen);
  listen('print-consent','click',() => window.print());
  focusHeading();
}
function discardScreen() {
  if (session) session.stop();
  session = null;
  app.innerHTML = `<section class="panel narrow"><h1 tabindex="-1">Local answers discarded</h1><p>No research record was sent. This page has no saved return link or participant collection backend.</p><button id="start-again" class="primary">Return to study information</button></section>`;
  listen('start-again','click',setupScreen); focusHeading();
}
function eligibilityScreen() {
  const items = [['adult','Are you 19 years old or older?'],['canadian_billpayer','Do you live in a Canadian residential household and pay or share its electricity bill?'],['english_understanding','Can you understand the English information and tasks with the website and your usual accessibility tools?'],['excluded_relationship','Have you developed or previously tested WattDialogue, are you close family of Stephen Makonin, or are you currently directly supervised, employed, assessed or taught by him?']];
  app.innerHTML = `<section class="panel narrow"><h1 tabindex="-1">Eligibility · invented self-reports</h1><p>These choices stay in memory. Do not enter identity evidence or contact details. There is no payment. Use the same device for both formats.</p><form id="eligibility-form">${items.map(([id,label]) => `<div class="field"><label for="eligible-${id}">${esc(label)}</label><select id="eligible-${id}" required><option value="">Choose</option><option value="yes">Yes</option><option value="no">No</option><option value="decline">Prefer not to answer</option></select></div>`).join('')}
    <details class="review-controls"><summary>Researcher path check only</summary><div class="field"><label for="review-allocation">Allocation for this invented test</label><select id="review-allocation"><option value="0">Equal-probability random order</option>${corpus.assignments.map(a => `<option value="${a.id}">Allocation ${a.id}</option>`).join('')}</select></div><p class="small">Manual paths exist for review only. The planned public study uses equal-probability assignment and does not guarantee balanced completion counts.</p></details>
    <details><summary>Optional invented access responses</summary>${backgroundSelect('digital_confidence','Confidence using a digital display',['very low','low','moderate','high','very high'])}${backgroundSelect('device_access','Reliable access to a personal device',['yes','sometimes','no'])}${backgroundSelect('internet_access','Reliable home Internet access',['yes','sometimes','no'])}${backgroundSelect('prior_energy_display_use','Prior use of energy charts or an energy app',['never','occasionally','often'])}</details>
    <div class="actions"><button type="submit" class="primary">Continue with invented responses</button><button id="eligibility-exit" type="button">Exit and discard</button></div></form></section>`;
  listen('eligibility-exit','click',discardScreen);
  listen('eligibility-form','submit',e => {
    e.preventDefault(); const eligible = Object.fromEntries(items.map(([id]) => [id,byId(`eligible-${id}`).value]));
    if (!['adult','canadian_billpayer','english_understanding'].every(id => eligible[id] === 'yes') || eligible.excluded_relationship !== 'no') {
      app.innerHTML = `<section class="panel narrow"><h1 tabindex="-1">The present study has a limited scope</h1><p>This invented eligibility check does not meet the current criteria. No eligibility or response record was sent or saved.</p><button id="ineligible-exit" class="primary">Exit and discard</button></section>`;listen('ineligible-exit','click',discardScreen);focusHeading();return;
    }
    selectedAllocation = Number(byId('review-allocation').value);
    const allocation = selectedAllocation || ((crypto.getRandomValues(new Uint32Array(1))[0] & 3) + 1);
    session = new StudyCore.Session(corpus,allocation);
    session.eligibility = eligible;
    session.log('allocation_method',{method:selectedAllocation ? 'researcher_manual_review' : 'browser_equal_probability'});
    for (const key of ['digital_confidence','device_access','internet_access','prior_energy_display_use']) session.background[key] = byId(`background-${key}`).value || null;
    render();
  });focusHeading();
}
function backgroundSelect(key, label, values) {
  return `<div class="field"><label for="background-${key}">${esc(label)}</label><select id="background-${key}"><option value="">Prefer not to answer</option>${values.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join('')}</select></div>`;
}
function header() {
  return `<div class="row session-header"><div><span class="badge">Condition ${session.conditionIndex + 1} of 2 · ${viewName(session.condition.view)}</span><p class="small muted">Set ${session.condition.set} · no identity or return code</p></div><div class="progress" aria-label="Task progress">${Array.from({length:6}, (_, i) => `<span class="dot ${i < session.taskIndex ? 'done' : i === session.taskIndex ? 'current' : ''}" aria-hidden="true"></span>`).join('')}<span>Task ${session.taskIndex + 1} of 6</span></div></div>`;
}
function render() {
  if (!session) return setupScreen();
  if (session.stage === 'task') return taskScreen();
  if (session.stage === 'intro' && !session.practiceCompletion.some(p => p.condition_number === session.conditionIndex+1)) return practiceScreen();
  if (['intro','ready'].includes(session.stage)) {
    app.innerHTML = `${header()}<section class="panel narrow"><div class="eyebrow">${session.stage === 'intro' ? 'Condition introduction' : 'Next task'}</div><h1 tabindex="-1">${session.stage === 'intro' ? viewName(session.condition.view) : 'Ready for the next example?'}</h1>
      <p>${session.condition.view === 'dashboard' ? 'The table, labelled bars and interpretation cards describe the evidence.' : 'Use the question buttons to open fixed prepared answers. The evidence table remains available.'} Both formats use the same values, status and uncertainty.</p>
      <p>Each task is an independent invented example. Give an answer in your own words. You may skip, pause or stop. The timer counts time while this page is visible and the task is unpaused. Pause or hiding the page stops that timer; this is not a measure of attention.</p>
      ${session.stage === 'intro' ? '<p class="small">Separate orientation is complete or skipped. Its answers are not scored or retained.</p>' : ''}
      <div class="actions"><button id="start-task" class="primary">Start task ${session.taskIndex + 1}</button><button id="stop-test" class="danger">Stop test</button></div></section>`;
    listen('start-task','click',() => { session.startTask(); render(); });
    listen('stop-test','click',confirmStop);
  } else if (session.stage === 'ratings') ratingsScreen();
  else if (session.stage === 'break') breakScreen();
  else if (session.stage === 'finished') finishedScreen();
  focusHeading();
}
function practiceScreen() {
  const card=window.WATT_ORIENTATION.practice_cards[session.conditionIndex];
  const dialogue=session.condition.view==='dialogue';
  session.log('practice_opened',{practice_id:card.id,condition:session.condition.view});
  app.innerHTML=`${header()}<section class="panel narrow"><div class="eyebrow">Separate orientation · not scored</div><h1 tabindex="-1">Try ${viewName(session.condition.view)}</h1><p>Before the six scored tasks, try reading one simple value. This is a separate invented example. You may skip the practice. No practice answer or correctness is retained.</p><table class="evidence-table"><caption>Invented orientation ${card.id}</caption><tbody>${card.facts.map(f=>`<tr><th scope="row">${esc(f.label)}</th><td>${esc(f.text)}</td></tr>`).join('')}</tbody></table><p><strong>Label status:</strong> No appliance identity is supplied.</p><p><strong>Uncertainty:</strong> This is illustrative; measurement provenance is not supplied.</p>${dialogue?`<div class="questions">${card.questions.map(q=>`<button type="button" data-practice-question="${q.id}">${esc(q.label)}</button>`).join('')}</div><div id="practice-explanation" class="response" aria-live="polite">Choose a prepared question.</div>`:`<section><h2>What this evidence means</h2>${card.questions.map(q=>`<article class="interpretation"><h3>${esc(q.label)}</h3><p>${esc(q.response)}</p></article>`).join('')}</section>`}<form id="practice-form"><div class="field"><label for="practice-answer">${esc(card.prompt)}</label><input id="practice-answer" type="text" maxlength="100" autocomplete="off"></div><div class="actions"><button type="submit" class="primary">Try practice answer</button><button id="skip-practice" type="button">Skip practice</button><button id="practice-exit" type="button" class="danger">Exit and discard</button></div></form></section>`;
  app.querySelectorAll('[data-practice-question]').forEach(button=>button.addEventListener('click',()=>{byId('practice-explanation').textContent=card.questions.find(q=>q.id===button.dataset.practiceQuestion).response;}));
  listen('practice-form','submit',e=>{e.preventDefault();byId('practice-answer').value='';showModal(`<h2>Practice feedback</h2><p>${esc(card.feedback)}</p><p>For scored tasks, enter an answer, then confidence. Skip leaves a task unanswered. Pause and tab hiding stop the visible/unpaused timer; closing or Exit discards the whole unsubmitted packet.</p><button id="practice-done" class="primary">Continue to scored examples</button>`,()=>listen('practice-done','click',()=>{session.completePractice();closeModal();render();}));});
  listen('skip-practice','click',()=>{session.completePractice('skipped');render();});listen('practice-exit','click',confirmStop);focusHeading();
}
function factsTable(card) {
  const evidence = StudyCore.evidenceFor(corpus, card.id);
  return `<table class="evidence-table" data-card-id="${card.id}" data-evidence-hash="${window.WATT_REVIEW_FREEZE.card_evidence_sha256[card.id]}"><caption>Invented evidence · ${card.id}</caption><tbody>${evidence.facts.map(f => `<tr data-role="${esc(f.role)}"><th scope="row">${esc(f.label)}</th><td>${esc(f.text)}</td></tr>`).join('')}</tbody></table>
    <div class="evidence-note"><p><strong>Label status:</strong> ${esc(evidence.label_status)}</p><p><strong>Uncertainty:</strong> ${esc(evidence.uncertainty)}</p></div>`;
}
function bars(card) {
  const values = card.evidence.bars;
  if (!values.length) return '';
  const maximum = Math.max(...values.map(v => v.value));
  return `<div class="bars" aria-label="Labelled energy comparison">${values.map(v => `<div class="bar-item"><div class="row"><span>${esc(v.label)}</span><strong>${v.value.toFixed(2)} ${esc(v.unit)}</strong></div><div class="bar-track" aria-hidden="true"><div class="bar-fill" data-bar-percent="${100*v.value/maximum}"></div></div></div>`).join('')}</div>`;
}
function taskScreen() {
  const card = session.card;
  const isDialogue = session.condition.view === 'dialogue';
  app.innerHTML = `${header()}<div class="task-layout"><section class="panel"><div class="eyebrow">Fictional household · study example</div><h1 tabindex="-1">${esc(card.title)}</h1><p class="task-prompt">${esc(card.prompt)}</p>
    ${factsTable(card)}
    ${isDialogue ? `<section aria-labelledby="questions-heading"><h2 id="questions-heading">Prepared questions</h2><p class="small muted">These buttons retrieve checked examples. There is no free-form chat.</p><div class="questions">${card.questions.map(q => `<button type="button" class="question-button" data-question-id="${q.id}" aria-pressed="false">${esc(q.label)}</button>`).join('')}</div><div class="response" id="prepared-response" aria-live="polite"><p>Choose a question to open its prepared explanation.</p></div><p class="small muted">Choose from the prepared questions above. This review does not accept unrestricted chat.</p></section>` : `${bars(card)}<section aria-labelledby="interpretation-heading"><h2 id="interpretation-heading">What this evidence means</h2>${card.questions.map(q => `<article class="interpretation" data-question-id="${q.id}"><h3>${esc(q.label)}</h3><p>${esc(q.response)}</p></article>`).join('')}</section>`}
    </section><aside class="panel answer-panel" aria-labelledby="answer-heading"><div class="timer row"><span>Visible, unpaused <b id="timer-active">0:00</b> / <span id="timer-limit">3:00</span></span><span class="small muted">Elapsed <span id="timer-elapsed">0:00</span></span></div><h2 id="answer-heading">Your answer</h2><p class="small muted">Invented responses only during researcher review. Do not enter personal details.</p>
      <form id="answer-form"><div class="field"><label for="task-answer">Answer in your own words</label><textarea id="task-answer" maxlength="1200" autocomplete="off" spellcheck="true"></textarea></div>
      <div class="actions"><button type="submit" class="primary">Hold answer and continue</button><button id="skip-task" type="button">Skip task</button><button id="pause-task" type="button">Pause</button><button id="stop-test" type="button" class="danger">Exit and discard</button></div>
      <details class="review-controls"><summary>Guidance and optional issue note</summary><div class="questions">${[1,2,3,4].map(level => `<button type="button" data-help-level="${level}">${['','Repeat instructions / input help','Navigation guidance','Locate relevant evidence','Show prepared explanation'][level]}</button>`).join('')}</div>
        <div class="field"><label for="task-note">Optional technical/accessibility issue about this example</label><textarea id="task-note" maxlength="500" autocomplete="off"></textarea><small>No personal details.</small></div><div class="actions"><button id="technical-fault" type="button">Report technical fault</button></div>
        <details><summary>Synthetic researcher helper · not a participant control</summary><button id="synthetic-fill" type="button">Fill invented test answer</button></details>
      </details></form></aside></div>`;
  app.querySelectorAll('[data-bar-percent]').forEach(el => { el.style.width = `${el.dataset.barPercent}%`; });
  app.querySelectorAll('.question-button').forEach(button => button.addEventListener('click', () => {
    if (session.current.status !== 'running') return;
    const response = session.ask(button.dataset.questionId);
    byId('prepared-response').innerHTML = '<p></p>';
    byId('prepared-response').firstChild.textContent = response;
    app.querySelectorAll('.question-button').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
  }));
  listen('answer-form','submit',e => { e.preventDefault(); confidenceScreen(); });
  listen('skip-task','click',() => finish('skipped'));
  listen('pause-task','click',() => pause('requested break'));
  app.querySelectorAll('[data-help-level]').forEach(button => button.addEventListener('click',() => {
    const level = Number(button.dataset.helpLevel); session.assistance(level);
    const guidance = window.WATT_ORIENTATION.help_cards[card.id][String(level)];
    showModal(`<h2>Guidance</h2><p>${esc(guidance)}</p><p class="small">Browser-visible task time continues while this guidance is open.</p><button id="close-guidance" class="primary">Return to task</button>`,() => listen('close-guidance','click',closeModal));
  }));
  listen('synthetic-fill','click',() => {
    byId('task-answer').value = card.questions[0].response;
    byId('task-note').value = 'Invented researcher-testing response; not participant data.';
    session.log('synthetic_test_answer_filled', {card_id: card.id});
  });
  listen('technical-fault','click',() => finish('technical_fault'));
  listen('stop-test','click',confirmStop);
  updateTimer();
  focusHeading();
}
function draft() {
  const confidence = byId('confidence')?.value ?? '';
  return {answer: byId('task-answer')?.value || '', confidence: confidence === '' ? null : Number(confidence), note: byId('task-note')?.value || ''};
}
function confidenceScreen() {
  if (!byId('task-answer').value.trim()) return error('Enter an answer or use Skip task.');
  if (!session.pause('answer held; confidence follows')) return showPause(session.current.status === 'time_limit');
  showModal('<h2>Confidence in your answer</h2><p>Browser-visible answer time is paused. Choose 0–100, or leave blank.</p><form id="confidence-form"><div class="field"><label for="confidence">0 = not confident; 100 = completely confident</label><input id="confidence" type="number" min="0" max="100" step="1" inputmode="numeric" autocomplete="off"></div><div class="actions"><button type="submit" class="primary">Continue</button><button id="revise-answer" type="button">Return to answer</button></div></form>',() => {
    listen('confidence-form','submit',e => {e.preventDefault(); finish('completed');});
    listen('revise-answer','click',() => {session.resume();closeModal();});
  });
}
function finish(status) {
  try {
    session.finishTask(status, draft());
    timeoutModalOpen = false;
    if (modal.open) closeModal();
    render();
  } catch (err) { error(err.message); }
}
function pause(reason) {
  if (!session?.pause(reason)) return;
  showPause(false);
}
function showPause(isTimeout) {
  timeoutModalOpen = isTimeout;
  showModal(`<h2>${isTimeout ? 'Browser-visible time limit reached' : 'Task paused'}</h2><p>${isTimeout ? 'The three-minute browser-visible unpaused allowance is complete. Record the task as timed out, or add time for an accommodation before resuming.' : 'The visible, unpaused timer is stopped. The evidence and answer form are unavailable while this dialog is open. Elapsed time continues.'}</p><p class="small muted">You may add time for an accommodation. A technical fault is recorded as missing rather than incorrect.</p><div class="actions">${isTimeout ? '<button id="record-timeout" class="primary">Record timeout and continue</button>' : '<button id="resume-task" class="primary">Resume task</button>'}<button id="add-minute">Add 1 minute for accommodation</button><button id="paused-fault">Record technical fault</button></div>`, () => {
    listen('resume-task','click',() => { session.resume(); timeoutModalOpen = false; closeModal(); });
    listen('record-timeout','click',() => finish('timed_out'));
    listen('add-minute','click',() => { session.extend(); showPause(false); });
    listen('paused-fault','click',() => finish('technical_fault'));
  });
}
modal.addEventListener('cancel', e => {
  if (session?.stage === 'task' && ['paused','time_limit'].includes(session.current.status)) e.preventDefault();
});
function updateTimer() {
  if (session?.stage !== 'task') return;
  if (session.tick() && !timeoutModalOpen) { showPause(true); announce('The visible, unpaused time limit is reached.'); }
  const t = session.timing();
  if (byId('timer-active')) byId('timer-active').textContent = formatTime(t.activeMs);
  if (byId('timer-elapsed')) byId('timer-elapsed').textContent = formatTime(t.elapsedMs);
  if (byId('timer-limit')) byId('timer-limit').textContent = formatTime(t.limitMs);
}
function ratingSelect(key, label) {
  return `<div class="field"><label for="rating-${key}">${esc(label)}</label><select id="rating-${key}"><option value="">Skip this rating</option>${[1,2,3,4,5].map(v => `<option value="${v}">${v}${v === 1 ? ' · very low' : v === 5 ? ' · very high' : ''}</option>`).join('')}</select></div>`;
}
function ratingsScreen() {
  app.innerHTML = `${header()}<section class="panel narrow"><div class="eyebrow">Optional ratings</div><h1 tabindex="-1">How was this format?</h1><p>Choose 1 to 5, or skip. These are study-specific questions.</p><form id="ratings-form" class="ratings">${ratingSelect('find','Ease of finding the needed information')}${ratingSelect('understand','Ease of understanding the information')}${ratingSelect('uncertainty','Confidence about what remains uncertain')}<div class="actions"><button type="submit" class="primary">Continue</button><button id="stop-test" type="button" class="danger">Stop test</button></div></form></section>`;
  listen('ratings-form','submit',e => {
    e.preventDefault();
    const values = {};
    for (const key of ['find','understand','uncertainty']) values[key] = byId(`rating-${key}`).value ? Number(byId(`rating-${key}`).value) : null;
    session.rate(values); render();
  });
  listen('stop-test','click',confirmStop);
}
function breakScreen() {
  app.innerHTML = `<section class="panel narrow blank-state"><div class="eyebrow">Between conditions</div><h1 tabindex="-1">Take a break</h1><p>A three-minute rest is offered. There is no need to wait if you wish to continue. Continue only if you still wish to take part. Exit discards all unsubmitted answers.</p><p>Suggested rest elapsed: <strong id="break-elapsed">0:00</strong></p><div class="notice small">Separate orientation precedes the next format. Correct scored-task feedback belongs after both formats; practice gives its own unscored feedback.</div><div class="actions"><button id="next-condition" class="primary">Continue to second format</button><button id="stop-test" class="danger">Stop test</button></div></section>`;
  listen('next-condition','click',() => { session.nextCondition(); render(); });
  listen('stop-test','click',confirmStop);
}
function finishedScreen() {
  const simulated = session.submissionSimulated;
  app.innerHTML = `<section class="panel"><div class="eyebrow">Final review · no collection backend</div><h1 tabindex="-1">${simulated ? 'Final submission simulated' : 'Both formats finished'}</h1><p>Twelve task outcomes remain only in this page’s memory. No answers have been transmitted or automatically saved.</p><div class="notice">In the proposed public study, only the final Submit action would send the completed anonymous research packet. After that, individual removal would be impossible without an identity link. This REVIEW build has no such endpoint and does not establish hosting anonymity, approval or encrypted storage.</div>
    <div class="results-table-wrap"><table class="results-table"><caption>Invented test outcomes · no automatic correctness scoring</caption><thead><tr><th>Card</th><th>Format</th><th>Status</th><th>Visible unpaused time</th><th>Confidence</th></tr></thead><tbody>${session.records.map(r => `<tr><td>${r.card_id}</td><td>${viewName(r.condition)}</td><td>${esc(r.status.replaceAll('_',' '))}</td><td>${formatTime(r.active_ms)}</td><td>${r.confidence ?? 'skipped'}</td></tr>`).join('')}</tbody></table></div>
    ${!simulated ? `<form id="final-review-form"><h2>Optional written feedback</h2>${window.WATT_FEEDBACK_QUESTIONS.map((q,i) => `<div class="field"><label for="feedback-${i}">${esc(q)}</label><textarea id="feedback-${i}" maxlength="700" autocomplete="off"></textarea></div>`).join('')}<p class="small">Discuss only the invented examples. No personal names, accounts or household data.</p><div class="field checkbox"><input id="submit-understanding" type="checkbox" required><label for="submit-understanding">For this invented review, I understand the planned withdrawal limit and that this action simulates final submission without sending anything.</label></div><div class="actions"><button type="submit" class="primary">Simulate final anonymous Submit · REVIEW</button><button id="reset-test" type="button" class="danger">Exit and discard</button></div></form>` : `<p>Simulation complete. Optional plaintext JSON export is for invented researcher checks only, with no identity or withdrawal code.</p><div class="actions"><button id="review-export" class="primary">Review optional researcher JSON export</button><button id="reset-test" class="danger">Clear local review data</button></div>`}</section>`;
  listen('final-review-form','submit',e => {
    e.preventDefault();session.feedback=Object.fromEntries(window.WATT_FEEDBACK_QUESTIONS.map((_,i) => [`item_${i+1}`,byId(`feedback-${i}`).value.trim().slice(0,700) || null]));
    session.simulateSubmission();finishedScreen();focusHeading();
  });
  listen('review-export','click',reviewExport);listen('reset-test','click',confirmReset);focusHeading();
}
function confirmStop() {
  const paused = session?.stage === 'task' && session.pause('exit confirmation');
  showModal('<h2>Exit and discard local answers?</h2><p>Nothing has been submitted. This clears all current answers and events from page memory; there is no saved return link.</p><div class="actions"><button id="confirm-stop" class="danger">Exit and discard</button><button id="keep-going" class="primary">Keep going</button></div>',() => {
    listen('confirm-stop','click',() => {closeModal();discardScreen();});
    listen('keep-going','click',() => {if(paused)session.resume();closeModal();});
  });
}
function confirmReset() {
  showModal('<h2>Clear this test from memory?</h2><p>This clears its answers and events in the page. An exported file, if any, must be managed separately.</p><div class="actions"><button id="confirm-clear" class="danger">Clear test</button><button id="cancel-clear" class="primary">Return</button></div>', () => {
    listen('confirm-clear','click',() => { closeModal(); setupScreen(); });
    listen('cancel-clear','click',closeModal);
  });
}
function reviewExport() {
  if (!session.submissionSimulated) return error('Simulate final submission before any invented researcher export.');
  const record = session.snapshot(window.WATT_REVIEW_FREEZE.corpus_sha256);
  const encoded = JSON.stringify(record, null, 2);
  showModal('<h2>Optional researcher export</h2><p>Only invented testing records may be exported from this REVIEW build. The downloaded JSON is plaintext. Actual participant records would require approval and institutionally approved encrypted storage and handling.</p><pre id="export-preview" tabindex="0" aria-label="JSON export preview"></pre><div class="field checkbox"><input id="export-confirm" type="checkbox"><label for="export-confirm">I confirm these are invented test responses and I understand the file is not encrypted by this display.</label></div><div class="actions"><button id="download-json" class="primary" disabled>Export invented test JSON</button><button id="cancel-export">Return without export</button></div>', () => {
    byId('export-preview').textContent = encoded;
    listen('export-confirm','change',() => { byId('download-json').disabled = !byId('export-confirm').checked; });
    listen('cancel-export','click',closeModal);
    listen('download-json','click',() => {
      if (!byId('export-confirm').checked) return;
      const blob = new Blob([encoded], {type:'application/json'});
      const localUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = localUrl; link.download = 'WattDialogue_anonymous_REVIEW_test.json';
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(localUrl), 1000);
      announce('Invented test JSON exported. Manage the plaintext file separately.');
      closeModal();
    });
  });
}
function scale(delta) {
  textScale = Math.min(1.5, Math.max(1, Math.round((textScale + delta) * 10) / 10));
  document.documentElement.style.setProperty('--text-scale', textScale);
  byId('text-scale-label').textContent = `${Math.round(textScale * 100)}%`;
  if (session) session.log('text_scale_changed', {scale: textScale});
}
listen('smaller-text','click',() => scale(-.1));
listen('larger-text','click',() => scale(.1));
document.addEventListener('visibilitychange',() => {
  if (document.hidden && session?.stage === 'task' && session.current.status === 'running') pause('page hidden');
});
window.addEventListener('beforeunload', e => {
  if (session && !session.submissionSimulated) { e.preventDefault(); e.returnValue = ''; }
});
setInterval(() => {
  updateTimer();
  if (session?.stage === 'break' && byId('break-elapsed')) byId('break-elapsed').textContent = formatTime(performance.now() - session.breakStarted);
}, 250);
setupScreen();
