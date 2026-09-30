# WattDialogue question benchmark

The repository contains a generator, an independent numerical oracle, a response
scorer, and manual synthetic arithmetic fixtures. The default generator uses
wholly synthetic demonstration signals. It reads no household archive, calls no
model, and contains no credentials. Synthetic results are interface checks, not
experimental NILM accuracy, measured savings, or resident comprehension findings.

## Generate a synthetic benchmark

From the prototype directory, use a Python environment with NumPy:

```sh
python3 benchmark/generate.py
python3 -m unittest discover -s tests -p test_benchmark.py -v
```

The default output is `benchmark/generated/`. The generator obtains arrays from
`wattdialogue.demo_data`, writes generated NPZ files inside that output directory,
and independently integrates their allowed channels. Recording/block identifiers
are compatibility aliases; they do not make these generated values measurements
from the datasets associated with those names.

There are 120 prepared evaluation questions across eight blocks, 15 per block:
60 consumption/comparison, 20 ambiguous-label, 20 missing/stale/revision, and 20
certainty/comfort cases. Alternating blocks use category counts 8/3/2/2 and
7/2/3/3. A separate 30 development questions use the first block per recording.
The generator obtains the recording selection and native cadence from the demo
metadata. Generated cases contain no responses; generation is not evaluation.

Products are `questions.jsonl`, `dev_questions.jsonl`, `private/expected.jsonl`,
`private/dev_expected.jsonl`, `protocol.json`, and `manifest.json`. The manifest
records source/content hashes, implementation hashes, selection, timing, and
exposure status. `--output` selects a new version. Existing products cannot be
replaced without `--overwrite`; do not overwrite after collecting responses.

Only public question objects go to the responder. Never serve `private/` or give
oracle targets, rationale, reference mappings, or numeric answers to an agent.
Comfort preferences are declared scripted contexts, not observed resident data.
Use an empty label registry and no tariff for this protocol; a confirmation or
inventory comparison needs a separately declared study.

## Optional private replay

Private source data is an explicit opt-in. Supply both paths:

```sh
python3 benchmark/generate.py --source-root /path/to/replay \
  --source-profile /path/to/source-profile.json --output /path/to/private-benchmark
```

The read-only source layout is `<recording>/verification/<block>.npz`. The profile
must explicitly document two recordings with five distinct blocks each, native
cadence, measured aggregate boundary, and model version. Its first block per
recording is development; the remaining eight become prepared evaluation cases.
For example, a profile for user-provided data has this structure:

```json
{
  "recordings": {
    "home_one": {
      "blocks": ["dev", "case1", "case2", "case3", "case4"],
      "cadence_seconds": 1,
      "boundary": "Describe this source's measured aggregate",
      "model_version": "Describe this source's online output version"
    },
    "home_two": {
      "blocks": ["dev", "case1", "case2", "case3", "case4"],
      "cadence_seconds": 60,
      "boundary": "Describe this source's measured aggregate",
      "model_version": "Describe this source's online output version"
    }
  }
}
```

An optional `upstream_manifest` path records its hash; a relative path resolves
from the profile's directory. There is no implicit private source path or archive
search. Generated private questions, targets, manifests, responses, and even
source timing/hash metadata remain private research products. Keep them outside
the repository or in its ignored generated folders. Sanitized inputs and source
profiles should be distributed separately under their applicable permissions.

## Independent arithmetic and scoring

`oracle.py` imports NumPy, not the adapter, `EnergyTools`, or label registry. It
reads only `t`, aggregate `P[:,0]`, and `control_P_online`. Other columns, the
reference-dependent `valid` mask, reference names, and retrospective vectors are
excluded. Native cadence is explicit and is never inferred across missing rows.

A row covers `[t,t+cadence)`. Queries clip native intervals and skip missing or
nonfinite observations. The whole interval must complete before `as_of`, even if
the requested window clips it. Meter integration uses finite aggregate values;
components and residuals use the common finite aggregate/all-24-components mask.
Separate coverage is retained; missingness is not zero consumption. Means are
weighted by observed duration, and percent change is undefined for a zero
baseline. Positive unexplained and negative overallocated energy remain separate.
An early request for final retrospective output requires abstention.

`fixtures/interval_cases.json` is manually synthetic with explicit arithmetic
expectations. Tests exercise interval clipping, gaps, availability, nonfinite
components, zero denominators, zoned timestamps, ignored reference channels,
source selection, leakage controls, and adversarial response scoring.

A supplied callback receives a public question only:

```python
from benchmark.score import evaluate

report = evaluate(
    "benchmark/generated/dev_questions.jsonl",
    "benchmark/generated/private/dev_expected.jsonl",
    response_callback,
    "benchmark/generated/runs/local-development",
    manifest_path="benchmark/generated/manifest.json",
    run_kind="development",
    run_metadata={"responder": "deterministic local template", "api_calls": 0},
)
```

Return the actual server contract: `answer`, `evidence`, `fields`,
`label_candidates`, `warnings`, `freshness`, `mode`, `evidence_ids`, and
`constraints`. Fields include stable `metric`, readable `label`, numeric `value`,
`unit`, and `source` (`meter`, `nilm_estimate`, or `derived`). Evidence retains
household/block, window, `as_of`, coverage, online mode, boundary, availability,
and the independently reproducible allowed-channel content hash. Scope denial
needs structured evidence with the authenticated household, `scope_denied: true`,
and no foreign measurements. Every category requires applicable evidence.

To score saved responses without a model call:

```sh
python3 benchmark/score.py --questions benchmark/generated/dev_questions.jsonl \
  --expected benchmark/generated/private/dev_expected.jsonl --responses saved-responses.jsonl \
  --manifest benchmark/generated/manifest.json --output benchmark/generated/runs/saved \
  --run-kind development
```

Saved rows contain `id` and `response`. `--callback module:function` can instead
supply a local responder. Failures and actual outputs are retained; the harness
does not manufacture answers. A deterministic run remains a smoke baseline.

Before a reserved model evaluation, call `freeze_execution` with tool files,
prompt files, and declared configuration. Record model/version, generation
settings, repeats, registry/tariff state, budget, and failure handling. Reserved
evaluation refuses missing or changed execution hashes. Use fresh cases if an
untouched holdout is needed after development exposure; a smoke run cannot be
retroactively promoted to a formal model evaluation.

Numerical tolerances are 0.01 kWh, 1 W, 1 second, 0.1 percentage points, and 1e-6
for coverage, with 1e-6 relative tolerance. Abstention, identity certainty,
unsupported monetary claims, comfort, household scope, coverage, availability,
and provenance are checked separately. Prose checks are incomplete screening;
**manually review every response** before claiming factuality or comfort outcomes.
The optional reference-association helper does not perform matching, establish
physical appliance identity, or supply label-accuracy evidence.

## Repository export boundary

Commit only `generate.py`, `oracle.py`, `score.py`, `README.md`, `.gitignore`, and
`fixtures/interval_cases.json` from this folder, plus `tests/test_benchmark.py`.
The generated JSONL, protocol/manifests, private targets, sources, and run outputs
are excluded. `.gitignore` supports that boundary but an explicit file allowlist
is the final protection when creating an export. Preserved private research
products are not examples or assets for a public release.
