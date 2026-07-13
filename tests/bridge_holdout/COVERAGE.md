# Hidden bridge holdout coverage matrix

`X` means the case has a decisive oracle for the dimension, not merely incidental fields.

| Case | root | dependence | scope | time | versions | uncertainty | measurement | query | filter_smooth | condition_do_aap | delta | tamper | negative | order | taint |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H01 | X | X | X | X | X | X |  |  |  |  |  |  |  |  |  |
| H02 | X | X | X | X | X |  |  |  |  | X |  |  |  |  |  |
| H03 | X | X |  |  |  |  |  |  |  |  |  |  |  | X |  |
| H04 | X | X |  |  |  |  |  |  |  |  |  |  | X |  |  |
| H05 | X | X |  |  |  |  |  |  |  |  |  | X |  |  |  |
| H06 |  |  |  | X |  |  |  |  |  |  |  |  |  |  |  |
| H07 |  |  |  | X |  |  |  |  |  |  |  |  | X |  |  |
| H08 |  | X |  | X |  | X |  | X | X |  |  |  |  |  |  |
| H09 |  |  |  |  |  |  |  | X | X |  |  |  |  |  |  |
| H10 |  |  |  | X |  |  |  |  |  |  |  |  | X |  |  |
| H11 |  |  |  |  | X |  |  |  |  |  |  |  |  |  |  |
| H12 |  |  |  |  | X |  |  |  |  |  |  |  | X |  |  |
| H13 | X | X |  |  | X |  |  |  |  |  | X |  |  |  |  |
| H14 |  |  |  |  | X |  |  |  |  |  |  |  | X |  | X |
| H15 |  |  |  |  | X |  |  |  |  |  |  | X | X |  |  |
| H16 |  | X |  |  |  | X |  |  |  |  |  |  |  |  |  |
| H17 |  | X |  |  |  | X |  |  |  |  |  |  |  |  |  |
| H18 |  |  |  |  |  |  | X |  |  |  |  |  | X |  |  |
| H19 |  |  |  |  |  |  | X |  |  |  |  |  | X |  | X |
| H20 |  |  |  |  |  |  |  | X |  | X |  |  |  |  |  |
| H21 | X | X |  |  |  |  |  | X |  | X |  |  |  |  |  |
| H22 |  |  |  | X |  |  |  |  |  | X |  |  | X |  |  |
| H23 |  |  |  | X |  |  |  |  |  | X |  |  | X |  |  |
| H24 |  |  | X |  |  |  |  |  |  |  |  |  | X |  |  |
| H25 |  |  |  |  | X |  | X |  |  |  |  | X | X |  |  |
| H26 |  |  |  |  |  |  |  |  |  |  |  | X | X |  |  |
| H27 |  |  |  |  |  |  |  |  |  |  |  |  |  | X |  |
| H28 |  |  |  | X | X |  |  |  |  |  |  |  |  | X |  |
| H29 | X | X |  | X | X | X |  | X | X |  | X |  |  |  |  |
| H30 | X | X |  | X | X | X |  | X |  | X | X |  |  |  |  |
| H31 |  |  |  |  |  |  |  | X | X |  |  |  | X |  |  |
| H32 | X | X |  |  |  | X |  |  |  |  |  |  | X |  |  |
| H33 |  |  |  | X | X |  |  |  |  |  | X |  |  |  |  |
| H34 | X | X |  |  | X |  |  |  |  |  | X |  | X |  |  |
| H35 | X | X | X |  |  |  |  | X |  | X |  |  | X |  |  |
| H36 | X | X | X |  |  |  |  |  |  |  |  |  | X |  |  |
| H37 | X | X |  | X |  |  |  |  |  |  | X |  |  |  |  |
| H38 |  | X |  |  |  | X | X | X | X |  |  |  | X |  |  |
| H39 |  |  |  | X |  |  |  | X |  |  |  |  | X |  |  |
| H40 |  |  |  |  |  |  |  | X |  | X |  |  | X |  |  |
| H41 | X | X |  |  |  | X |  |  |  |  |  |  | X |  |  |

## Expected failure modes

- root alias/path multiplication; value-based dedup of true repeats; synthetic bridge roots
- clock-role collapse, off-by-one eligibility, future leakage, target-window mismatch
- current-version fallback, last-write-wins forks, stale/unkeyed caches
- aleatoric/epistemic/measurement collapse or failure taint laundering
- filter implemented as smooth (or vice versa), query labels without distinct semantics
- conditioning used for do, action forecast labeled do, AAP resampling exogenous worlds
- planned action treated as performed; cross-subject/specimen/semantic-scope coercion
- censor/interval/masked states flattened; hidden unit or nearest-concept conversion
- raw payload used as semantic input; digest/vector tamper accepted; oracle-field dispatch
- alias or registration order affects semantics; incremental result differs from clean rebuild
- DBN target not bound to the compiled state; query time outside the frozen target window
- one root or one dependence family counted twice through aliases/duplicate records
- post-cut correction/retraction leaks backward; self/cycle/fork supersedes is arbitrated by order
- SCM population selector is ignored, or exogenous/endogenous names shadow one another
- encounter/specimen mismatch degrades to subject-only matching; empty dependence family implies independence
- absent/censored evidence is silently skipped and a prior is returned as a successful posterior
