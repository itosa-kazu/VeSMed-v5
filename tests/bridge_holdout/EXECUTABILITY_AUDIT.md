# Hidden bridge corpus executability audit

## Outcome

The fixture bytes and source seals are reproducible, but **41 case descriptors
are not 41 executable hidden fixtures**.  The current file contains one DBN
base, one SCM base, five concrete query objects, exact finite oracles, and prose
mutation/oracle descriptors.  A descriptor is not promoted to a candidate
PASS/FAIL unless a separate deterministic probe supplies the complete input.

## Key evidence

Run:

```powershell
python tests/bridge_holdout/audit_corpus_executability.py
```

Current machine audit:

- directly specified base cases with non-dangling queries: `H01`, `H02`,
  `H08`, `H16`;
- descriptor-only mutation cases: 35;
- dangling query references:
  - `H09`: `smooth_t1`;
  - `H20`: `condition_t0`, `do_t1`;
  - `H21`: `aap_do_t0_given_factual_t1_y1` (the base uses
    `aap_t0_given_t1_y1`).

Important omissions include a concrete v2 registry for `H11`, delta/event
graphs for `H13`/`H33`/`H37`, a complete alpha-renamed copy for `H27`, and the
combined cross fixtures for `H29`/`H30`.  `COVERAGE.md` records intended
decisive dimensions; it does not provide the missing inputs or an executable
oracle.

## Verification boundary

The immutable corpus remains authoritative and is not repaired in place:

- corpus SHA-256:
  `9ed638f0f6d5b5db688f40581b4bb659bb1b6df29e377048fa628b970944f309`;
- freeze-manifest SHA-256:
  `1eeddf4db162ae5c255e79d621785f912aa783382c794707cc46d8996b4ad6cb`.

The stronger preregistration wording is used for base numeric checks even where
the short case descriptor omitted the numeric assertion.  The complete corpus,
including `hidden_oracle`, is never passed to a candidate; each runner may pass
only the projected authority/model/cut/query slice.

Every result uses one of these non-compensating classifications:

- `PASS`: a concrete input was losslessly projected and every hard assertion
  passed;
- `CANDIDATE_FAIL`: a valid lossless projection reached the frozen candidate
  and violated the oracle;
- `ADAPTER_UNREPRESENTABLE`: the frozen candidate schema cannot express the
  portable semantics using the permitted projection operations; this is a hard
  preservation non-pass, not a runtime bug;
- `HARNESS_INCOMPLETE`: the fixture, oracle, lowering, or instrumentation is not
  concrete enough to attribute a result to the candidate;
- `POST_SEAL_EXTERNAL_PROBE`: a deterministic adversarial probe created after
  seal/reveal.  It is useful falsification evidence but is never relabeled as a
  preregistered hidden fixture.

Adapter-side oracle-aware rejection is not a candidate PASS.  A recovered
field may not be filled from the authority snapshot or an opaque canonical echo
after the frozen candidate dropped it.

## Next step

Preserve the first executable base run and post-seal destructive probes as
separate, hashed evidence.  A future full 41-case run requires an append-only
operational probe pack with complete portable subcases, machine predicates,
independently frozen A/B lowerings, and a new run ID; it must not overwrite this
corpus or first-pass evidence.
