# Evidence -> model bridge hidden holdout (private preregistration)

Status: private design only. Do not copy into the repository before both
implementations are sealed. The checked-in corpus is generated after sealing,
with a fresh seed and opaque aliases.

## Experimental unit

Each implementation must independently provide both targets:

```
compile_dbn(cut, bridge, model, query) -> native_ir + bridge_witness
decode_dbn(native_ir, bridge_witness)  -> audit_envelope
run_dbn(native_ir, query)              -> typed_outcome

compile_scm(cut, bridge, model, query) -> native_ir + bridge_witness
decode_scm(native_ir, bridge_witness)  -> audit_envelope
run_scm(native_ir, query)              -> typed_outcome
```

The judge compares A vs hidden oracle, B vs hidden oracle, A vs B, and each
round trip vs the authority snapshot. The two implementations may share only
the frozen wire schema. They may not share parser, canonicalizer, bridge code,
solver, or reference implementation.

## Equivalence, not representation identity

Round-trip equality is audit-semantic isomorphism, not byte equality of native
IR. Exact fields are root occurrence/version, artifact/logical version, scope,
all clock roles, raw digest/span/mapping version, value variant, dependency
families, complete version/snapshot vector, query constructor, uncertainty
semantics, and materialized/consumed source-proof mapping. Proof/native node IDs
may be alpha-renamed and unordered maps/lists may be canonically reordered, but
shared premises, alternative proofs, and the root set must remain isomorphic.

Native finite probability results are judged by independent enumeration with
absolute tolerance 1e-12. Positive fixtures do not accept `unsupported`.
Negative fixtures require typed failure and `native_invoked=false`; an exception,
empty output, or generic green status is not a pass.

## Hidden corpus groups

| ID | Scenario | Decisive oracle | Principal mutation killed |
|---|---|---|---|
| H01 | DBN baseline, one frozen cut | audit round trip exact; exact posterior | partial witness |
| H02 | SCM baseline, factual roots | audit round trip exact; exact condition/do/AAP | causal bypass |
| H03 | one root through aliases and fan-out/fan-in | one occurrence root; proof DAG isomorphic | path-count voting |
| H04 | two true same-slice observations on singleton port plus time-series control | singleton typed ambiguous; declared time-series keeps both | latest-wins / universal refusal |
| H05 | raw canary perturbation | model value unchanged; raw digest/audit changes; no synthetic raw root | raw semantic leak / bridge root minting |
| H06 | available-at boundary and +epsilon future | boundary included; future excluded | `<`/`<=` error, future leak |
| H07 | half-open effective end and unknown clock | end excluded; unknown not guessed | interval error / clock collapse |
| H08 | same snapshot, past target, informative later observation | filter uses prefix; smooth uses later evidence; values and operators differ | smoothing-as-filter |
| H09 | no informative later evidence | values may equal; operator/value-kind/policy witness differ | label-only equivalence judge |
| H10 | upstream/downstream target-window mismatch | typed cut mismatch before model invocation | outer root pasted over empty model run |
| H11 | evidence/model/bridge v1-v2 replay modes | old as-then and new reinterpret differ; roots unchanged; versions exact | current-version fallback |
| H12 | bridge registered after cut / unavailable model version | typed version unavailable | version string echo |
| H13 | correction, retraction, alternative support | incremental == clean rebuild; old cut stable; witness shrinks only | stale cache / over-delete |
| H14 | unresolved version fork | conflicting versions, never last-write-wins | transaction-order arbitration |
| H15 | incompatible schema without migration | typed migration/schema failure; raw retained | silent coercion |
| H16 | all uncertainty channels together | aleatoric, epistemic, measurement blocks exact and distinct | one `confidence` scalar |
| H17 | mutate one uncertainty channel at a time | only declared semantic path changes | channel conflation |
| H18 | BelowDetection vs Exact(0), Interval vs midpoint | discriminated value variants; no scalar collapse | censor/midpoint fabrication |
| H19 | masked, absent, unknown, local conflict | states stay distinct; masked payload not leaked; taints survive | absence inference / taint wash |
| H20 | confounded finite SCM | condition sign and value differ from population do | conditioning-as-do |
| H21 | factual abduction + shared-world counterfactual | AAP differs from population do and uses factual roots | exogenous resampling |
| H22 | missing shared-world policy / factual root not visible | not-identified or insufficient, no population-do fallback | AAP label substitution |
| H23 | planned vs performed action; forecast vs do | plan has no effect; receipt does; forecast and do distinct | planned-as-performed / forecast-as-do |
| H24 | cross subject/specimen and illegal role upgrades | fail before consume | scope crossing / knowledge-as-action |
| H25 | unknown alias/method/unit and legal conversion control | raw+typed quarantine; legal conversion has versioned inverse audit | nearest match / hidden unit conversion |
| H26 | digest/version-vector/oracle-field tamper | integrity/closed-schema failure | tamper acceptance / oracle leakage |
| H27 | opaque alpha-renamed vocabulary + shuffled modules | semantic results isomorphic; root IDs remain their own | name/order dispatch |
| H28 | warm future/new-version cache then old-cut query | old warm == old cold | unkeyed cache |
| H29 | state cross: correction + later evidence + v2 + three uncertainties | exact smooth/round trip + incremental clean equality | interaction-only defect |
| H30 | causal cross: two factual roots + versions + uncertainty + AAP | exact AAP/roots/versions/taints | interaction-only causal defect |

## Post-seal adversarial audit addendum

The following cases were added only after the four candidate source files were
sealed, but before fixture generation or candidate execution.  They came from
independent static review of the frozen APIs.  They therefore cannot have been
used to tune the candidates and are reported separately from H01--H30.

| ID | Scenario | Decisive oracle |
|---|---|---|
| H31 | DBN query target is unknown or cross-bound | typed `query_target_unbound`; no posterior under the wrong target |
| H32 | duplicate records share a root or dependence family | same root equals one likelihood; same-family needs a declared joint model or refusal; independent-family control remains live |
| H33 | correction registered after transaction cut | old cut equals clean pre-correction build; new root is not consumed |
| H34 | self/cyclic/forked supersedes graph | typed graph/version conflict; never last-write-wins |
| H35 | SCM `do` population selector | selector evidence roots are consumed, or the query is typed unsupported; silent full-population fallback is forbidden |
| H36 | same subject but different encounter/specimen | fail closed before consumption |
| H37 | correction and retraction both post-cut | both invisible at old cut; later cut applies transaction order |
| H38 | absent and censored DBN evidence | effective typed likelihood or typed refusal; returning a green prior after skipping is forbidden |
| H39 | query time outside target window | typed cut/query mismatch before native invocation |
| H40 | SCM exogenous/endogenous symbol collision | typed causal namespace failure; no environment shadowing |
| H41 | empty dependence-family set | typed missing-dependence failure; no implicit independence |

## Randomized finite models

### DBN/SSM

Binary hidden state over three slices. A hidden finite model-member index is
fixed across time and represents epistemic parameter uncertainty. Each member
has a stochastic transition matrix (aleatoric uncertainty); observations use a
binary confusion matrix and method/version metadata (measurement uncertainty).
The frozen evidence is `Y0=0, Y1=0, Y2=1`, where `Y2` is available only after
the target. Parameter bands are chosen so that the hidden oracle verifies:

```
abs(P(X1=1 | prefix) - P(X1=1 | prefix,Y2)) >= 0.04
```

The generator enumerates `(member, X0, X1, X2)` and rejects seeds that do not
meet the margin. A performed action selects an explicitly separate transition
and/or observation channel; a plan does neither.

### SCM

The SCM is an opaque, finite possible-world table with columns `(weight,
observed_T, potential_Y0, potential_Y1)`. A seed jitters the preregistered count
template `[30,15,5,5,5,15,5,20]` and is accepted only if:

```
P(Y=1|T=1) - P(Y=1|T=0) > 0.10
P(Y=1|do(T=0)) - P(Y=1|do(T=1)) > 0.10
P(Y_do0=1 | factual T=1,Y=1) - P(Y=1|do(T=0)) > 0.10
```

This creates observational confounding, a beneficial population intervention,
and a distinct same-unit AAP result without relying on meaningful variable
names. The oracle enumerates worlds directly.

## Reveal and hashing

1. Seal A and B source trees; record sorted path+SHA256 manifest and aggregate
   digest for each implementation.
2. Draw a fresh 256-bit seed after both seals.
3. Generate aliases, parameters, model-member/world order, module registration
   order, and an alpha-renamed isomorphic copy.
4. Write canonical UTF-8 JSON (`sort_keys=True`, compact separators, no NaN,
   trailing LF) plus a separate exact-byte `.sha256` file to avoid self-hash.
5. Record seed, generator digest, A/B seal digests, and reveal timestamp in the
   fixture metadata. Any implementation source change after reveal creates a
   new experimental run, not a continuation of the sealed run.

## Required report vector

No total score may compensate a hard failure. Report independently:

- hard assertion pass/fail by semantic dimension;
- A-vs-B disagreement count and rate;
- round-trip field loss/corruption count;
- exact finite numeric error by query;
- mutation kill matrix;
- adapter non-comment LOC and closed transform/opcode count;
- manually declared mappings, unit conversions, clock policies, likelihoods,
  identification assumptions, and shared-world policies;
- compile/decode/run p50 and p95 latency, trace bytes/nodes;
- incremental-vs-clean mismatch count;
- extension blast radius: core files/branches/schema migrations changed.
