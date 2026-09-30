# Data and privacy

The cloneable demo generates deterministic synthetic aggregate and anonymous component traces. Synthetic appliance-like patterns are invented fixtures, not measured homes, labelled NILM findings or validation data. The display names their source explicitly.

Actual saved HyNILM outputs can be replayed only through an explicitly supplied `--source-root`. The adapter exports aggregate power and anonymous component estimates; it excludes submeter references, appliance-reference labels and the joint reference-dependent validity mask. Immediate and revised results retain different availability rules. Anonymous activity can still reveal household routines.

Research recordings, replay bundles, generated questions/targets/manifests and experimental response logs are not committed. The optional exporter creates a separate local bundle and preserves the original files. GPL licensing of the code does not grant rights to household recordings or upstream datasets.

API credentials belong in ignored `.env.local` or server environment variables. Only the blank `.env.example` is tracked. The HTTP service exposes only its allowlisted UI and API responses. It does not serve environment files, source directories, labels on disk or private benchmark targets. API keys remain on the server.

Cloud processing is off by default and requires explicit session consent. Its payload contains the question, declared context and relevant deterministic tool summaries. The API requests use `store: false`; this setting is not a claim of zero provider retention. Local summaries remain available without cloud consent. Cached summaries remain old evidence and cannot establish current appliance activity.

The server binds to loopback and uses session-scoped recording selection and request tokens for this research demo. A hosted utility service needs its own production authentication, retention policy and provisioned network/device design.
