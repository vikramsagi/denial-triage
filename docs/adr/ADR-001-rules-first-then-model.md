# ADR-001: Rules first, model only where rules cannot decide

Date: 2026-10-07
Status: accepted

## Context

Some denials can be settled from structure alone: a member ID with two swapped digits, an authorization number on file but missing from the claim, a submission date inside the filing window. Others need the documentation read. A model call on every denial costs money and adds variance. A rule that misfires is never checked again.

## Options

- **A. Model for everything.** Simplest pipeline. Pays for a model call on denials that structure already settles.
- **B. Structural rules, then the model.** Rules read only IDs, codes, and dates, never wording. Anything else goes to the model.
- **C. Structural plus keyword rules, then the model.** Rules also match words such as "retro", "excluded", or "ended".

## Decision

Option B.

## Evidence

On the 200 dev denials ([run file](../../evals/runs/20261007T133827Z-dev-b2_rules_ev.json)):

| Rule set | Denials settled by rules | Settled correctly |
| --- | --- | --- |
| Structural only (B) | 57 | 57 |
| Structural plus keyword (C) | 142 | 123 |

Keyword rules settled 85 more denials but got 19 wrong, and those 19 never reach the model. Example: on a denial where the patient's own coverage had ended, the word "ended" matched the rule for "other coverage ended, appeal", which routed a 57 USD appeal on a claim that cannot be won. Keyword rules were also tuned on dev wording, while the held-out split uses phrasings the rules have never seen.

The 85 extra model calls that option B makes compared with option C cost about 0.45 USD on dev, so cost does not decide between B and C.

The rules were written with knowledge of how the synthetic data is built, so 57 of 57 overstates real-world precision. This is why they match formats only.

**Option A against option B on the same 200 denials.** Both runs use Claude Haiku 4.5 with thinking and prompt version 3, scored with the current win odds table ([rules first](../../evals/runs/20261007T162445Z-dev-m_rules_small_think-replay.json), [model for everything](../../evals/runs/20261007T162454Z-dev-m_all_small_think-replay.json)).

| | B. Rules first | A. Model for everything |
| --- | --- | --- |
| Model calls | 143 | 200 |
| API cost per denial | 0.0053 USD | 0.0073 USD |
| Root cause correct | 94.5% (91.0 to 97.5) | 96.0% (93.0 to 98.5) |
| Value captured | 98.9% (97.5 to 99.9) | 99.9% (99.8 to 99.9) |
| Dollars lost on the 57 denials rules can settle | 15 USD | 140 USD |
| Dollars lost on the 143 denials only the model reads | 2,491 USD | 204 USD |

The two rows that matter point in different directions, and only one of them is about rules.

- **On the 57 denials rules can settle, rules are better.** Rules settled all 57 correctly. The model, reading the same 57, marked 5 true duplicate claims as fixable and resubmitted them, losing 25 USD each.
- **On the other 143 denials, the two runs used the same model, prompt, and input.** The gap there is run-to-run variance, not a property of either option. 6 of the 143 denials (4%) received a different route in the two runs, and those 6 explain the whole 2,287 USD difference. The largest single swing is a 1,481 USD medical necessity denial where records had not been sent: one run appealed it (worth 342 USD), the other fixed and resent it (worth 1,481 USD).

So the comparison does not show that model for everything is better. It shows that rules are more accurate on the denials they cover, that they cost 27% less in API calls, and that model variance is now the largest source of lost value. Variance is measured and addressed in the evaluation suite: repeated runs of the same configuration, and a confidence cutoff that sends unstable decisions to a person.

## Consequences

- Easier: 29% of denials need no model call, and the rules give the same answer every run.
- Harder: two paths to test and monitor. Rule coverage is limited until payer-specific rule packs exist.
- Found while running this comparison: the model sometimes calls a true duplicate fixable. Rules catch the most common form of duplicate before the model sees it.

## Revisit when

- A rule resolves a denial incorrectly in monitoring or on held-out.
- The share of denials settled by rules drops, which would signal a change in claim formats.
- Payer rule packs make more structural signals available.
- The model stops calling true duplicates fixable, and repeated runs show its variance is small. Model for everything would then be simpler at a cost of about 0.002 USD per denial.
