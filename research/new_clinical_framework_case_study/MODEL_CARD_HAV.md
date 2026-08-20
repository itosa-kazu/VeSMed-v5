# HAV / cardiac-process blind generic model card

## Outcome

`models/hav_takotsubo_generic_model.json` is an **experimental, uncalibrated model hypothesis** for the new clinical dynamic-map framework. It supplies topology, branch-local charts, four operating modes, a typed factor graph, wide ordinal likelihood assumptions, action-conditioned constraints, action memory, and an open-world branch. It is not a diagnostic model, a treatment policy, or evidence for clinical effectiveness.

## Blind boundary

Clinical branch semantics and parameter assumptions were restricted to the candidate process names listed in the JSON and general medical knowledge; generic state/factor/dynamics contracts follow this experiment's framework specification. The model was not parameterized from case-specific values, a case event stream, PMC7005653 text/tables, VeSMed V5 distillations/runtime output, or an expected rank/forecast/action result.

The package intentionally contains:

- no case identifiers or case-specific timestamps;
- no laboratory, ejection-fraction, pressure, dose, or support cut-points;
- no disease-specific score bonuses or action-to-diagnosis shortcuts;
- no claim that co-occurring hepatic and cardiac processes have a known causal direction.

The JSON is a prior hypothesis that must be frozen before replay against any held-out event ledger. Any change after replay must be versioned and classified as a model revision, not silently treated as blind evidence.

## Model structure

- **Topology:** hepatic, cardiac, hemodynamic-instability, and open-world families with explicit sibling and concurrency bridges. Cross-branch Euclidean averaging is forbidden.
- **Local coordinates:** each candidate has its own chart; shared concepts retain the same identifiers where they are genuinely shared.
- **Modes:** `compensated`, `strained`, `decompensated`, and `recovering` alter drift and transition behavior. Exit from decompensation uses hysteresis.
- **Factor graph:** AST, ALT, and their derived transaminase summary share one hepatocyte-injury latent. Troponin, ejection fraction, and wall motion are conditional emissions from shared cardiac-injury/pump latents. Pressure, perfusion, and support share perfusion/support latents.
- **Likelihoods:** only broad ordinal ranges are stated. They are uncalibrated interval hypotheses, and midpoint-only evaluation is forbidden.
- **Actions:** abstract action classes test controlled dynamics. Only performed actions affect state; support may mask observations but cannot identify a disease branch.
- **Unknown branch:** retains nonzero open-world mass and reports residuals without a hard diagnostic threshold.

## Key evidence and audit hooks

The model requires per-cut state hashes, event digests, branch/mode posterior, unknown mass, latent summaries, one contribution per redundancy group, forecast intervals, and constraint flags. Required ablations remove mode, topology, shared factors, history, action memory, or the unknown branch.

The decisive anti-double-counting rules are:

1. when AST and ALT are used, the derived transaminase summary adds no independent likelihood;
2. troponin, EF, and wall motion are not three independent votes;
3. support intensity changes measurement context and action memory but is not disease-identity evidence.

## Limitations

1. No probability, transition, or action-effect parameter is calibrated.
2. Candidate names do not identify individual causal direction, treatment response, or prognosis.
3. The candidate set is incomplete; unknown mass is therefore essential.
4. Several different cardiac processes can generate overlapping troponin, EF, and wall-motion observations. The graph preserves this ambiguity rather than resolving it by label.
5. Transaminase magnitude does not uniquely establish hepatic cause or current functional reserve.
6. Abstract support actions omit clinically important device, dose, timing, contraindication, and adverse-effect detail.
7. Registered hepatic-plus-cardiac concurrent sets are representational possibilities, not claims that one process caused the other.
8. A single case replay can establish structural executability or case consistency only. It cannot establish calibration, generalization, comparative effectiveness, or an individual counterfactual.

## Unidentified causal edges

The JSON explicitly marks as unidentified: progression from hepatocellular injury to liver failure in an individual; hepatic-to-cardiac causation; stress-to-Takotsubo causation; abstract etiologic-action effects; support-to-recovery/survival effects; and causal direction in hepatic/cardiac co-occurrence.

## Verification

Before use, validate JSON syntax and schema, compute a content digest, freeze it, then replay a held-out typed event ledger without editing this version. Report sensitivity across admitted ordinal intervals and all required ablations. A result should be labelled only `STRUCTURALLY_SUPPORTED`, `CASE_CONSISTENT`, `FAILED`, or `UNIDENTIFIABLE` under the experiment protocol.
