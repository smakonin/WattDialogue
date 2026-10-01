/* In-memory REVIEW session logic. No storage, network or inference. */
(function (root) {
  'use strict';
  function evidenceFor(corpus, cardId) {
    const card = corpus.cards.find(c => c.id === cardId);
    if (!card) throw new Error('Unknown evidence card');
    return card.evidence;
  }
  function preparedResponse(corpus, cardId, questionId) {
    const card = corpus.cards.find(c => c.id === cardId);
    return card?.questions.find(q => q.id === questionId)?.response || corpus.unknown_question_response;
  }
  class Session {
    constructor(corpus, assignmentId, clock = () => performance.now()) {
      this.corpus = corpus;
      this.assignment = corpus.assignments.find(a => a.id === assignmentId);
      if (!this.assignment) throw new Error('Unknown allocation');
      this.clock = clock;
      this.started = clock();
      this.conditionIndex = 0;
      this.taskIndex = 0;
      this.stage = 'intro';
      this.current = null;
      this.records = [];
      this.ratings = [];
      this.events = [];
      this.background = {};
      this.consent = {version: 'v0.2-20260930-REVIEW', action: 'I agree to take part'};
      this.eligibility = {};
      this.feedback = {};
      this.practiceCompletion = [];
      this.submissionSimulated = false;
      this.log('session_started', {assignment_id: assignmentId});
    }
    get condition() { return this.assignment.conditions[this.conditionIndex]; }
    get card() { return this.corpus.cards.find(c => c.set === this.condition.set && c.task === this.taskIndex + 1); }
    log(type, details = {}) { this.events.push({type, elapsed_ms: Math.max(0, Math.round(this.clock() - this.started)), ...details}); }
    startTask() {
      if (!['intro', 'ready'].includes(this.stage)) throw new Error('Task cannot start in this stage');
      if (!this.practiceCompletion.some(p => p.condition_number === this.conditionIndex + 1)) throw new Error('Complete or skip separate orientation first');
      const now = this.clock();
      this.current = {started: now, activeStarted: now, activeMs: 0, limitMs: 180000, status: 'running', assistanceMax: 0, assistance: [], questions: [], extensions: []};
      this.stage = 'task';
      this.log('task_started', {card_id: this.card.id, condition: this.condition.view});
    }
    timing() {
      if (!this.current) return {activeMs: 0, elapsedMs: 0, limitMs: 180000};
      const c = this.current;
      const active = c.activeMs + (c.status === 'running' ? Math.max(0, this.clock() - c.activeStarted) : 0);
      return {activeMs: Math.min(active, c.limitMs), elapsedMs: Math.max(0, this.clock() - c.started), limitMs: c.limitMs};
    }
    tick() {
      if (this.current?.status === 'running' && this.timing().activeMs >= this.current.limitMs) {
        this.current.activeMs = this.current.limitMs;
        this.current.activeStarted = null;
        this.current.status = 'time_limit';
        this.log('task_time_limit', {card_id: this.card.id});
        return true;
      }
      return false;
    }
    pause(reason) {
      this.tick();
      if (this.current?.status !== 'running') return false;
      this.current.activeMs = this.timing().activeMs;
      this.current.activeStarted = null;
      this.current.status = 'paused';
      this.log('task_paused', {reason, card_id: this.card.id});
      return true;
    }
    resume() {
      if (this.current?.status !== 'paused') return false;
      this.current.activeStarted = this.clock();
      this.current.status = 'running';
      this.log('task_resumed', {card_id: this.card.id});
      return true;
    }
    extend(ms = 60000) {
      if (!this.current || !['paused', 'time_limit'].includes(this.current.status)) throw new Error('Pause before extending');
      this.current.limitMs += ms;
      this.current.status = 'paused';
      this.current.extensions.push({additional_ms: ms, elapsed_ms: Math.round(this.clock() - this.current.started)});
      this.log('accommodation_time_added', {card_id: this.card.id, additional_ms: ms});
    }
    assistance(level) {
      if (!Number.isInteger(level) || level < 0 || level > 4 || !this.current) throw new Error('Invalid assistance');
      this.current.assistanceMax = Math.max(this.current.assistanceMax, level);
      this.current.assistance.push({level, elapsed_ms: Math.round(this.clock() - this.current.started)});
      this.log('help_requested', {card_id: this.card.id, level});
    }
    ask(questionId) {
      if (!this.current || this.current.status !== 'running') return this.corpus.unknown_question_response;
      if (this.card.questions.some(q => q.id === questionId)) {
        this.current.questions.push(questionId);
        this.log('prepared_question_opened', {card_id: this.card.id, question_id: questionId});
      }
      return preparedResponse(this.corpus, this.card.id, questionId);
    }
    finishTask(status, details = {}) {
      if (this.stage !== 'task' || !this.current) throw new Error('No active task');
      this.tick();
      if (!['completed', 'skipped', 'technical_fault', 'timed_out', 'stopped_session'].includes(status)) throw new Error('Invalid outcome');
      if (this.current.status === 'time_limit' && !['timed_out', 'technical_fault', 'stopped_session'].includes(status)) throw new Error('Extend time or record timeout');
      const timing = this.timing();
      const confidence = details.confidence ?? null;
      if (confidence !== null && (!Number.isInteger(confidence) || confidence < 0 || confidence > 100)) throw new Error('Confidence must be an integer from 0 to 100 or null');
      if (status === 'completed' && !String(details.answer || '').trim()) throw new Error('Answer required for completion; use skip instead');
      const record = {
        card_id: this.card.id, task: this.card.task, set: this.card.set, condition: this.condition.view,
        condition_number: this.conditionIndex + 1, status,
        answer: status === 'completed' ? String(details.answer).trim().slice(0, 1200) : null,
        confidence: status === 'completed' ? confidence : null,
        active_ms: Math.round(timing.activeMs), elapsed_ms: Math.round(timing.elapsedMs), limit_ms: timing.limitMs,
        help_max: this.current.assistanceMax, help_events: this.current.assistance,
        optional_task_note: String(details.note || '').trim().slice(0, 500),
        prepared_questions_opened: this.current.questions,
        accommodation_extensions: this.current.extensions
      };
      this.records.push(record);
      this.log('task_finished', {card_id: this.card.id, status});
      this.current = null;
      if (status === 'stopped_session') this.stage = 'finished';
      else if (this.taskIndex === 5) this.stage = 'ratings';
      else { this.taskIndex += 1; this.stage = 'ready'; }
      return record;
    }
    rate(values) {
      if (this.stage !== 'ratings') throw new Error('Ratings are not due');
      for (const value of Object.values(values)) if (value !== null && (!Number.isInteger(value) || value < 1 || value > 5)) throw new Error('Rating must be 1–5 or null');
      this.ratings.push({condition: this.condition.view, set: this.condition.set, ...values});
      if (this.conditionIndex === 0) { this.stage = 'break'; this.breakStarted = this.clock(); }
      else this.stage = 'finished';
      this.log('condition_ratings_finished', {condition: this.condition.view});
    }
    nextCondition() {
      if (this.stage !== 'break') throw new Error('No condition break');
      this.log('condition_break_ended', {duration_ms: Math.round(this.clock() - this.breakStarted)});
      this.conditionIndex = 1; this.taskIndex = 0; this.stage = 'intro';
    }
    completePractice(status='completed') {
      if (this.stage !== 'intro' || !['completed','skipped'].includes(status)) throw new Error('Practice is not due');
      if (this.practiceCompletion.some(p => p.condition_number === this.conditionIndex+1)) throw new Error('Practice already recorded');
      this.practiceCompletion.push({practice_id:'P'+(this.conditionIndex+1),condition:this.condition.view,condition_number:this.conditionIndex+1,status});
      this.log('practice_finished',{practice_id:'P'+(this.conditionIndex+1),condition:this.condition.view,status});
    }
    stop() {
      this.current = null;
      this.records = []; this.ratings = []; this.events = [];
      this.background = {}; this.eligibility = {}; this.feedback = {}; this.consent = null;
      this.practiceCompletion = [];
      this.stage = 'discarded';
    }
    simulateSubmission() {
      if (this.records.length !== 12 || this.ratings.length !== 2 || this.practiceCompletion.length !== 2 || this.stage !== 'finished') throw new Error('Complete both formats before final review submission');
      this.submissionSimulated = true;
      this.log('final_submission_simulated_no_network');
    }
    snapshot(corpusHash) {
      return {
        schema_version: '1.0', record_kind: 'synthetic_researcher_test', study_status: 'REVIEW_NOT_APPROVED',
        export_notice: 'Only invented researcher-testing responses. This browser prototype does not encrypt exported files; approved institutional storage is required before actual participant collection.',
        assignment_id: this.assignment.id,
        corpus_sha256: corpusHash, stage: this.stage, complete: this.records.length === 12 && this.ratings.length === 2,
        consent: this.consent, eligibility: this.eligibility, background: this.background,
        tasks: this.records, condition_ratings: this.ratings, practice_completion:this.practiceCompletion, feedback: this.feedback, events: this.events,
        submission_simulated: this.submissionSimulated
      };
    }
  }
  const api = {evidenceFor, preparedResponse, Session};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.StudyCore = api;
}(typeof window !== 'undefined' ? window : globalThis));
