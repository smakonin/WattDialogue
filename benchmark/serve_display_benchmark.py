# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Stephen Makonin
"""Synthetic, local-only measurement copy of the real WattDialogue display.

Adds stopwatch hooks and explicit experiment buttons to a copy of app.js. The
production renderer/fetch/cached-answer functions execute normally. No provider
transport, credentials, participant collector or hosted deployment is used.
"""
from pathlib import Path
from hashlib import sha256
import json
import os
import sys
import time
import argparse
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--port',type=int,default=8794)
args = parser.parse_args()
if not 1024 <= args.port <= 65535: parser.error('Use a port from 1024 to 65535')
OUT = args.output.resolve()
sys.path.insert(0, str(REPO))
from wattdialogue.config import Settings
from wattdialogue.service import WattDialogueService
from wattdialogue.server import DisplayServer, DisplayHandler, STATIC_FILES

PROBE = r'''
  // Synthetic engineering harness; no changes to the production source copy.
  const panel = element('section', 'panel'); panel.id = 'engineering-panel';
  panel.append(element('h2', '', 'Local engineering measurements'));
  panel.append(element('p', '', 'Instrumented replay display. Cloud transport is disabled. Two animation frames measure a visible-layout opportunity, not physical screen latency.'));
  const runButton = element('button', '', 'Run display timing'); runButton.type = 'button';
  const recoveryButton = element('button', '', 'Test cached display recovery'); recoveryButton.type = 'button';
  const resultText = element('pre'); resultText.id = 'engineering-results'; resultText.textContent = 'Ready after the recording has loaded.';
  panel.append(runButton, recoveryButton, resultText); document.body.prepend(panel);
  const frames = () => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const results = { timings: [], recovery: [], warmups: 3, browser: navigator.userAgent,
    viewport: { width: innerWidth, height: innerHeight, dpr: devicePixelRatio },
    method: 'native fetch/json and native renderer; performance.now; two rAF callbacks after DOM update; checks outside stopwatch; loopback no cloud' };
  async function saveResults() { await api('/__engineering/results', { method: 'POST', body: JSON.stringify(results) }); }
  function inspectFields(record) {
    const cards = Array.from($('answer-fields').children);
    const fields = record.returnedFields || [];
    const faithful = cards.length === fields.length && fields.every((f, index) => {
      const n = Number(cards[index]?.querySelector('.answer-field-value')?.firstChild?.nodeValue?.replaceAll(',', ''));
      const expected = f.unit === 'fraction' ? f.value * 100 : f.value;
      return typeof expected !== 'number' || Number.isFinite(n) && Math.abs(n - expected) <= 0.00500001;
    });
    const rect = $('answer-card').getBoundingClientRect();
    return { faithful_numeric_cards: faithful, returned_fields: fields.length,
      visible_layout: !$('answer-card').hidden && rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < innerHeight,
      document_visible: document.visibilityState === 'visible',
      answer_mode: $('answer-mode').textContent, freshness: $('answer-freshness').textContent };
  }
  async function measuredAsk(question, warmup = false) {
    if (state.busy || !state.summary) throw new Error('Recording is not ready');
    const record = { question_class: /compare/i.test(question) ? 'comparison' : /appliance/i.test(question) ? 'component' : 'meter',
      warmup, cached: state.cached, home: state.home, block: state.block, start_ms: performance.now() };
    engineering.current = record;
    await ask(question);
    $('answer-card').scrollIntoView({ block: 'center', behavior: 'instant' });
    await frames();
    const end = performance.now();
    record.two_frame_ms = end - record.start_ms;
    Object.assign(record, inspectFields(record));
    delete record.returnedFields; delete record.start_ms;
    engineering.current = null;
    if (!warmup) results.timings.push(record);
    return record;
  }
  runButton.addEventListener('click', async () => {
    runButton.disabled = recoveryButton.disabled = true;
    try {
      results.timings = [];
      const questions = ['How much electricity was measured?', 'What is appliance 1?', 'Compare the two periods.'];
      for (const question of questions) await measuredAsk(question, true);
      for (let i = 0; i < 30; i++) { await measuredAsk(questions[i % 3]); resultText.textContent = 'Completed ' + (i + 1) + '/30 visible-layout measurements'; }
      await saveResults(); resultText.textContent = JSON.stringify({ measurements: results.timings.length,
        numeric_cards_passed: results.timings.filter(v => v.faithful_numeric_cards).length,
        visible_passed: results.timings.filter(v => v.visible_layout && v.document_visible).length,
        details_saved: true }, null, 2); panel.scrollIntoView({ block: 'start', behavior: 'instant' });
    } catch (error) { resultText.textContent = error.message; }
    finally { runButton.disabled = recoveryButton.disabled = false; engineering.current = null; }
  });
  recoveryButton.addEventListener('click', async () => {
    runButton.disabled = recoveryButton.disabled = true;
    try {
      results.recovery = [];
      for (let cycle = 0; cycle < 3; cycle++) {
        await loadSummary(); const baseline = state.summary.total_energy_kwh;
        await api('/__engineering/control', { method: 'POST', body: JSON.stringify({ outage: true }) });
        await loadSummary();
        const cached = state.cached && /Cached/.test($('summary-freshness').textContent) && /Current activity/.test($('summary-warning').textContent);
        const renameBlocked = document.querySelectorAll('.rename-load-button, .candidate-button').length === 0;
        const query = await measuredAsk('How much electricity was measured?');
        const outage = { cycle: cycle + 1, phase: 'HTTP 503 outage', cache_marked: cached,
          rename_blocked: renameBlocked, cached_value_retained: state.summary.total_energy_kwh === baseline,
          stale_answer_warning: /stale/i.test(query.freshness), no_query_http: query.request_ms == null,
          numeric_cards_faithful: query.faithful_numeric_cards, visible: query.visible_layout && query.document_visible };
        outage.passed = Object.entries(outage).filter(([k]) => !['cycle', 'phase'].includes(k)).every(([, v]) => v === true);
        results.recovery.push(outage);
        await api('/__engineering/control', { method: 'POST', body: JSON.stringify({ outage: false }) });
        await loadSummary(); const restored = !state.cached && !/Cached/.test($('summary-freshness').textContent);
        const fresh = await measuredAsk('How much electricity was measured?');
        const recovered = { cycle: cycle + 1, phase: 'restored', cache_flag_cleared: restored,
          value_retained: state.summary.total_energy_kwh === baseline, local_http_resumed: fresh.request_ms > 0,
          stale_warning_cleared: !/stale/i.test(fresh.freshness), numeric_cards_faithful: fresh.faithful_numeric_cards,
          visible: fresh.visible_layout && fresh.document_visible };
        recovered.passed = Object.entries(recovered).filter(([k]) => !['cycle', 'phase'].includes(k)).every(([, v]) => v === true);
        results.recovery.push(recovered);
      }
      await saveResults(); resultText.textContent = JSON.stringify({ display_recovery_checks: results.recovery.length,
        passed: results.recovery.filter(v => v.passed).length, details_saved: true }, null, 2);
      panel.scrollIntoView({ block: 'start', behavior: 'instant' });
    } catch (error) { resultText.textContent = error.message; }
    finally {
      await api('/__engineering/control', { method: 'POST', body: JSON.stringify({ outage: false }) });
      runButton.disabled = recoveryButton.disabled = false; engineering.current = null;
    }
  });
'''

def prepare():
    OUT.mkdir(parents=True,exist_ok=False)
    app = (REPO/"web/app.js").read_text()
    original = app
    app = app.replace("  const state =", "  const engineering = { current: null };\n  const state =", 1)
    app = app.replace("    let response;\n    try { response = await fetch", "    const testStart = performance.now();\n    let response;\n    try { response = await fetch", 1)
    app = app.replace("    let data;\n    try { data = await response.json(); }", "    const testHeaders = performance.now();\n    let data;\n    try { data = await response.json(); }", 1)
    app = app.replace("    if (!response.ok) throw", "    if (path === '/api/query' && engineering.current) { engineering.current.request_ms = performance.now() - testStart; engineering.current.headers_ms = testHeaders - testStart; engineering.current.decode_ms = performance.now() - testHeaders; }\n    if (!response.ok) throw", 1)
    app = app.replace("  function renderAnswer(data, question) {", "  function renderAnswer(data, question) {\n    const testRender = performance.now();", 1)
    app = app.replace("    announce('Answer ready. ' + residentText(data.answer || 'No explanation supplied.'));", "    announce('Answer ready. ' + residentText(data.answer || 'No explanation supplied.'));\n    if (engineering.current) { engineering.current.dom_ms = performance.now() - testRender; engineering.current.returnedFields = data.fields || []; }", 1)
    app = app.replace("  initialize();", PROBE+"\n  initialize();", 1)
    (OUT/"app.js").write_text(app)
    for name in ("index.html", "style.css", "favicon.svg"):
        if (REPO/"web"/name).is_file(): (OUT/name).write_bytes((REPO/"web"/name).read_bytes())
    protocol = {"version": "display-measurement-v1", "ordinary_queries": 30, "warmups": 3,
                "question_classes": ["meter", "component", "comparison"], "outage_recovery_cycles": 3,
                "provider_network_requests": 0, "interface": "instrumented copy, production app unchanged",
                "paint_limit": "two animation-frame callbacks with visible document and nonzero intersecting answer layout; no physical display or first-paint timestamp",
                "production_app_sha256": sha256(original.encode()).hexdigest(),
                "instrumented_app_sha256": sha256(app.encode()).hexdigest(),
                "server_runner_sha256": sha256(Path(__file__).read_bytes()).hexdigest()}
    (OUT/"PROTOCOL.json").write_text(json.dumps(protocol, indent=2)+"\n")

class Handler(DisplayHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path in STATIC_FILES:
            if not self._host_ok(): return self._json(403, {"error": "Loopback only"})
            self._session()
            name = STATIC_FILES[path]
            mime = {"html": "text/html", "js": "application/javascript", "css": "text/css", "svg": "image/svg+xml"}[name.rsplit('.',1)[1]]
            if not (OUT/name).is_file(): return self._json(404, {"error": "No such static file"})
            self._headers(200, mime+"; charset=utf-8")
            return self.wfile.write((OUT/name).read_bytes())
        if self.server.outage and path.startswith('/api/'):
            return self._json(503, {"error": "Injected local HTTP outage"})
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path.startswith('/__engineering/'):
            if not self._host_ok(): return self._json(403, {"error": "Loopback only"})
            session = self._session()
            import secrets
            if not secrets.compare_digest(self.headers.get('X-WattDialogue-Token',''),session['csrf_token']):
                return self._json(403, {"error": "Session token required"})
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length < 200000: return self._json(400, {"error": "Invalid size"})
            payload = json.loads(self.rfile.read(length))
            if path == '/__engineering/control':
                self.server.outage = payload.get('outage') is True
            elif path == '/__engineering/results':
                (OUT/'BROWSER_RESULTS.json').write_text(json.dumps(payload, indent=2)+'\n')
            else: return self._json(404, {"error": "No such engineering control"})
            return self._json(200, {"ok": True})
        if self.server.outage and path.startswith('/api/'):
            return self._json(503, {"error": "Injected local HTTP outage"})
        return super().do_POST()

if __name__ == '__main__':
    for key in ('OPENAI_API_KEY','OPENAI_API_KEY_BACKUP'): os.environ[key]=''
    prepare()
    (OUT/'empty.env').write_text('')
    def forbidden(*_): raise RuntimeError('Provider transport disabled')
    service = WattDialogueService(
        env_file=OUT/'empty.env',registry_path=OUT/'unused-labels.json',transport=forbidden)
    service.agent.settings_loader=lambda: Settings()
    server = DisplayServer(('127.0.0.1',args.port),service)
    server.RequestHandlerClass=Handler; server.outage=False
    print(f'Synthetic display timing harness http://127.0.0.1:{args.port}/',flush=True)
    try: server.serve_forever()
    finally: server.server_close()
