# WattDialogue display verification

The standalone interface uses no frontend framework, external scripts, analytics, remotely hosted fonts, or browser-side API credentials.

## Data-source honesty

The server identifies inputs through `synthetic_fixture`, `input_kind`, `data_source`, and optional `household_labels`. Summary metadata takes precedence over status metadata. Before source metadata loads, the display makes no claim that its values are actual household measurements.

In synthetic mode, the banner, household options, overview, numeric source badges, answer notice, naming dialog, and footer identify generated fixtures. Fixture values are examples, not data from a real home, executed NILM results, or reported research findings. With explicitly configured archive input, the display instead identifies historical replay and retains measurement/estimate distinctions. Neither mode claims a live meter connection.

Browser caches are separated by input kind and use a versioned namespace. Switching from archive replay to synthetic fixtures cannot reuse a legacy cached archive as a synthetic example. Consent and credentials are not cached.

## Implemented interaction

- Household and period selection, a separate meter total and estimated-load overview, coverage, evidence-availability time, and unexplained consumption.
- Friendly anonymous aliases independent of energy rank. Load numbers are not counts of physical appliances; API payloads and evidence details preserve stable component identifiers.
- Inline `(rename)` beside each eligible load name. Only `rename` is a link-styled semantic button, with a load-specific accessible name. Uncertainty stays below and kWh in a separate column.
- Explicit demo/operator annotations, not claims of observed resident confirmation or independently verified appliance identity. Confirmation uses an existing evidence reference, model version, and recorded `as_of` where supplied.
- Positive unexplained electricity separately from signed diagnostic residuals and over-allocation. Fractional coverage is displayed as a percentage.
- Local explanations by default. Cloud consent is off on every page load and applies only to that session; the server owns AI access.
- Session-scoped household changes. Writes send the status-provided `X-WattDialogue-Token` header with same-origin cookies.
- API prose uses text nodes, never injected HTML. Structured numeric fields carry source labels.
- Cached, explicitly dated summary fallback after a local-service interruption. This does not establish a complete offline installation.
- Touch and keyboard interaction. Voice is described as a future feature without a pretend recording control.

## Static checks completed

- JavaScript syntax check passes.
- No API response is inserted using `innerHTML`.
- Browser storage contains only received period lists and summaries, separated by input kind.
- No browser credential entry, hard-coded household energy totals, or assumed appliance identities.

## Integrated browser checklist

1. Start the default synthetic demo: consent is off, generated inputs are prominent, and no value is described as coming from a real household.
2. Where an archive adapter is explicitly configured, its source metadata changes source notices consistently; timestamps remain historical and non-live.
3. Change household and period through the session controls; the prior answer clears and the supplied measurement boundary remains visible.
4. Ask a suggested and typed question. Verify numeric cards, percentages, evidence references, uncertainty, and appropriate synthetic/archive source labels.
5. Follow `(rename)` by touch or keyboard. The dialog must preserve the exact evidence/model/as-of context and show an error when a write fails.
6. Verify Tab/Shift+Tab order, dialog focus containment, Escape, and Ctrl/Cmd+Enter. Test narrow layouts and 200% zoom for overflow, wrapping and visible warnings.
7. Without configured server-side AI, cloud settings remain unavailable. With access configured, opt-in is required and revocation changes later questions to local mode.
8. Temporarily disconnect the local service after loading evidence. Cached summaries retain source identity and age; new responses cannot imply current appliance activity.

## Deployment limits

This interface does not establish utility device provision, cellular coverage, accessibility certification, production household authentication, or conservation effects. A supplied display and provisioned connection remain a proposed way to evaluate access without residents' personal technology.
