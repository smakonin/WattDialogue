# WattDialogue anonymous website study REVIEW

This self-contained local preview uses invented researcher-testing responses only. It is available as a public research preview at [WattDialogue/study](https://smakonin.github.io/WattDialogue/study/), but is not approved or open for participant collection. The proposed study is unpaid, uses volunteers’ own devices and connection, and aims for an anonymous research dataset. Institutional hosting and logging have not been selected or verified.

Open [index.html](index.html) in a current browser, or serve just this directory with `python3 -m http.server 8791 --bind 127.0.0.1` and open [127.0.0.1:8791](http://127.0.0.1:8791/). Stop the preview server with Ctrl+C. Do not serve the repository root. The existing replay demo on port 8767 is separate. The file contains all scripts, styles and evidence and can be opened without Internet access.

## What can be reviewed

The flow presents the current consent draft, invented eligibility self-reports, optional access questions, equal-probability selection from four orders, separate P1/P2 orientation, six tasks in each format, optional ratings/break/feedback, and a simulated final Submit. Manual assignment and automatic invented-answer filling are researcher checks; they are not final participant controls.

Both formats read the same immutable evidence, units, labels, coverage, status, uncertainty, revision availability and comfort constraints. The dashboard includes readable tables, labelled bars and the same interpretations available through prepared dialogue questions. There is no live chat or inference. Normal dialogue access is distinct from an explicit help request; exact help levels are available in both views.

Practice answers are cleared before unscored feedback. Only completion/skip markers and relative events enter the in-memory review packet. Scored answer time stops when the answer is held and confidence follows; the timer counts visible, unpaused browser time rather than observed attention. Pause, hidden-tab, accommodation extension, skip, timeout and reported technical fault remain separate events.

## Data boundaries

### GitHub Pages hosting

The self-contained HTML/CSS/JavaScript REVIEW interface can run on GitHub Pages. It currently has no response collector, and Pages hosting alone would not add one. Actual final submissions need a separately approved HTTPS collector and storage, with the current outbound-denying Content Security Policy deliberately revised for that endpoint after review.

[GitHub's official Pages documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages#data-collection), checked 30 September 2026, states that visitors' IP addresses are logged and stored for security whether or not they sign in. Therefore, a Pages-hosted study must not promise that no identifying hosting logs are retained. Keep the research responses free of identifiers, disclose the host's logging, and obtain institutional review of the chosen arrangement; choose another audited host if the requirement is no retained identifying access logs. GitHub Pages is available for public repositories on GitHub Free; private-repository hosting requires an eligible paid plan. The repository's `pages.yml` workflow publishes the self-contained preview after no-key checks. No response collector is deployed.

Answers remain in browser RAM. No name, contact field, login, participant code, withdrawal token, IP, user agent, fingerprint or calendar timestamp is recorded by this application. It uses no cookies, persistent browser storage, analytics, microphone or camera. There is no collection endpoint, partial upload or real final submission. The Content Security Policy denies outbound connections and form actions; permitted inline scripts/styles have hashes.

Exit discards the current packet. Only after both formats and simulated final submission can a researcher preview and explicitly download invented JSON, after acknowledging that it is plaintext. No automatic file saving occurs. The local display does not encrypt downloads or demonstrate approved storage, hosting anonymity or REB approval. A local development server may keep access logs; it is not the production privacy design.

Actual online collection needs an approved institutionally managed HTTPS endpoint/storage, reviewed host/proxy/CDN/security/error/database/backup logging and residence, final consent/contact details, PI eligibility/training and written approval before recruitment. Transient Internet addressing and accidentally identifying free text require honest privacy handling. The proposed final anonymous submission cannot later be located for individual removal; this is disclosed before consent and Submit. No actual participant data belongs in this directory or repository.

## Evidence and review decisions

[corpus.json](corpus.json) contains the exact twelve invented Appendix A cards and four assignments. [orientation-and-help.json](orientation-and-help.json) contains the separate orientation cards and exact help. The [draft protocol](../WattDialogue_Participant_Protocol_and_Ethics_Draft.tex) is included so the website can be rebuilt from a clean clone. Its scored table is byte-identical to v0.1. The protocol remains a review draft, not an approved or submitted study.

Unprovided dates/bounds stay null; relative windows are shown. Task 2 supplies no measurement provenance. Task 1 component sums are 8.64/7.50 kWh, distinct from aggregate meter totals 9.20/8.00 kWh; no forced closure is introduced. Task 4 shows 75% coverage and missing hours. Task 5 shows post-block availability. Each card is independent. Codex-assisted preparation and PI-review-pending status are recorded; software checks do not replace author review or an approved participant freeze.

## Verification and reproducibility

With Node.js and Python 3 available, run these from this directory:

```sh
node test-review.js
python3 verify-review.py
```

The logic checks exercise all four paths, 48 invented scored-task outcomes, separate practice completion/skip, pause/extension/timeout, invalid confidence, skips/faults, final-submit gating and discard. Schema/source checks validate all keywords used by the three supplied JSON schemas, exact task/evidence integrity, source hashes, shared evidence, CSP hashes and absence of outbound/persistent-storage calls. They are not participant outcomes or infrastructure security certification. Synthetic fixtures are clearly labelled invented.

To rebuild after reviewed source changes, run these in order:

```sh
python3 build_corpus.py
python3 build_orientation.py
python3 make_schemas.py
python3 build.py
node test-review.js
python3 verify-review.py
```

[review-freeze.json](review-freeze.json) records source, corpus, per-card evidence, orientation, schema and code hashes. It is a REVIEW snapshot, not approval. The original local archive is maintained outside the repository. The unchanged v0.1 scoring table is preserved in [task-table-v01.tex](../task-table-v01.tex) for the portable integrity check.

Manual browser review of assignment 1 used invented responses only. It covered the full consent header and eligibility, P1 practice completion and feedback with its input cleared, six dashboard skips, blank optional ratings, break, a P2 prepared question and practice skip, six dialogue skips, the twelve-outcome final review, the explicit simulated-Submit choice, and the optional plaintext export preview. The preview contained consent/self-reports/allocation, twelve task outcomes and two practice-completion markers, with no practice answers, identity, return code or calendar timestamp. The interface reported an invented JSON export; the browser download-event waiter timed out, so a downloaded file and saved path were not verified. Local test memory was discarded. Earlier manual checks also covered pause/extension and confidence. All four orders passed the 569 synthetic logic checks; only assignment 1 has a complete manual browser pass. Cross-device and assistive-technology evaluation remain necessary before launch. No raw participant results, claims of distinct respondents, measured savings or socioeconomic equality follow from this preview.
