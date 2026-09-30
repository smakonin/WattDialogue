# WattDialogue

A conversational bridge from unsupervised NILM results to household energy understanding.

This repository contains the replay bridge, independent question benchmark and in-home display prototype accompanying the working IEEE PES GM 2027 paper. **The repository is private while the demo is being prepared. Public release is planned when it is ready.**

## Run the demo

Python 3.12 or later is required. No frontend build or OpenAI account is needed for local feedback.

```sh
git clone https://github.com/smakonin/WattDialogue.git
cd WattDialogue
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run.py
```

On Windows, use `py -3 -m venv .venv` and `.venv\Scripts\activate` for the environment steps. Open **http://127.0.0.1:8767** in a browser. Stop the service with Ctrl+C.

A fresh copy runs a deterministic **synthetic** replay. These generated signatures demonstrate the interface and are labelled as synthetic throughout the display. They contain no private household recordings or established appliance identities. The demo has no live meter connection or appliance control.

## Add your OpenAI keys

AI dialogue is optional. Keep credentials on the machine running the Python service:

```sh
cp .env.example .env.local
```

On Windows, use `copy .env.example .env.local`. Open `.env.local` in a text editor and fill in the values locally:

```dotenv
OPENAI_API_KEY=your_primary_key
OPENAI_API_KEY_BACKUP=your_optional_backup_key
WATTDIALOGUE_MODEL=gpt-5.4-mini
WATTDIALOGUE_LIVE_CALL_LIMIT=8
```

The values above are placeholders. Leave the backup value empty if it is not needed. Environment variables with the same names are also supported. For an existing configuration stored elsewhere, use `python run.py --env-file /path/to/private/config.env`.

**Never commit `.env.local`, a key, or a populated copy of the template.** `.gitignore` excludes local configuration, credentials, runtime output and datasets; only the blank `.env.example` is tracked. `python scripts/check_repo_safety.py` checks tracked/staged content without printing secret values.

Open **AI settings** in the display and explicitly enable cloud processing for the current session. The service sends the question and necessary tool summaries to OpenAI. The browser receives answers and key-availability flags, never the keys. Local feedback remains usable with cloud consent off.

The default model is `gpt-5.4-mini`. The live-call limit caps HTTP requests **per running process**, including tool rounds and backup retries. Restarting resets this counter; it is not a dollar budget. The backup is used only when the primary returns `insufficient_quota`. It does not bypass the cap. An authentication error or transient rate limit does not trigger key switching. A fallback answer is explicitly marked as local.

## Use previous HyNILM outputs

The research integration has ten archived blocks from R1Hz and AMPds2. They are kept separately from this repository. To replay authorised previous outputs:

```sh
python run.py --source-root /path/to/hynilm-replay/runs
```

The directory contains `{recording}/verification/{block}.npz`. The adapter reads timestamps `t`, aggregate power `P[:,0]`, and anonymous estimates `control_P_online`; `control_P_revised` is a separate post-block view. Reference appliance columns and the joint reference-dependent validity mask do not enter answers. The display distinguishes archive replay from the synthetic demo.

`python scripts/export_replay.py --source-root /path/to/original/runs --output /path/outside/repository/replay` creates a separate replay bundle containing only those permitted arrays. It does not alter the original data. Neither source recordings nor exported bundles are committed. A future public demo can use a separately approved replay sample without distributing reference labels or private household activity.

GitHub stores the runnable source. A shared hosted demonstration also requires a backend service for Python and server-owned API access; this repository does not deploy that service. Its current server accepts loopback connections. Hosting, household authentication and device/gateway testing remain deployment work.

## What the prototype does

- Calculates measured totals, estimated component use, covered intervals, comparisons and unexplained/over-allocated consumption in software.
- Answers through a deterministic local template or a bounded Responses API tool loop.
- Suggests appliance names with alternatives, while preserving unknown, candidate, occupant-confirmed and independently verified annotation states.
- Keeps label annotations separate from the unsupervised learner and records replay-operator confirmations as simulations.
- Displays ordinary-language load names, **(rename)** links, evidence, uncertainty, cloud choice and cached historical feedback.

See the [adapter contract](docs/adapter-contract.md), [benchmark guide](benchmark/README.md), [data and privacy notes](docs/DATA_AND_PRIVACY.md), and [test guide](TEST_REPORT.md).

## Run checks

```sh
python -m unittest discover -s tests -v
python scripts/check_repo_safety.py
```

The default suite uses synthetic fixtures and makes no paid API calls. Optional private-archive checks require an explicit path. JavaScript syntax can be checked with `node --check web/app.js`; Node is not needed to run the display.

`python live_check.py --live` makes a bounded paid OpenAI check with a declared synthetic signature and saves the result in ignored `runtime/`. It is separate from a model benchmark. GitHub Actions runs the no-key checks only.

The runnable demo makes the interface inspectable. It does not establish physical appliance accuracy, occupant comprehension, utility access or energy savings. Those results require separate evaluation. The public launch checklist is in [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md).

## Model evaluation

The [benchmark guide](benchmark/README.md#run-a-frozen-model-evaluation) documents a
resumable paid evaluation runner comparing the deterministic template, production
WattDialogue and GPT arithmetic from precomputed minute-bin electrical features.
It freezes source, code, prompts, schemas, model settings and prior case exposure
before requests. Raw model responses and delivered fallback answers remain separate.
The arithmetic condition changes numerical processing and evidence orchestration;
it is not GPT reading untouched native traces.

Use explicitly authorised replay inputs, a source profile, an existing private
configuration and an output directory outside this repository. `--freeze-only`
prepares the execution without API requests. The default model is the fixed
`gpt-5.4-mini-2026-03-17` snapshot; three repeats, a USD 20 conservative cost limit
and a separate HTTP request cap apply. Project rate limits still apply, and the
runner does not automatically retry rate-limit failures. Numerical fidelity,
model completion, fallback use and author-reviewed prose findings must be reported
separately. No generated results, household data or participant records belong in
Git. The no-key test suite does not run this paid evaluation.

## License and citation

The source code is licensed under the **GNU General Public License, version 3** (`GPL-3.0-only`); see [LICENSE](LICENSE). Dataset permissions are separate. [CITATION.cff](CITATION.cff) supplies the software citation; cite the accompanying paper once published.
