# Prototype verification

The default test suite runs from a clean copy using generated synthetic traces and no paid API calls:

```sh
python -m unittest discover -s tests -v
python scripts/check_repo_safety.py
```

It checks native-interval integration, fractional bounds, missingness, separate meter/component coverage, availability of revised estimates, signed residuals, annotation provenance, household/version scope, the independent numerical oracle, strict response handling, local fallbacks and request-cap/backup behaviour. It also checks that the HTTP server does not expose configuration or private scoring files.

Synthetic data is intentionally incomplete in selected intervals and has an allocation-error example. Fixture expectations are declared tests, not findings about occupants or NILM appliance accuracy. Private archive checks are skipped unless an explicit authorised archive path is supplied; see the adapter contract.

The benchmark generator prepares 120 synthetic evaluation cases and 30 synthetic development cases. Private research-case exposure records and measured traces are kept separately from the repository. Formal model evaluation needs an execution freeze, independently retained responses and manual factuality review.

GitHub Actions runs the no-key suite, tracked-file safety audit and JavaScript syntax check. `python live_check.py --live` is an explicit, optional paid check using a synthetic signature; its runtime output is ignored by Git. Unit tests isolate credentials to prevent an existing shell key from causing a paid request.

Browser interaction checks cover the source indicator, local questions, two recording boundaries, uncertainty, cloud choice, cached historical feedback and the inline **(rename)** dialog. Broader accessibility, live gateway, device provision, resident comprehension and savings evaluation remain separate study tasks.
