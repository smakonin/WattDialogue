"""Produce a self-contained offline HTML and a REVIEW hash manifest."""
from pathlib import Path
from hashlib import sha256
import base64
import json
import re

ROOT = Path(__file__).resolve().parent
corpus_bytes = (ROOT / 'corpus.json').read_bytes()
corpus = json.loads(corpus_bytes)
orientation = json.loads((ROOT/'orientation-and-help.json').read_text())
canonical = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
meta = {
    'status': 'REVIEW, not an approved participant-study freeze',
    'corpus_sha256': sha256(corpus_bytes).hexdigest(),
    'card_evidence_sha256': {c['id']: sha256(canonical(c['evidence'])).hexdigest() for c in corpus['cards']},
    'protocol_appendix_sha256': corpus['appendix_sha256']
}
protocol_path = ROOT.parent / 'WattDialogue_Participant_Protocol_and_Ethics_Draft.tex'
protocol_text = protocol_path.read_text()
consent_body = protocol_text.split('\\section{Study information and consent form draft}')[1].split('\\section{Questionnaire and optional written feedback}')[0]
def plain(text):
    text = re.sub(r'\\href\{[^}]*\}\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\textbf\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\\\(?:\[[^]]*\])?', '\n', text)
    return text.replace('\\&', '&').replace('--', '–').replace('``', '“').replace("''", '”').strip()
parts = re.split(r'\\subsection\*\{([^}]*)\}', consent_body)
metadata = [plain(line) for line in parts[0].splitlines() if line.startswith(r'\textbf{') and any(line.startswith(r'\textbf{' + label) for label in ['Study title:', 'Research Ethics Study Number:', 'Principal Investigator:', 'Research team:'])]
consent = {'version': 'v0.2-20260930-REVIEW', 'status':'REVIEW, not issued or approved', 'metadata': metadata, 'sections':[{'heading':parts[i], 'paragraphs':[plain(p) for p in re.split(r'\n\s*\n',parts[i+1]) if p.strip() and p.strip() != r'\newpage']} for i in range(1,len(parts),2)]}
feedback = ['Which format helped you most, and why? No preference is acceptable.', 'When, if ever, could you not tell whether a name or a number was certain?', 'Did wording, text size, layout, touch targets or input controls make a task harder?', 'If a utility supplied a display without needing your own device or Internet service, what might still make it difficult to use? Discuss generally, without private financial details.', 'What should the display explain before suggesting a change that could affect comfort?']
data_script = 'window.WATT_STUDY_CORPUS = ' + json.dumps(corpus, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/') + ';\n'
data_script += 'window.WATT_REVIEW_FREEZE = ' + json.dumps(meta, ensure_ascii=False, separators=(',', ':')) + ';\n'
data_script += 'window.WATT_CONSENT_REVIEW = ' + json.dumps(consent, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/') + ';\n'
data_script += 'window.WATT_FEEDBACK_QUESTIONS = ' + json.dumps(feedback, ensure_ascii=False).replace('</', '<\\/') + ';\n'
data_script += 'window.WATT_ORIENTATION = ' + json.dumps(orientation, ensure_ascii=False).replace('</', '<\\/') + ';\n'
data_script += 'function freezeEvidence(value){if(value && typeof value === "object"){Object.values(value).forEach(freezeEvidence);Object.freeze(value);}}\nfreezeEvidence(window.WATT_STUDY_CORPUS);freezeEvidence(window.WATT_REVIEW_FREEZE);freezeEvidence(window.WATT_ORIENTATION);'
scripts = [data_script, (ROOT / 'study-core.js').read_text(), (ROOT / 'app.js').read_text()]
css = (ROOT / 'styles.css').read_text()
csp_hash = lambda value: "'sha256-" + base64.b64encode(sha256(value.encode()).digest()).decode() + "'"
csp = "default-src 'none'; connect-src 'none'; script-src " + ' '.join(csp_hash(s) for s in scripts) + "; style-src " + csp_hash(css) + "; img-src 'none'; font-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"
html = '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
html += '<meta http-equiv="Content-Security-Policy" content="' + csp + '"><title>WattDialogue · anonymous web study REVIEW</title><style>' + css + '</style></head><body>'
html += '<div class="review-banner">STUDY REVIEW · invented examples · researcher testing only · ethics approval pending</div>'
html += '<header class="masthead"><div class="brand">WattDialogue<small>Anonymous web flow · local REVIEW</small></div><div class="text-tools"><span>Text size</span><button id="smaller-text" aria-label="Smaller text">A−</button><span id="text-scale-label">100%</span><button id="larger-text" aria-label="Larger text">A+</button></div></header>'
html += '<main id="app"></main><dialog id="modal" aria-label="Study action"></dialog><div id="announcements" class="screen-reader-only" role="status" aria-live="polite"></div>'
html += '<footer>Invented researcher testing only. No collection backend. Answers stay in page memory until discarded or explicitly exported after simulated final submission. No live AI or automatic saving. Researcher JSON export is plaintext.</footer>'
html += ''.join('<script>' + s + '</script>' for s in scripts) + '</body></html>\n'
(ROOT / 'index.html').write_text(html)
manifest = {**meta,
    'artifact': 'WattDialogue standalone local anonymous-web-flow STUDY REVIEW display',
    'consent_appendix_sha256': sha256(consent_body.encode()).hexdigest(),
    'protocol_sha256': corpus['protocol_sha256'],
    'review_allocation': corpus['review_allocation'],
    'corpus_provenance': corpus['prepared_by'],
    'review_needed': corpus['review_decisions'],
    'file_sha256': {name: sha256((ROOT / name).read_bytes()).hexdigest() for name in ['index.html', 'corpus.json', 'corpus.schema.json', 'session-record.schema.json', 'orientation-and-help.json', 'orientation-and-help.schema.json', 'study-core.js', 'app.js', 'styles.css', 'build.py', 'build_corpus.py', 'build_orientation.py', 'make_schemas.py', 'test-review.js', 'verify-review.py']}
}
(ROOT / 'review-freeze.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
print('Built self-contained index.html; scripts/styles have CSP hashes; outbound connections denied.')
