# V5 Reference-Response-Information Design v0

This document locks the diagnostic scoring layer that sits on top of the V5
SDE manifold architecture. It does not replace disease manifolds. It specifies
how health/reference physiology, disease stimulus, physiological response, and
information accounting are factored so ranking does not depend on one-off
disease patches.

## Object Model

```text
theta_i
  = patient background parameters:
    age, sex, pregnancy/postpartum state, chronic disease, medication,
    transplant/immunosuppression, altitude, smoking, obesity, hydration,
    fasting/sampling state, and other no-active-disease physiology modifiers.

health_reference_manifold
  = P(X | no active disease, theta_i)
  = reference distributions, normal finding prevalence, covariance, and
    modifier deformations.
  = not a diagnosis candidate.

disease_manifold
  = permanent disease geometry:
    latent mechanisms, observed axes, trajectories, couplings, hazards,
    treatments, and disease-specific risk modulation.

stimulus_field
  = disease-driven demand imposed on physiology:
    inflammatory stimulus, pathogen burden, hypoperfusion, hypoxemia,
    acidosis, bleeding/volume loss, endocrine stress, coagulation activation,
    renal perfusion pressure, and related demand fields.

response_model
  = P(response axis | stimulus_field, health_reference_manifold, theta_i)
  = expected compensation plus response-gap residuals.

information_accounting
  = explicit decomposition of evidence into health surprise, disease gain,
    stimulus evidence, response-gap information, hazard contribution, and
    posterior scoring.
```

## Factorization

Observed axes fall into two broad groups.

Direct disease axes:

```text
P(axis | disease, theta_i, phase)
```

Response axes:

```text
P(axis | expected_response(stimulus_field, health_reference, theta_i))
```

The same observed fact must not be consumed twice. If an axis is governed by an
active response model, the runtime scores it through that response model rather
than as an independent disease endpoint for the same candidate.

## Health Reference

The health reference layer owns only no-active-disease physiology:

```text
continuous reference distributions
normal finding / symptom base prevalence
axis covariance under no active disease
modifier-specific deformation by theta_i
```

Existing background modifiers for CKD, pregnancy, cirrhosis, diabetes,
immunosuppression, transplant status, and medication effects are health
reference modifiers unless the condition is itself represented as an active
disease manifold in the candidate. Condition scope prevents double counting.

Health reference does not encode disease prior, disease severity, or disease
identity.

## Disease Stimulus

Disease manifolds generate stimulus fields from mechanisms and observed
non-response evidence. Examples:

```text
sepsis mechanisms -> inflammatory_stimulus, pathogen_burden_stimulus,
                     hypoperfusion_stimulus, coagulation_activation_stimulus
hemorrhage -> volume_loss_stimulus, hypoperfusion_stimulus
DKA -> acidosis_stimulus, dehydration_stimulus
ARDS/pneumonia -> hypoxemia_stimulus
adrenal crisis -> endocrine_stress_demand
```

Stimulus inference is leave-one-out with respect to the response axis being
scored. For example, `white_blood_cell_count` must not be used to infer the
inflammatory stimulus that later judges WBC response adequacy.

## Response Models

Response models are reusable physiology modules. Initial model families:

```text
myeloid_response_to_inflammation
acute_phase_hepatic_response
thermoregulatory_response
cardiovascular_response_to_shock
ventilatory_response_to_acidosis_hypoxemia
renal_perfusion_response
coagulation_response_to_inflammation_or_bleeding
adrenal_stress_response
```

Each model declares:

```text
stimulus_axes / stimulus_mechanisms
response_axes
expected direction and adequate response range
failure branch range
minimum stimulus threshold
response gap definition
severity / hazard meaning of the gap
```

Response failure is not a standalone observation. It is a conditional residual:

```text
response_gap =
  expected_response(stimulus, health_reference, theta_i) - observed_response
```

The gap is meaningful only when stimulus evidence is present.

## Information Accounting

The runtime should expose, per candidate and per important axis:

```text
health_self_information = -log P(obs | health_reference, theta_i)
disease_direct_gain     = log P(obs | disease) - log P(obs | health_reference)
stimulus_evidence       = evidence supporting the demand field
expected_response       = model-predicted response under that demand
response_gap_information
hazard_contribution     = severity / mortality implication of response failure
posterior_score         = candidate score after reference, disease, and response terms
```

Subtracting a shared health log likelihood alone does not change disease-vs-
disease rank. It is still required for illness/OOD evidence, but disease
identity requires disease geometry plus response-model likelihoods.

## Sepsis WBC Example

```text
health_reference:
  WBC/ANC baseline depends on theta_i
  (chemotherapy, steroids, cirrhosis, age, pregnancy, etc.)

disease stimulus:
  pathogen burden + CRP/PCT + fever/chills + lactate + shock/source evidence
  infer inflammatory/pathogen stimulus

response model:
  high inflammatory stimulus predicts WBC/ANC rise unless response fails

interpretation:
  WBC normal/low + weak stimulus -> does not support sepsis
  WBC normal/low + strong stimulus -> myeloid response failure
  response failure -> severity / mortality hazard contribution
```

This is not a sepsis-specific rule. It is one instance of:

```text
danger = demand high + expected compensation high + observed compensation inadequate
```

## Migration Rules

1. Formal health reference files replace hard-coded healthy overrides where
   available. Hard-coded overrides may remain as compatibility fallback only.
2. Existing `background_modifiers.json` remains valid but is treated as health
   reference deformation, not disease geometry.
3. Disease leaves do not gain disease-specific response if-rules. They expose
   stimulus and hazard geometry.
4. Response axes that are governed by response models are scored through the
   response model for candidates with sufficient stimulus evidence.
5. Broad regression must review top-10 plausibility, not top-1 alone.
