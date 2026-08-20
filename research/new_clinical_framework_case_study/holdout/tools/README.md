# Case-blind combined pre-primary holdout seal

`build_pre_primary_holdout_seal.py` creates the atomic freeze proof that must
exist **before** a primary holdout case is selected.  It is intentionally
independent of every case-selection, article, ledger, mapping, and replay file.

## Fixed read surface

The tool can read only these fixed inputs under the study root:

1. `ARCHITECTURE_FINAL_v1.md`
2. `architecture_final_v1.schema.json`
3. `holdout/PERFECT_LANDING_GATES.md`
4. `holdout/PERFECT_LANDING_GATES.json`
5. `holdout/PERFECT_LANDING_GATES.seal.json`
6. the recursive case-blind `runtime_v2/` source tree, its final manifest and
   its final `evidence/FREEZE_SEAL.json`
7. the recursive case-blind `holdout/generic_model/` four-file tree, its pack
   and validation, plus the external final component seal
   `holdout/evidence/GENERIC_MODEL_FREEZE_SEAL.json`
8. frozen primary execution/scoring contracts, the combined-seal builder and
   its tests, deterministic selector and its tests, protocol validator, and
   strict role/complete-role-set/search/screening/mapped-observation schemas,
   plus the screening-evidence validator, schema and test source;
9. the offline raw-search compiler, raw-search validator, exact-response and
   retrieval-manifest schemas, and both test sources;
10. the conservative availability compiler, input schema and compiler tests;
11. the executable final thirty-gate scorer, exact result schema and scorer
    tests;
12. the event-ledger replay generator and tests, plus the structural-gate
    harness, tests, and evidence/result output schemas;
13. `holdout/PRIMARY_HOLDOUT_EXCLUSIONS.json`, which is constrained to an
    identifier-only schema

It never opens `CASE_SELECTION.md`, `cases/`, a primary article, an event
ledger, a case mapping, or replay evidence.  A case-shaped file discovered
inside either approved recursive source root, or referenced by the runtime
manifest (including under `runtime_v2/evidence/`), causes failure *before that
file is opened*.  Runtime manifest paths must also be canonical relative paths
strictly below `runtime_v2/`.

The gate component seal is re-derived against all four authoritative inputs:
the human-readable gate document, machine-readable gate contract, frozen
architecture document, and frozen wire schema.  Tampering with any one of the
four fails preflight.  The corrected gate contract is `1.1.0`; its
identifiability enum must exactly match the architecture wire.  The combined
seal also binds all execution, availability, isolation and final-scoring
tool/schema/test bytes.  Therefore a scorer or protocol change after sealing
fails verification just like a runtime or model change.

The primary execution binding covers generator source, test source, and output
schemas only.  It deliberately does **not** bind any generated replay bundle,
structural evidence object, or structural result bundle, because those outputs
can exist only after deterministic primary-case selection and sealed input
construction.

The selector does not trust the seal's status string or embedded payload hash
by themselves.  Before selecting, it requires the canonical seal/protocol/
exclusion paths, invokes the complete combined-seal verifier, recomputes the
canonical payload digest, and compares the actual protocol and exclusion bytes
to their exact bindings in that seal.  Runtime/model drift or a post-seal query
or eligibility edit therefore prevents selection rather than merely being
recorded after the fact.

Search completeness is executable rather than an attestation.  The scout saves
the untouched PubMed ESearch response bytes.  The offline frozen compiler binds
their canonical paths, byte counts and SHA-256 values, reconstructs the exact
Q1/Q2 HTTPS request URLs using fixed parameter order and RFC3986 encoding, and
emits capture manifests plus the canonical identifier snapshot.  The validator
reopens those exact bytes and requires first-page completeness,
`retrieved_count == len(idlist)`, exact ordered `PMID:<id>` projection and exact
canonical union before the selector may screen or select anything.

Screening claims are likewise executable rather than attestations.  The frozen
offline `validate_primary_case_screening.py` reopens the content-addressed
screening evidence index, every candidate source snapshot, every per-criterion
claim and the NCBI identity response.  It recomputes count and exclusion
criteria, requires complete candidate/criterion coverage, and rejects any
source, identity or byte-locator mismatch before selection.  The combined seal
binds this validator, its test source and
`holdout/schemas/primary_screening_evidence.schema.json`.

## Component seal contract

The final runtime component seal must contain at least:

```json
{
  "seal_kind": "runtime_v2_1_case_blind_freeze",
  "runtime_version": "2.1",
  "architecture_version": "NCF-ARCH-1.0.0",
  "case_blind": true,
  "final": true,
  "frozen_at": "ISO-8601 timestamp",
  "manifest_sha256": "64 lowercase hex"
}
```

The final generic-model component seal lives outside the four-file model
directory at `holdout/evidence/GENERIC_MODEL_FREEZE_SEAL.json` and must contain
at least:

```json
{
  "seal_kind": "generic_model_case_blind_freeze",
  "runtime_version": "2.1",
  "architecture_version": "NCF-ARCH-1.0.0",
  "case_blind": true,
  "final": true,
  "sealed_at": "ISO-8601 timestamp",
  "model_pack_sha256": "64 lowercase hex",
  "validation_sha256": "64 lowercase hex"
}
```

`model_validation.json` must have `case_blind: true`, the frozen architecture
version, `runtime_version: "2.1"`, and `status: "PASS"` or `"FINAL_PASS"`.
Its `runtime_binding` must match the exact current runtime manifest and runtime
component-seal hashes—not merely the same version label.  Thus any runtime
source change requires runtime resealing followed by generic-model
revalidation and resealing.  The generic-model component seal's recursive
`source_files` and `source_tree_sha256` must also exactly match the current
four-file model tree, so changing model documentation or validation evidence
after freeze fails closed.  Any status containing `PENDING`, `DRAFT`,
`SUPERSEDED`, `INCOMPLETE`, or `FAIL` is rejected.

The exclusion file has an intentionally narrow schema:

```json
{
  "schema_version": "NCF-PRIMARY-HOLDOUT-EXCLUSIONS-1.0.0",
  "exclusion_set_id": "pre-primary-v1",
  "excluded_case_ids": ["PMCID:...", "PMID:..."]
}
```

The combined seal stores only the exclusion-file hash and identifier count,
not the identifiers themselves.

## Commands

After selection, each isolated role manifest and the complete producer-
consumer set are validated with the same frozen protocol tool:

```powershell
python holdout/tools/validate_primary_holdout_protocol.py validate-role-manifest --input <role_execution_manifest.json>
python holdout/tools/validate_primary_holdout_protocol.py validate-role-manifest-set --input <role_manifest_set.json>
```

The set command requires the exact eight roles (including the independent
`screener`), content-addressed prompt/command, tool trace and parent packet,
canonical non-symlink artifacts, exact output-to-input producer lineage, and an
acyclic role DAG.  Self-declared classes or unattached manifests fail closed.

Before the runtime and model are final, this is expected to fail closed and
must not create an output:

```powershell
python holdout/tools/build_pre_primary_holdout_seal.py preflight
```

After both component freezes and the identifier-only exclusion list exist:

```powershell
python holdout/tools/build_pre_primary_holdout_seal.py build
python holdout/tools/build_pre_primary_holdout_seal.py verify
```

The only permitted output is:

```text
holdout/evidence/PRE_PRIMARY_HOLDOUT_SEAL.json
```

Build refuses to overwrite it.  Verification recursively rehashes both source
trees, rechecks every component seal and manifest, and re-derives the complete
combined payload.  Any byte change fails closed.

## Final primary scorer evidence

`final_primary_holdout_scorer.py` accepts only
`ncf.primary-gate-evidence.v3` evidence.  The outer evidence reference, every
source artifact, and the automated producer executable are canonical in-root,
non-symlink content references with exact `path`, `sha256`, and `bytes`.
Automated producer executables must match the exact permitted generator bytes
in the verified combined pre-primary seal, and the frozen producer policy must
permit that generator to establish the named gate or coverage subject.

Copying a permitted schema version or `produced_by` value is not producer
provenance.  Every automated evidence item must also carry a replay claim that
binds the exact producer, sealed replay policy, content-addressed input slots,
deterministic check arguments, and cited output.  The scorer calls
`producer_replay_verifier.py` to run that exact invocation in a fresh process
over isolated input copies and requires byte-identical and canonical-JSON-
identical output before it evaluates any assertion.  The verifier installs an
auditable Python socket guard and proxy-deny environment; this is an
application-level offline control, not an operating-system sandbox.

Evidence assertions are deterministic checks, not author verdicts.  Each one
names a producer-output source reference, an RFC 6901 JSON pointer, the claimed
observed value, expected value, and operator.  The scorer reloads the referenced
artifact, verifies the claimed observation, and recomputes the operator.  In
addition, every automated producer has a frozen assertion contract.  A
result-row producer must bind the unique row for the asserted subject; the
primary case evaluator must expose every one of that row's checks, with no
omissions, extras, or duplicate IDs, and the scorer recomputes each operator
before deriving the row result.  This prevents an unrelated true field in a
freshly replayed artifact from being laundered into a different gate.  A naked
`passed: true`, an unsealed producer, a forged source reference, an incomplete
subject assertion set, or a producer used outside its frozen subject scope is
`HARNESS_INCOMPLETE`.

The generic verifier also supports a sealed `NAMED_FILES` contract.  The
sanitized-runtime-ledger compiler uses it because one invocation emits both the
opaque ledger and its assignment proof; both outputs are content-addressed,
freshly regenerated, and byte/JSON compared.  Its input manifest is passed by
the sealed `VERIFIED_ORIGINAL_PATH` materialization because the manifest's own
content-addressed children are resolved under the study root.  The manifest is
verified before execution and checked for drift afterwards.

`compile_evaluator_sanitized_runtime_ledger.py` and
`verify_evaluator_sanitized_runtime_ledger.py` are upstream provenance tools
only.  Neither may mint `PL-LED-001`.  The primary case evaluator must consume
the source denominator, the sanitized ledger, the compiler assignment proof,
and the independent replay-verification artifact; it must recompute that
verification and bind both named output hashes before it can adjudicate
`PL-LED-001`.

The manual-independent-auditor policy is failure-only: a content-addressed
audit from the isolated `scorer_auditor` role may establish `FAIL`, but cannot
establish `PASS`.  If no allowed automated generator can establish a positive
gate, the scorer fails closed as `HARNESS_INCOMPLETE` rather than accepting a
manual success assertion.
