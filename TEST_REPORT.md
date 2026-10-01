# Prototype verification

The default test suite runs from a clean copy using generated synthetic traces and no paid API calls:

```sh
python -m unittest discover -s tests -v
python scripts/check_repo_safety.py
```

It checks native-interval integration, fractional bounds, missingness, separate meter/component coverage, availability of revised estimates, signed residuals, annotation provenance, household/version scope, the independent numerical oracle, strict response handling, local fallbacks and request-cap/backup behaviour. It also checks that the HTTP server does not expose configuration or private scoring files.

The model-evaluation runner adds checks for frozen configuration and resume refusal, concurrent durable journals, shared budget reservations, cached-token accounting, uncertain requests, preservation of rejected model outputs, unchanged production requests, and finite-coverage minute-bin inputs. These use mocked transports and make no paid requests. On 30 September 2026, all 65 checks passed with the optional authorized archive replay check enabled; none was skipped. This verifies software behaviour, not model answer quality.

Synthetic data is intentionally incomplete in selected intervals and has an allocation-error example. Fixture expectations are declared tests, not findings about occupants or NILM appliance accuracy. Private archive checks are skipped unless an explicit authorised archive path is supplied; see the adapter contract.

The benchmark generator prepares 120 synthetic evaluation cases and 30 synthetic development cases. Private research-case exposure records and measured traces are kept separately from the repository. Formal model evaluation needs an execution freeze, independently retained responses and manual factuality review.

GitHub Actions runs the no-key suite, tracked-file safety audit and JavaScript syntax check. `python live_check.py --live` is an explicit, optional paid check using a synthetic signature; its runtime output is ignored by Git. Unit tests isolate credentials to prevent an existing shell key from causing a paid request.

Browser interaction checks cover the source indicator, local questions, two recording boundaries, uncertainty, cloud choice, cached historical feedback and the inline **(rename)** dialog. Broader accessibility, live gateway, device provision, resident comprehension and savings evaluation remain separate study tasks.


The later sustained/revision extension passed all **71 checks** with the optional
local archive check enabled. It added synthetic-oracle conformance, cache churn,
atomic snapshot publication, an expected-failure unpinned comparison, eight
simultaneous queries, same-model revisions, and stale confirmation rejection.
The public engineering runners separately passed 123,624 sustained HTTP requests,
64 forced publication cases, 1,760 synthetic scaling checks and 24 simulated
provider recovery checks. The six-minute soak used 120 seconds each at 1/4/8
clients. These are local software/performance findings, with zero new provider
requests. See [the reproducible guide](benchmark/ENGINEERING.md) for exact scope.

## Private repository sync — 1 October 2026

The committed synthetic study review website passed 569 logic checks across four
assignments and 48 invented task outcomes, schema/evidence/source-hash checks,
CSP checks, and a repeat rebuild with no tracked changes. It includes the draft
protocol and original task-table baseline for portable verification. These are
software checks, not participant findings or ethics approval.

The repository suite ran 71 tests: 70 passed and the explicit private-archive
opt-in check was skipped. No paid provider requests were made. JavaScript syntax
checks passed for the demo and study source, and the staged-file safety audit
found no credentials or private datasets. GitHub Actions also runs the study
checks and verifies that rebuilding leaves the committed artifacts unchanged.
