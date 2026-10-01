# Reproducible engineering benchmarks

These tests run locally with generated signals. They need Python 3.12+, NumPy and,
for process-memory measurements, macOS or Linux with `ps`. They use no API key,
read no populated configuration file, send no provider requests and load no
household archive. The transport rejects any accidental provider call. Recording
identifiers are compatibility aliases for synthetic inputs.

From the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -p test_engineering.py
python3 benchmark/run_engineering.py \
  --output runtime/engineering-soak-01 --seconds 120 --clients 1 4 8
python3 benchmark/run_scaling_recovery.py \
  --output runtime/engineering-scaling-01
```

Each output directory must be new. Outputs under `runtime/` are ignored by Git.
Keep the original products after running: changing code or parameters requires a
new directory. Protocols freeze implementation/input hashes before measurement;
artifact manifests hash the recorded products afterwards. The soak runner also preserves the frozen implementation source. Reproduction means the
same procedure and checks, not identical timings on different hardware.

## Sustained HTTP load

The default is 60 seconds at each of 1/4/8 clients; the command above uses 120.
A 60-case workload rotates through ten generated replay blocks, both estimate
modes, and meter, component and comparison requests. Its arithmetic targets come
from the independent benchmark oracle. The production four-entry cache and
loopback server execute normally; each client has separate household sessions.
The server is a separate process. HTTP/1.0 uses a new connection per request.

This is closed-loop traffic with no think time. HTTP latency includes request,
body read and JSON decoding, with scoring after the stopwatch. Scoring remains
inside each client cycle, so reported throughput includes that cost. Phase
throughput uses successful completions over elapsed duration including final
drain. Five-second bins use completion time and keep failures and post-deadline
completions explicit. It is not an open-loop saturation or internet-latency test.

The process RSS sampler runs each second; the final high-water RSS belongs to the
server alone. Neither establishes a memory-leak bound for multi-hour operation.
Initial array/cache allocations are expected. Values are operating-system process
RSS, not a per-query allocation measurement. Other computer activity can influence
results. Session count is finite for the declared workload.

Options are bounded: 1–600 seconds per phase, up to four distinct levels with
1–16 clients, and 1–100 revision repetitions. HTTP and barrier timeouts are ten
seconds. Stop the command to end the benchmark; the child server is cleaned up.

## Revision during an answer

Eight scripted scenarios run eight times each: immediate/revised summaries,
component features and comparisons, a revision requested too early, and a label
query. A barrier stops an answer after it has started reading evidence; a producer
then atomically publishes new immutable component arrays, content hashes and model
versions while retaining the meter and timestamps. These are simulated updates,
not a live HyNILM ingestion interface or physical appliance split/merge experiment.

An answer must match the complete pre-publication response, excluding its timing;
the next query must reflect the publication. A deliberately unpinned comparison
is a negative control: it must expose mixed old/new evidence versions. The suite
also rejects stale confirmation evidence and checks that an old annotation does
not automatically transfer to a new model version. The production query and
summary entry points capture a store snapshot; frozen replay adapters return
themselves, while a mutable adapter must supply an atomic immutable view.

`PROTOCOL.json`, `CASES.json`, per-phase HTTP records/summaries,
`SERVER_MEMORY.json`, `REVISIONS.json`, `RESULTS.json` and `ARTIFACT_SHA256.json`
retain inputs, boundaries, counts, failures, response digests and environment.
No cookie or credential is recorded.

## Resident-array scaling and simulated provider recovery

`run_scaling_recovery.py` runs 176 unique cells with one warm-up and ten measured
calls each. Retained history is 1/6/24/72 hours, cadence 1/60 seconds, and active
components 1/4/12/24 within 24 allocated slots. Query windows are five minutes,
one hour and full history, collapsing duplicates. A closed-form periodic pulse
oracle checks energy and coverage. Arrays are resident; loading, HTTP, rendering
and NILM inference are excluded.

Recovery uses four simulated provider errors: timeout, rate limit, invalid key and
quota. Each has three failed and three restored responses. A dummy credential
exists only in memory for the simulated transport; it cannot authenticate a real
request. Both the local fallback and restored two-turn tool response are checked
against the independent synthetic oracle. These are 24 scripted checks, not a
provider availability measurement or a physical connectivity test.

## Display timing and cached-display recovery

```sh
python3 benchmark/serve_display_benchmark.py \
  --output runtime/engineering-display-01 --port 8794
```

Open `http://127.0.0.1:8794/` in a visible browser and wait for the recording to
load. Click **Run display timing**, then **Test cached display recovery**. Keep
the tab visible and do not interact with it while measurements run. Stop the
server afterwards. This creates an instrumented copy of the real display, leaving
the source renderer unchanged. It uses generated data and disables cloud access.

The first button runs three warm-ups and 30 ordinary requests, rotating meter,
component and comparison questions. It records native fetch/JSON, DOM update,
rounded-card fidelity, visibility, viewport and browser version. Two animation
frame callbacks after answer rendering measure a visible-layout opportunity;
they are not first-paint or physical-screen latency. The second button runs three
HTTP-503 outage/restoration cycles and checks cached age, stale warnings, disabled
renaming and resumed retrieval. Its six additional timings are separate from the
ordinary 30-query cohort. Results save to `BROWSER_RESULTS.json`; no participant
answers are collected. Use a fresh output directory for a new browser run.

## Interpretation and release boundary

Synthetic performance results support interface timing, numerical conformance and
specified failure handling. They do not establish NILM or appliance-name accuracy,
explanation correctness, resident understanding, savings or inclusive access.
Historical household/model evaluations require their separately authorised inputs
and must not be inferred from this package. The repository includes source under
GPL-3.0-only and deterministic inputs, not household traces or configured keys.
