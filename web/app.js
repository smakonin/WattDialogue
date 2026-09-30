// SPDX-License-Identifier: GPL-3.0-only
// Copyright (C) 2026 Stephen Makonin
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const state = { home: 'R1Hz', block: '', summary: null, status: null, token: null, busy: false, epoch: 0, cached: false, labelTarget: null, showAll: false };
  const numberFormat = new Intl.NumberFormat('en-CA', { maximumFractionDigits: 2 });
  const cachePrefix = 'wattdialogue:demo:v2:';
  const sourceLabels = { meter: 'Meter reading', estimate: 'NILM estimate', nilm_estimate: 'NILM estimate', derived: 'Calculated from evidence', illustrative: 'Illustrative only' };
  const metricLabels = { total_energy_kwh: 'Measured electricity', measured_energy_kwh: 'Measured electricity', estimated_energy_kwh: 'Estimated load electricity', unexplained_energy_kwh: 'Unexplained electricity', residual_energy_kwh: 'Signed estimate difference', coverage: 'Data coverage', coverage_fraction: 'Data coverage' };

  function element(tag, className, content) { const node = document.createElement(tag); if (className) node.className = className; if (content !== undefined) node.textContent = String(content); return node; }
  function finite(value) { if (value === null || value === undefined || value === '') return null; const n = Number(value); return Number.isFinite(n) ? n : null; }
  function first(...values) { return values.find(value => value !== undefined && value !== null); }
  function asArray(value) { return Array.isArray(value) ? value : []; }
  function displayNumber(value) { const n = finite(value); return n === null ? '—' : numberFormat.format(n); }
  function humanStatus(value) { return String(value || 'unknown').replace(/[_-]/g, ' '); }
  function sourceKind(...sources) {
    for (const source of sources) {
      if (!source) continue;
      if (source.synthetic_fixture === true) return 'synthetic';
      const kind = String(source.input_kind || '').toLowerCase();
      if (/synthetic|fixture/.test(kind)) return 'synthetic';
      if (/archive|recorded|replay/.test(kind)) return 'archive';
      const description = typeof source.data_source === 'string' ? source.data_source.toLowerCase() : '';
      if (/synthetic|generated fixture/.test(description)) return 'synthetic';
      if (/archive|recorded|hynilm replay/.test(description)) return 'archive';
      if (source.synthetic_fixture === false) return 'archive';
    }
    return 'unknown';
  }
  function currentSource() { return sourceKind(state.summary, state.status); }
  function sourceLabel(source) { if (currentSource() !== 'synthetic') return sourceLabels[source] || 'Source not supplied'; return ({ meter: 'Synthetic meter value', estimate: 'Synthetic estimate', nilm_estimate: 'Synthetic estimate', derived: 'Calculated from synthetic data', illustrative: 'Illustrative only' })[source] || 'Synthetic example'; }
  function renderSourceContext() {
    const kind = currentSource();
    const labels = first(state.summary?.household_labels, state.status?.household_labels, {});
    Array.from($('home-select').options).forEach((option, index) => { option.textContent = labels[option.value] || (kind === 'synthetic' ? 'Synthetic home ' + (index + 1) : kind === 'archive' ? 'Recorded home ' + (index + 1) + ' · ' + option.value : 'Demo home ' + (index + 1)); });
    const notice = $('data-source-notice'); notice.replaceChildren();
    const title = kind === 'synthetic' ? 'Wholly synthetic demo data. ' : kind === 'archive' ? 'Recorded home data. ' : 'Data source not yet identified. ';
    const detail = kind === 'synthetic' ? 'The example meter values and component estimates are generated fixtures, not records from a real home. No live meter is connected.' : kind === 'archive' ? 'This prototype replays archived HyNILM estimates. It is not connected to a live meter.' : 'Do not interpret these examples as real household measurements. This prototype is not connected to a live meter.';
    notice.append(element('strong', '', title), document.createTextNode(detail));
    $('home-select-label').textContent = kind === 'archive' ? 'Recorded household' : 'Demo household';
    $('block-select-label').textContent = kind === 'archive' ? 'Recording period' : 'Demo period';
    $('total-label').textContent = kind === 'synthetic' ? 'Example meter total' : kind === 'archive' ? 'Measured electricity' : 'Electricity total';
    $('estimate-source-chip').textContent = kind === 'synthetic' ? 'Synthetic estimates' : kind === 'archive' ? 'NILM estimates' : 'Estimates';
    $('intro-copy').textContent = kind === 'synthetic' ? 'Explore electricity use and estimated loads in a fictional home. Every displayed energy value is synthetic.' : kind === 'archive' ? 'Ask about electricity use, estimated appliances, or changes that fit the recorded household.' : 'Explore electricity use, estimated loads, and the limits of this demonstration.';
    $('footer-source').textContent = kind === 'synthetic' ? 'All energy values in this demo come from generated synthetic fixtures.' : kind === 'archive' ? 'Measured totals and estimated loads are shown separately.' : 'The source of displayed values must be identified with the evidence.';
  }
  function friendlyLoad(componentId) { const match = String(componentId ?? '').match(/^(?:component_|k)?(\d+)$/); return match ? 'Unidentified load ' + (Number(match[1]) + 1) : 'Unidentified load'; }
  function residentText(value) { return String(value ?? '').replace(/\b(?:estimated\s+(?:load|component)|anonymous\s+component|load|component)\s+component_(\d+)\b/gi, (_, index) => friendlyLoad('component_' + index)).replace(/\bcomponent_(\d+)\b/g, (_, index) => friendlyLoad('component_' + index)); }
  function date(value) { if (value === null || value === undefined || value === '') return null; const n = finite(value); const d = n === null ? new Date(value) : new Date(n < 1e12 ? n * 1000 : n); return Number.isNaN(d.getTime()) ? null : d; }
  function timeText(value) { const d = date(value); if (!d) return 'not supplied'; return new Intl.DateTimeFormat('en-CA', { timeZone: state.summary?.timezone || 'America/Vancouver', month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }).format(d); }
  function stringMessage(value) { if (typeof value === 'string') return value; return String(first(value?.message, value?.text, value?.description, value?.warning, 'Evidence needs review.')); }
  function announce(message) { $('activity-status').textContent = message; }
  function showMessage(id, message) { const node = $(id); node.textContent = message || ''; node.hidden = !message; }
  function readCache(key) { try { return JSON.parse(localStorage.getItem(cachePrefix + currentSource() + ':' + key)); } catch { return null; } }
  function writeCache(key, value) { try { localStorage.setItem(cachePrefix + currentSource() + ':' + key, JSON.stringify({ value, cached_at: Date.now() })); } catch { /* A restricted display can operate without browser storage. */ } }

  async function api(path, options = {}) {
    const headers = { Accept: 'application/json', ...options.headers };
    if (options.method && options.method !== 'GET') {
      if (!state.token) throw new Error('The local service is not connected. Please try again when it is available.');
      headers['Content-Type'] = 'application/json';
      headers['X-WattDialogue-Token'] = state.token;
    }
    let response;
    try { response = await fetch(path, { ...options, headers, credentials: 'same-origin', cache: 'no-store' }); }
    catch { const error = new Error('The local display service is unavailable.'); error.network = true; throw error; }
    let data;
    try { data = await response.json(); }
    catch { throw new Error('The local service returned a response this display could not read.'); }
    if (!response.ok) throw new Error(String(first(data?.error?.message, data?.error, data?.message, 'The request could not be completed.')));
    return data;
  }

  function updateCloudControls() {
    const available = state.status?.api_available === true;
    $('cloud-consent').disabled = !available || state.busy;
    if (!available) $('cloud-consent').checked = false;
    const cloud = available && $('cloud-consent').checked;
    $('mode-badge').replaceChildren(element('span', 'status-dot'), document.createTextNode(cloud ? 'Cloud AI enabled' : 'Local mode'));
    $('api-availability').textContent = available ? 'AI access is provided by the server. Your consent applies only to this session; turn this off to return to local explanations.' : 'Cloud AI is not configured on this server. You can still read the recording and use local explanations.';
  }

  async function getStatus() {
    const status = await api('/api/status');
    state.status = status;
    state.token = status.csrf_token || null;
    if (['R1Hz', 'AMPds2'].includes(status.home_scope)) { state.home = status.home_scope; $('home-select').value = state.home; }
    renderSourceContext();
    updateCloudControls();
    return status;
  }

  function normalizedSummary(raw) {
    const summary = raw.summary || raw;
    const components = asArray(first(summary.components, summary.loads)).map(component => ({
      ...component,
      component_id: first(component.component_id, component.id),
      energy_kwh: finite(first(component.energy_kwh, component.estimated_energy_kwh, component.kwh)),
      evidence_id: first(component.evidence_id, component.evidence_ids?.[0]),
      model_version: first(component.model_version, summary.model_version),
      confirmation_as_of: first(component.confirmation_as_of, summary.freshness?.as_of, summary.as_of),
      label_status: first(component.label_status, component.status, 'unknown')
    })).sort((a, b) => (b.energy_kwh ?? -Infinity) - (a.energy_kwh ?? -Infinity));
    return { ...summary, components, total_energy_kwh: finite(first(summary.total_energy_kwh, summary.measured_energy_kwh, summary.aggregate_energy_kwh)), coverage: first(summary.coverage, summary.coverage_fraction, summary.coverage_percent), observation_start: first(summary.observation_start, summary.start, summary.freshness?.observation_start), observation_end: first(summary.observation_end, summary.end, summary.freshness?.observation_end), available_time: first(summary.available_time, summary.available_at, summary.freshness?.available_time, summary.freshness?.available_at) };
  }

  function renderSummary(raw, cachedAt = null) {
    const summary = normalizedSummary(raw);
    state.summary = summary;
    state.cached = cachedAt !== null;
    renderSourceContext();
    const synthetic = currentSource() === 'synthetic';
    $('boundary').textContent = (synthetic ? 'Example boundary: ' : 'Meter boundary: ') + (summary.boundary || summary.measurement_boundary || (synthetic ? 'Synthetic household fixture.' : 'Not supplied.'));
    $('total-energy').textContent = displayNumber(summary.total_energy_kwh);
    $('recording-range').textContent = summary.observation_start != null || summary.observation_end != null ? timeText(summary.observation_start) + ' — ' + timeText(summary.observation_end) : 'Recording interval is not supplied.';
    const coverage = finite(typeof summary.coverage === 'object' ? first(summary.coverage.fraction, summary.coverage.percent) : summary.coverage);
    $('coverage').textContent = coverage === null ? 'Not supplied' : displayNumber(coverage <= 1 ? coverage * 100 : coverage) + '%';
    $('summary-freshness').textContent = cachedAt ? 'Cached ' + (synthetic ? 'synthetic demo' : 'evidence') + ' summary saved ' + timeText(cachedAt) + '. Current service availability is unknown.' : (synthetic ? 'Synthetic example evidence available ' : 'Recorded evidence available ') + timeText(summary.available_time) + (synthetic ? '. Example timestamps, not live or real household readings.' : '. Historical replay, not current appliance activity.');
    const unexplained = finite(first(summary.unexplained_energy_kwh, summary.unexplained_kwh));
    const over = finite(summary.overallocated_energy_kwh);
    $('residual').textContent = unexplained !== null ? displayNumber(unexplained) + ' kWh of ' + (synthetic ? 'example meter electricity' : 'measured electricity') + ' is unexplained by the estimates.' : 'Unexplained consumption is not supplied for this summary.';
    if (over !== null && over > 0) $('residual').textContent += ' The estimates also run above meter readings in some intervals, by ' + displayNumber(over) + ' kWh in total.';
    const warnings = asArray(summary.warnings).map(stringMessage);
    if (coverage !== null && (coverage <= 1 ? coverage : coverage / 100) < 1) warnings.unshift('This recording is incomplete. Missing intervals are not treated as zero consumption.');
    if (cachedAt) warnings.unshift('Cached evidence only. Current activity cannot be inferred from this recording.');
    showMessage('summary-warning', [...new Set(warnings)].join(' '));
    renderLoads();
  }

  function renderLoads() {
    const list = $('load-list'); list.replaceChildren();
    const all = state.summary?.components || [];
    const shown = state.showAll ? all : all.slice(0, 5);
    if (!shown.length) { list.append(element('li', 'empty-state', 'No component estimates are available in this interval.')); return; }
    const maximum = Math.max(...all.map(item => item.energy_kwh || 0), 0);
    for (const component of shown) {
      const row = element('li');
      const top = element('div', 'load-topline');
      const name = element('div', 'load-name');
      const status = humanStatus(component.label_status);
      const confirmed = /confirmed|verified/.test(status);
      const displayName = confirmed && component.label ? residentText(component.label) : friendlyLoad(component.component_id);
      const title = element('span', 'load-title', displayName);
      if (component.component_id !== undefined && component.evidence_id && component.model_version && !state.cached) {
        const button = element('button', 'rename-load-button', 'rename'); button.type = 'button';
        button.setAttribute('aria-label', 'Rename ' + displayName);
        button.disabled = state.busy;
        button.addEventListener('click', () => openLabel(component));
        title.append(document.createTextNode(' ('), button, document.createTextNode(')'));
      }
      name.append(title);
      const annotationStatus = state.status?.prototype && /occupant confirmed/.test(status) ? (currentSource() === 'synthetic' ? 'demo annotation' : 'operator-confirmed replay annotation') : status;
      name.append(element('span', 'load-status', confirmed ? annotationStatus + ' · consumption estimated' : 'Appliance name not confirmed'));
      top.append(name, element('span', 'load-value', displayNumber(component.energy_kwh) + ' kWh'));
      const track = element('div', 'load-track'); track.setAttribute('aria-hidden', 'true');
      const fill = element('div', 'load-fill'); fill.style.width = (maximum > 0 ? Math.max(0, component.energy_kwh || 0) / maximum * 100 : 0) + '%'; track.append(fill);
      row.append(top, track);
      list.append(row);
    }
    if (all.length > 5) { const row = element('li'); const button = element('button', 'name-load-button', state.showAll ? 'Show fewer loads' : 'Show all ' + all.length + ' estimated loads'); button.type = 'button'; button.setAttribute('aria-expanded', String(state.showAll)); button.addEventListener('click', () => { state.showAll = !state.showAll; renderLoads(); }); row.append(button); list.append(row); }
  }

  function clearAnswer() { $('answer-card').hidden = true; $('answer-text').textContent = ''; $('answer-fields').replaceChildren(); $('label-candidates').replaceChildren(); showMessage('connection-message', ''); }

  async function loadBlocks() {
    const epoch = ++state.epoch;
    state.summary = null; state.showAll = false; clearAnswer();
    renderSourceContext();
    $('block-select').disabled = true;
    $('block-select').replaceChildren(new Option('Loading periods…', ''));
    try {
      const raw = await api('/api/blocks?home=' + encodeURIComponent(state.home));
      if (epoch !== state.epoch) return;
      const blocks = asArray(Array.isArray(raw) ? raw : raw.blocks);
      writeCache(state.home + ':blocks', blocks);
      populateBlocks(blocks);
      await loadSummary();
    } catch (error) { if (epoch !== state.epoch) return; const cached = readCache(state.home + ':blocks'); if (cached?.value?.length) { populateBlocks(cached.value); await loadSummary(); } else { $('block-select').replaceChildren(new Option('No recording periods available', '')); showMessage('summary-warning', error.message); $('total-energy').textContent = '—'; $('recording-range').textContent = 'No recording has been loaded.'; $('load-list').replaceChildren(element('li', 'empty-state', 'No evidence is available.')); } }
  }

  function populateBlocks(blocks) {
    const select = $('block-select'); select.replaceChildren();
    blocks.forEach(block => { const id = typeof block === 'string' ? block : first(block.block_id, block.id); if (id === undefined || id === null) return; const label = typeof block === 'string' ? block : first(block.label, block.name, 'Recording ' + id); select.append(new Option(label, String(id))); });
    if (!select.options.length) { select.append(new Option('No recording periods available', '')); select.disabled = true; state.block = ''; return; }
    state.block = select.options[0].value; select.value = state.block; select.disabled = state.busy;
  }

  async function loadSummary() {
    if (!state.block) return;
    const epoch = ++state.epoch; const home = state.home; const block = state.block;
    clearAnswer(); showMessage('summary-warning', ''); announce('Loading recorded electricity evidence.');
    try {
      const data = await api('/api/summary?home=' + encodeURIComponent(home) + '&block_id=' + encodeURIComponent(block));
      if (epoch !== state.epoch) return;
      renderSummary(data); writeCache(home + ':' + block, data); announce('Recorded electricity overview loaded.');
    } catch (error) { if (epoch !== state.epoch) return; const cached = readCache(home + ':' + block); if (cached?.value) { renderSummary(cached.value, cached.cached_at); showMessage('connection-message', 'The local service is unavailable. You can review this cached summary; new AI requests and label confirmations are unavailable.'); } else { state.summary = null; $('total-energy').textContent = '—'; $('coverage').textContent = '—'; $('recording-range').textContent = 'This recording could not be loaded.'; $('summary-freshness').textContent = 'No evidence available.'; $('load-list').replaceChildren(element('li', 'empty-state', 'No estimates are available.')); showMessage('summary-warning', error.message); } announce(error.message); }
  }

  function setBusy(busy) {
    state.busy = busy;
    $('ask-button').disabled = busy; $('ask-button').replaceChildren(document.createTextNode(busy ? 'Asking…' : 'Ask '), ...(busy ? [] : [element('span', '', '→')]));
    $('home-select').disabled = busy; $('block-select').disabled = busy || !state.block;
    document.querySelectorAll('[data-question], .name-load-button, .rename-load-button, .candidate-button').forEach(button => { button.disabled = busy; });
    updateCloudControls();
    $('question-form').setAttribute('aria-busy', String(busy));
  }

  function renderAnswer(data, question) {
    if (data.display_summary) { renderSummary(data.display_summary); writeCache(state.home + ':' + state.block, data.display_summary); }
    $('asked-question').textContent = residentText(question);
    const synthetic = currentSource() === 'synthetic';
    $('answer-title').textContent = synthetic ? "Here's what the synthetic example shows" : "Here's what the recording tells us";
    $('answer-source-note').textContent = synthetic ? 'Synthetic fixture: these generated values do not describe an actual household or constitute experiment results.' : currentSource() === 'archive' ? 'Archived household evidence. This is a replay, not a live meter response.' : 'The source is not verified. Do not assume these values are real household measurements.';
    $('answer-mode').textContent = data.mode === 'openai' ? 'Cloud AI explanation · values supplied by evidence tools' : 'Local explanation · no cloud AI request';
    $('answer-text').textContent = residentText(data.answer || 'The service did not return an explanation.');
    const fields = $('answer-fields'); fields.replaceChildren();
    for (const field of asArray(data.fields)) {
      const card = element('div', 'answer-field'); card.append(element('span', 'answer-field-label', residentText(first(field.humanlabel, field.human_label, field.label, metricLabels[field.metric], field.metric, 'Evidence value'))));
      const isFraction = field.unit === 'fraction';
      const numeric = finite(field.value);
      const shownValue = isFraction && numeric !== null ? displayNumber(numeric * 100) : typeof field.value === 'number' ? displayNumber(field.value) : residentText(field.value ?? 'Not supplied');
      const value = element('span', 'answer-field-value', shownValue);
      const shownUnit = isFraction ? '%' : field.unit;
      if (shownUnit) value.append(element('span', 'answer-field-unit', shownUnit));
      card.append(value, element('span', 'source-chip ' + (field.source === 'meter' ? 'meter' : field.source === 'illustrative' ? 'illustrative' : 'estimate'), sourceLabel(field.source))); fields.append(card);
    }
    const warnings = $('answer-warnings'); warnings.replaceChildren();
    asArray(data.warnings).forEach(warning => warnings.append(element('p', '', stringMessage(warning))));
    const evidence = $('evidence-list'); evidence.replaceChildren();
    asArray(data.evidence).forEach(item => { const labelStatus = state.status?.prototype && item?.label_status === 'occupant-confirmed' ? (synthetic ? 'demo annotation' : 'operator-confirmed replay annotation') : humanStatus(item?.label_status); const text = typeof item === 'string' ? item : [first(item.description, item.summary, item.label, item.type), first(item.evidence_id, item.id, item.source_ref), item.label_status ? 'Label: ' + labelStatus : null].filter(Boolean).join(' · '); if (text) evidence.append(element('li', '', text)); });
    if (!evidence.children.length) asArray(data.evidence_ids).forEach(id => evidence.append(element('li', '', 'Recorded evidence: ' + id)));
    if (!evidence.children.length) evidence.append(element('li', '', 'No source reference was supplied. Treat this response cautiously.'));
    const fresh = data.freshness || {};
    $('answer-freshness').textContent = [fresh.observation_end != null ? 'Observation ends ' + timeText(fresh.observation_end) : null, first(fresh.available_time, fresh.available_at) != null ? 'Evidence available ' + timeText(first(fresh.available_time, fresh.available_at)) : null, fresh.stale ? 'Evidence is marked stale.' : null, fresh.partial ? 'Partial evidence.' : null, synthetic ? 'This answer concerns generated synthetic examples, not a real household.' : 'This answer concerns non-live replay evidence.'].filter(Boolean).join(' ');
    renderCandidates(data.label_candidates);
    $('answer-card').hidden = false;
    announce('Answer ready. ' + residentText(data.answer || 'No explanation supplied.'));
  }

  function renderCandidates(candidates) {
    const area = $('label-candidates'); area.replaceChildren();
    for (const entry of asArray(candidates)) {
      const component = state.summary?.components.find(item => String(item.component_id) === String(entry.component_id));
      const group = element('div'); group.append(element('h3', '', 'Possible names for ' + friendlyLoad(entry.component_id).toLowerCase()), element('p', '', residentText(first(entry.reason, entry.explanation, 'These are suggestions. Appliance identity is not verified.'))));
      const options = asArray(entry.candidates).length ? entry.candidates : [entry];
      options.forEach(option => { const name = typeof option === 'string' ? option : first(option.label, option.appliance_class, option.name, option.class); if (!name) return; const target = { ...component, ...entry, component_id: first(entry.component_id, component?.component_id), evidence_id: first(entry.confirmation_evidence_id, component?.evidence_id), model_version: first(entry.model_version, component?.model_version), confirmation_as_of: first(entry.confirmation_as_of, component?.confirmation_as_of, state.summary?.freshness?.as_of) }; if (target.component_id !== undefined && target.evidence_id && target.model_version && !state.cached) { const button = element('button', 'candidate-button', 'Check “' + name + '”'); button.type = 'button'; button.addEventListener('click', () => openLabel(target, name)); group.append(button); } else { group.append(element('p', '', 'Possible: ' + name + '. Confirmation evidence is not yet available.')); } });
      area.append(group);
    }
  }

  function cachedAnswer(question) {
    const summary = state.summary;
    if (!summary || !state.cached) return null;
    const top = summary.components[0];
    const total = summary.total_energy_kwh;
    const answer = /most|largest|highest/i.test(question) && top ? 'The largest estimated load in the cached recording is load ' + top.component_id + ', at ' + displayNumber(top.energy_kwh) + ' kWh. Its appliance identity may be unconfirmed.' : 'The cached recording contains ' + displayNumber(total) + ' kWh of measured electricity. You can review its estimated loads in the overview. New comparisons, appliance suggestions and current-activity answers need the local service.';
    return { answer, mode: 'local', fields: [{ label: 'Cached measured electricity', value: total, unit: 'kWh', source: 'meter' }], warnings: ['Cached historical evidence only. No live meter or cloud AI request is available.'], evidence_ids: asArray(summary.evidence_ids), freshness: { observation_end: summary.observation_end, available_time: summary.available_time, stale: true } };
  }

  async function ask(question) {
    question = question.trim();
    if (!question || state.busy) { if (!question) $('question').focus(); return; }
    if (!state.block || !state.summary) { showMessage('connection-message', 'Load a recording before asking about its electricity use.'); return; }
    $('question').value = question; clearAnswer(); setBusy(true); announce('Finding the recorded evidence for your question.');
    const cloud = state.status?.api_available === true && $('cloud-consent').checked;
    try {
      if (state.cached) { const answer = cachedAnswer(question); if (answer) renderAnswer(answer, question); return; }
      const data = await api('/api/query', { method: 'POST', body: JSON.stringify({ question, home: state.home, block_id: state.block, mode: cloud ? 'openai' : 'local', consent: cloud }) });
      renderAnswer(data, question);
    } catch (error) { showMessage('connection-message', error.message + ' No new answer was produced. Your recording remains available.'); announce(error.message); }
    finally { setBusy(false); }
  }

  function openLabel(component, proposed = '') {
    state.labelTarget = component;
    const synthetic = currentSource() === 'synthetic';
    $('label-dialog-title').textContent = synthetic ? 'Annotate this synthetic load' : 'Annotate this recorded load';
    $('label-dialog-help').textContent = synthetic ? 'This load comes from generated synthetic data. Naming it creates a demo annotation; it does not identify an appliance in a real home.' : 'A suggested name is a possibility. This prototype records an operator-confirmed replay annotation, not a claim that a resident verified the physical appliance. Its electricity use remains a NILM estimate.';
    $('label-annotation-text').textContent = synthetic ? 'Record this name as a synthetic demo annotation.' : 'Record this name as an operator-confirmed replay annotation.';
    $('save-label-button').textContent = synthetic ? 'Record demo name' : 'Record replay name';
    $('dialog-load').textContent = friendlyLoad(component.component_id) + ' · ' + displayNumber(component.energy_kwh) + ' kWh in the selected ' + (synthetic ? 'demo' : 'recording') + ' period';
    $('appliance-name').value = proposed || (component.label && component.label !== component.component_id ? component.label : '');
    $('label-confirmation').checked = false; showMessage('label-error', '');
    $('label-dialog').showModal(); $('appliance-name').focus();
  }

  $('question-form').addEventListener('submit', event => { event.preventDefault(); ask($('question').value); });
  $('question').addEventListener('keydown', event => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); ask($('question').value); } });
  document.querySelectorAll('[data-question]').forEach(button => button.addEventListener('click', () => ask(button.dataset.question)));
  $('home-select').addEventListener('change', async () => {
    const selected = $('home-select').value; const previous = state.home; setBusy(true);
    try { const result = await api('/api/home', { method: 'POST', body: JSON.stringify({ home: selected }) }); if (result.csrf_token) state.token = result.csrf_token; state.home = selected; state.block = ''; await loadBlocks(); }
    catch (error) { $('home-select').value = previous; showMessage('connection-message', error.message + ' The household selection was not changed.'); }
    finally { setBusy(false); }
  });
  $('block-select').addEventListener('change', async () => { state.block = $('block-select').value; state.showAll = false; setBusy(true); await loadSummary(); setBusy(false); });
  $('cloud-settings-button').addEventListener('click', async () => { const open = $('cloud-settings').hidden; $('cloud-settings').hidden = !open; $('cloud-settings-button').setAttribute('aria-expanded', String(open)); if (open) { try { await getStatus(); } catch { state.status = { ...state.status, api_available: false }; updateCloudControls(); $('api-availability').textContent = 'The local service is unavailable. Cloud AI requests cannot be sent.'; } } });
  $('cloud-consent').addEventListener('change', () => { updateCloudControls(); announce($('cloud-consent').checked ? 'Cloud AI enabled for new questions in this session.' : 'Local mode enabled. New questions will not be sent to cloud AI.'); });
  $('close-label-dialog').addEventListener('click', () => $('label-dialog').close());
  $('label-form').addEventListener('submit', async event => {
    event.preventDefault(); const target = state.labelTarget; const label = $('appliance-name').value.trim();
    if (!target || !label || !$('label-confirmation').checked) return;
    setBusy(true); $('save-label-button').disabled = true; showMessage('label-error', '');
    try { const payload = { home: state.home, block_id: state.block, component_id: target.component_id, label, evidence_id: target.evidence_id, model_version: target.model_version, confirm: true }; if (target.confirmation_as_of != null) payload.as_of = target.confirmation_as_of; await api('/api/labels', { method: 'POST', body: JSON.stringify(payload) }); $('label-dialog').close(); await loadSummary(); announce((currentSource() === 'synthetic' ? 'Synthetic demo annotation' : 'Operator-confirmed replay annotation') + ' recorded separately from the component estimates. Physical identity is not independently verified.'); }
    catch (error) { showMessage('label-error', error.message); }
    finally { $('save-label-button').disabled = false; setBusy(false); }
  });

  async function initialize() {
    $('cloud-consent').checked = false; setBusy(true);
    try { await getStatus(); await loadBlocks(); }
    catch (error) { showMessage('connection-message', error.message + ' Start or reconnect the local prototype service to load recorded evidence.'); updateCloudControls(); }
    finally { setBusy(false); }
  }
  initialize();
})();
