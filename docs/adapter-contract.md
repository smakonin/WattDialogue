# WattDialogue replay and deterministic evidence contract

Standalone launch uses wholly synthetic, deterministic demonstration signals. No household archive, credentials, parent directory, or learned NILM model is required. `ReplayStore(root=None)` generates traces in memory with model version `synthetic-demo-v1/control/P`. These demonstrations support interface and arithmetic checks, not empirical appliance accuracy, occupant comprehension, or conservation claims.

An explicit source directory opts into a compatible replay archive, using the `quiet_fusion_v3a/control/P` profile. The archive is supplied separately by its operator and is not distributed with this prototype. The adapter does not certify that external archive's authenticity or experimental independence. Dataset aliases and block keys remain compatible across modes; they are not evidence that a synthetic trace represents a real recording.

## Source boundary

There is no default file root. `ReplayStore(root)` accepts an explicitly supplied runs directory or a parent containing `runs`. `--source-root` at standalone launch selects that supplied archive. An unavailable explicit archive raises an error rather than silently falling back to the synthetic demonstration.

| Compatibility recording / scope key | Allowed block aliases | Native interval | Inference interval | Synthetic boundary |
| --- | --- | --- | --- | --- |
| R1Hz | 17422, 17428, 17452, 17602, 18179 | 1 s | 5 s | Synthetic home 1 aggregate; no physical meter |
| AMPds2 | 15431, 15437, 15461, 15611, 16161 | 60 s | 60 s | Synthetic home 2 aggregate; no physical meter |

Generated traces last six hours, beginning on a declared synthetic date in January 2025. Each has anonymous component pulses, background demand, one absent native interval, one invalid aggregate interval, one invalid component interval, and an illustrative over-allocation period. All signal values and dates are generated from published formulas, with no original measurements, labels or source hashes copied. The synthetic vectors are hand-authored signals, not outputs of an evaluated NILM model.

An explicit source file is `<root>/<recording>/verification/<block_id>.npz`. The adapter reads only the `t`, `P`, and selected `control_P_online` or `control_P_revised` members. NPZ storage requires loading the `P` member; only column zero is copied into the application object and its other columns are discarded immediately. A sanitized `P` with one column is also accepted. It never reads evaluator current, joint-valid masks, appliance names, or reference mappings. The returned dataset contains only native time, one-dimensional `aggregate_w`, and 24 anonymous `components_w` channels plus provenance. Capacity 24 is not a physical appliance count. The supplied archive profile declares the R1Hz residential main aggregate and AMPds2 MHE = WHE minus rental suite and garage; the synthetic default makes no physical boundary claim.

## Public Python interface

```python
from wattdialogue.adapter import ReplayStore
from wattdialogue.labels import LabelRegistry
from wattdialogue.tools import EnergyTools

store = ReplayStore(root=None)
selected_model_version = store.model_version  # pass explicitly to label writes
store.list_blocks(recording=None)              # {recording: [block_ids]}
store.metadata(recording, block_id)            # JSON dict, online mode
store.source_metadata()                       # kind/version/labels/boundaries
data = store.load(recording, block_id, mode="online")
data.metadata()                               # selected mode metadata
data.select(start=None, end=None, as_of=None)  # internal numeric masks/weights

labels = LabelRegistry(path=None)              # optional private JSON persistence
tools = EnergyTools(store, labels=None, flat_rate_cad_per_kwh=None)
evidence = tools.call(name, args, home_scope)   # JSON dict or readable ValueError
```

`home_scope` is fixed by the authenticated session, either `R1Hz` or `AMPds2`; the model cannot change it. Optional argument `recording` or `home_id` must equal that scope. Block IDs are strictly allowlisted for the selected home. Names and argument keys are allowlisted. The server should expose `call`, not arbitrary methods or file paths.

Common JSON arguments are `block_id`, `start`, `end`, `as_of`, `mode`, `recording`, and `home_id`. Times accept finite Unix seconds or timezone-aware ISO 8601 strings; naive local timestamps are rejected. `mode` is `online` or `revised`. Missing start/end/as_of default to the selected block's native start/end/end. A default block window is not necessarily a complete local calendar day. Metadata states `America/Vancouver` for interpretation; every exported instant is explicit UTC.

| Tool name | Additional arguments | Main numeric output |
| --- | --- | --- |
| `get_window_summary` | none | `energy_kwh`, `average_power_w`, `peak_power_w`, `component_energy_kwh` dictionary, signed/positive/negative residual energy |
| `get_component_features` | `component_id` | `energy_kwh` and `component_energy_kwh` scalar, mean/peak estimated W, active seconds, observed positive spans |
| `compare_periods` | `period_a`, `period_b` objects using common keys | `period_a_energy_kwh`, `period_b_energy_kwh`, `difference_kwh`, `difference_percent` |
| `get_label` | `component_id` | Label evidence only; no meter coverage calculation |

Comparison children inherit top-level `block_id`, `as_of`, and `mode`; child keys can override these except the fixed home scope. Components use `component_000` through `component_023`; integer indices 0 through 23 are also accepted. Other values are rejected.

## Interval completion and missingness

A native sample at `t` represents the half-open interval `[t, t + native_interval_s)`. The minute profile requires completion of the entire minute before any clipped part is available. The one-second profile uses a zero-order-hold integration convention. Synthetic vectors are held on a declared five-second or minute grid to demonstrate timing. Explicit archive vectors retain their frozen effective timestamps; they are never retrospectively moved into earlier intervals. Selected overlap is clipped to the requested window, but rows are eligible only when their full interval ends at or before `as_of`.

Revised vectors are available only at or after the stored UTC block's end. A revised request with an earlier `as_of` raises `ValueError`. The envelope includes `revised_available_at`; `latest_availability` includes this later estimate availability even when the requested measurement window was earlier.

Meter energy integrates finite aggregate values over eligible overlap seconds. Component energies and residuals use a common mask requiring finite aggregate plus all 24 finite component estimates. No reference channel or reference-joint mask participates. Missing timestamps, nonfinite measurements, uncompleted measurements, and missing component predictions are never filled or rescaled to complete the requested period. Energy therefore means **energy observed in available coverage**, with null when no observations exist.

Coverage fields are `requested_seconds`, `present_seconds`, `completed_seconds`, `valid_meter_seconds`, `valid_component_seconds`, `outside_block_seconds`, `absent_interval_seconds`, `not_yet_available_seconds`, `missing_meter_seconds`, and `invalid_component_seconds`. `fraction` is meter seconds / requested seconds; `component_fraction` is common valid component seconds / requested seconds. `complete` and `component_complete` reflect those separate denominators. Summary `coverage_fraction` is meter coverage; feature `coverage_fraction` is common component coverage. A comparison retains both child coverage objects and flags complete equal-duration comparisons.

Energy is `sum(W * overlap_seconds) / 3,600,000`. Average W divides observed energy by the corresponding observed seconds, not by the entire requested period. Peak W is the largest eligible interval value, not a reconstructed instantaneous peak. A span is a contiguous period of positive estimated component power with gaps kept separate. Spans are conservatively censored at both ends and are not asserted to be complete appliance programs or verified appliance states.

Residual is measured aggregate minus the sum of estimated components on common component coverage. `signed_residual_energy_kwh` retains its sign. `unexplained_energy_kwh` integrates only positive residual; `overallocated_energy_kwh` integrates the magnitude of negative residual. Positive residual includes background and unassigned demand and cannot be labeled as a particular appliance. A negative residual triggers a warning; no silent clipping makes the decomposition appear exact. Aliases `unexplained_kwh` and `overallocation_kwh` support the application.

An optional nonnegative `flat_rate_cad_per_kwh` produces an explicitly illustrative energy charge in CAD, not a real tariff or bill. Costs exclude taxes, fixed charges and tiers. Without a supplied rate, cost is unavailable. Difference is period B minus A; no intervention savings, weather normalization, or comfort effect is inferred.

## Evidence envelope and JSON safety

Every tool result has `evidence_id` (`wd_` plus a deterministic SHA-256 prefix over finite JSON evidence). `synthetic_fixture`, `input_kind`, `data_source`, and dynamic `model_version` distinguish generated demonstration from an explicitly supplied archive. `source_metadata()` provides human-readable household labels and boundaries. Window tools include `home_id`, `recording`, `block_id`, `mode`, `boundary`, `units`, `window:{start,end}`, aliases `interval_start` / `interval_end`, `as_of`, `coverage`, and provenance. `measurement_available_at` is the latest selected valid interval end. `component_available_at` is the latest online effective timestamp or revised block availability. `latest_availability` is the later of those two. `latest_estimate_effective_at` refers to a native held-vector row, not a guaranteed model change event. `evidence_content_hash` hashes only the sanitized selected arrays and model/recording/block/mode. Synthetic hashes are generated independently and contain no original source hash. Provenance hashes do not imply calibrated accuracy.

`metric_sources` classifies cards as `meter`, `nilm_estimate`, or `derived`. Summary includes mixed meter and estimate evidence; the envelope's `estimated:true` warns that component allocation is inferred, while `metric_sources` specifies each numeric field. Component energies carry per-slot label statuses. The dialogue should state coverage and identity limitations when they affect the answer. All numeric output is finite JSON or null; tool failures are `ValueError` with ordinary readable messages.

## Separate annotation registry

```python
labels.get(recording, component, model_version=selected_model_version, as_of=None)
labels.set_label(recording, component, label, status="candidate", source=None,
                 evidence=None, alternatives=None, model_version=selected_model_version,
                 available_at=None, definitive=False)
labels.propose(recording, component, label, *, source, evidence,
               alternatives=None, model_version=selected_model_version, available_at=None)
labels.confirm(recording, component, label, *, evidence,
               alternatives=None, model_version=selected_model_version, available_at=None)
```

Statuses are `unknown`, `candidate`, `occupant-confirmed`, and `verified`. Non-unknown annotations require source and evidence. An operator choosing a proposed appliance name uses `candidate` with source `prototype_operator`; this is not occupant confirmation. `confirm` records an explicit occupant source, but still sets `definitive_identity:false`. Verified identity requires `status="verified"`, source kind `independent_verification`, and independent evidence; a source assertion is recorded provenance, not automated certification of the external evidence. Unverified writes cannot request definitive identity.

Histories are isolated by home, model version, and anonymous component slot. All tools read the selected source's model version, so demo labels cannot transfer to an archive. Pass the returned version explicitly when writing annotations. `as_of` returns only annotations whose availability is no later than that time. Default annotation availability is actual current UTC time. A replay annotation should receive explicit replay availability only when the operator is simulating that event; present-day annotations must not silently leak backward into historical queries. Registry changes do not retrain or relabel upstream inference. Persistent JSON is written atomically with owner-only file mode `0600`; the server remains responsible for authentication and runtime-directory access.

## Verification

Bridge tests use synthetic native fixtures with deliberately invalid evaluator columns and masks. They check timing, clipped integration, immediate versus revised behavior, missingness, signed residuals, identity statuses, annotation time/home/version isolation, persistence permissions, and scope rejection. Demo tests prove default loading never opens an archive, generated channels are deterministic, missingness remains visible, and source versions stay isolated. External archive checks are skipped unless the operator explicitly sets `WATTDIALOGUE_ARCHIVE_ROOT`. No external archive is needed for normal tests.

`demo_data.synthetic_arrays(recording, block_id)` exposes only generated `t`, `P` (one aggregate column), `control_P_online`, and `control_P_revised`. `demo_data.write_demo_npz(root)` writes the same channels for independent arithmetic evaluation; generated output should remain outside version control. Run with NumPy installed and the prototype package on the Python path:

```sh
python3 -m unittest discover -s tests -v
```
