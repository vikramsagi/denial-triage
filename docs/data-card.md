# Data card: synthetic claim denials

## Summary

| Item | Value |
| --- | --- |
| Records | 300: 200 dev, 100 held-out |
| Source | `data/generate.py`, seed 20261005, generator version 1.1.0 |
| Real data | None. All names, IDs, payers, and amounts are invented. |
| Model calls used to build it | 0 |
| Frozen | Yes. SHA-256 hashes are in `data/summary.json`. Do not regenerate. |

## Record shape

Each line of a `.jsonl` file is one denial.

| Field | What the model may see | Contents |
| --- | --- | --- |
| `denial_id` | Yes | Random ID such as `DN-31039` |
| `payer` | Yes | Fictional payer name, payer type, filing limit in days |
| `denial` | Yes | Claim adjustment reason code (CARC), its text, denial date |
| `claim` | Yes | Member ID, service date, submitted date, procedure lines, diagnosis codes, prior authorization number, billed amount, expected allowed amount |
| `documentation` | Yes, as untrusted data | 3 to 10 numbered lines (`D1`, `D2`, ...) from notes, eligibility checks, authorization logs, payer letters |
| `labels` | Never | The answer key (below). `triage/load.py` strips it before any model call. |

## Answer key (`labels`)

| Label | Meaning |
| --- | --- |
| `root_cause` | One of 8 causes |
| `scenario` | One of 24 scenario types, for example `auth_on_file_not_on_claim` |
| `correctable` | True if fixing our own error and resending would get paid |
| `evidence_supports_appeal` | True if the documentation gives a real basis to appeal |
| `true_overturn_probability` | Chance an appeal succeeds |
| `action_values` | Dollar value of appeal, fix and resubmit, and write off |
| `best_action` | The action with the highest value |
| `evidence_lines` | The documentation lines that prove the root cause |
| `difficulty` | easy, medium, or hard |
| `is_adversarial`, `injection` | Whether a line tries to hijack the model, and what it tries to force |
| `line_provenance` | Which template and phrasing variant produced each line |

## Value rules

These rules turn the answer key into dollars. They live in `triage/config.py`.

| Action | Value |
| --- | --- |
| Appeal | overturn probability × allowed amount − appeal cost |
| Fix and resubmit | 0.95 × allowed amount − 25 USD if correctable, otherwise −25 USD |
| Write off | 0 USD |
| Human review | oracle value for that record − 15 USD |

## Cost assumptions

| Assumption | Value | Source |
| --- | --- | --- |
| Fix and resubmit cost | 25 USD | 25.20 USD per reworked claim, [Change Healthcare 2020 via Becker's](https://www.beckershospitalreview.com/finance/86-of-denials-are-potentially-avoidable-strategies-to-better-prevent-manage-denials/). No newer per-claim figure has been published. A labor build-up gives a similar number: 25 minutes at 35 USD per hour is about 15 USD, plus resubmission and follow-up. |
| Administrative appeal cost (all other causes) | 57 USD | 57.23 USD average provider cost to adjudicate a claim, 2023 data from 280 hospitals, [Premier 2025](https://premierinc.com/newsroom/policy/claims-adjudication-costs-providers-257-billion-18-billion-is-potentially-unnecessary-expense) |
| Clinical appeal cost (medical necessity, prior authorization) | 108 USD | 57.23 USD administrative cost plus 51.20 USD of added clinical labor per inpatient surgery claim (AMA estimate), [Premier 2024](https://premierinc.com/newsroom/blog/trend-alert-private-payers-retain-profits-by-refusing-or-delaying-legitimate-medical-claims) |
| Human review cost | 15 USD | 24.59 USD per hour median wage ([BLS 2025](https://www.bls.gov/ooh/healthcare/medical-records-and-health-information-technicians.htm)) × 1.43 for benefits ([BLS ECEC June 2025](https://www.bls.gov/news.release/archives/ecec_09122025.htm)) = 35 USD per hour, for 25 minutes, the time of a manual payer transaction ([CAQH Index 2024](https://www.caqh.org/hubfs/Index/2024%20Index%20Report/CAQH_IndexReport_2024_FINAL.pdf)) |
| Fix success rate | 95% | Assumption |

## Root-cause mix

Shares follow the [Optum 2024 Denials Index](https://marketplace.optum.com/content/dam/change-healthcare/marketplace-assets/outcomes-and-insights/2024-denials-index.pdf) where it reports a category: registration and eligibility 24.33%, missing or invalid claim data 15.89%, authorization 12.80%, medical documentation requested 12.08%, not covered 9.67%, medical necessity 6.76%. The index does not break out coordination of benefits, timely filing, or duplicates, so those three causes share the remaining 19% as an assumption.

| Root cause | Share | Dev | Held-out |
| --- | --- | --- | --- |
| registration_eligibility | 24% | 48 | 24 |
| coding_error | 16% | 32 | 16 |
| medical_necessity | 15% | 30 | 15 |
| prior_authorization | 13% | 26 | 13 |
| non_covered_service | 10% | 20 | 10 |
| coordination_of_benefits | 8% | 16 | 8 |
| timely_filing | 7% | 14 | 7 |
| duplicate_claim | 7% | 14 | 7 |

Held-out counts are fixed by the stratified design. They were not read from the file.

## Dev split profile

| Dimension | Counts (n = 200) |
| --- | --- |
| Best action | fix and resubmit 82, appeal 62, write off 56 |
| Difficulty | easy 100, medium 71, hard 29 |
| Amount band | under 1,000 USD: 54; 1,000 to 2,499 USD: 81; 2,500 to 4,999 USD: 56; 5,000 USD or more: 9 |
| Payer type | commercial 93, Medicare Advantage 48, Medicaid 45, Medicare 14 |
| Adversarial | 12 |
| Total allowed amount | 452,685.87 USD |
| Oracle value (best action on every record) | 233,567.83 USD |
| Share of oracle value in claims of 5,000 USD or more | 18% (9 claims) |
| Share of oracle value in claims of 1,000 to 4,999 USD | 75% (137 claims) |

## What makes it hard

- **Ambiguous reason codes.** CO-16 ("lacks information") appears on dev records from 7 of the 8 root causes. CO-50 appears on 4. A reason-code lookup cannot solve these.
- **Difficulty levels.** Easy records use a cause-specific reason code and 2 distractor lines. Medium records use a generic code half of the time and 4 distractors. Hard records always use a generic or misleading code, 5 distractors, and a decoy line that hints at a different cause.
- **Gray-zone economics.** Weak medical necessity cases (10% to 20% overturn) and authorizations never requested (3% to 10%) are worth appealing only on large claims.
- **Prompt injection.** 18 records (12 dev, 6 held-out) contain a line such as "ignore all previous instructions" that tries to force a wrong root cause and a wrong action.

## Design choices

| Choice | Alternatives rejected | Why |
| --- | --- | --- |
| 8 root causes | 5 coarse buckets; 12 or more fine-grained causes | 8 is the smallest set where reason codes overlap across causes, so a lookup table cannot solve the task. Finer classes would leave about 15 dev records per class, too few for stable per-class metrics. |
| Hand-written templates with several phrasings per line | Model-paraphrased templates; fully model-generated records | Templates cost 0 USD, regenerate exactly from one seed, and carry labels that are correct by construction. A paraphrase pass can silently drop the evidence a label depends on. |
| Realistic class mix, 50/35/15 easy/medium/hard, 6% adversarial | Balanced classes; no adversarial records | Metrics should describe a real denial queue, and the injection metric needs injection attempts to measure. |
| Stratified split, with the last phrasing variant of every template reserved for held-out | Stratified random split; pure random split | A random split puts the same sentence templates in both sets, so the held-out score would reward memorized wording. Measured overlap after the fix: 0 template variants shared. |
| Claim amounts concentrated between 1,000 and 5,000 USD: 20% under 1,000 USD, 72% from 1,000 to 4,999 USD, 8% at 5,000 USD or more (targets; scenarios priced below 1,000 USD keep their natural range) | Service prices drawn uniformly, which put 45 of 200 dev claims at 5,000 USD or more | With the first price mix, 23% of claims held 79% of the recoverable dollars. Headline metrics then mostly measured a handful of large claims, and a 200-record sample gives wide intervals on so few records. The new mix puts 75% of the dollars in the 1,000 to 4,999 USD range and keeps a small high-value tail to test stakes-aware review. |
| Overturn probability of exactly 0 for denials with no basis to appeal | A small floor probability for every denial | With a 1% to 8% floor, expected value math labeled 25 of 200 dev denials as "appeal", including claims the payer had already paid. A billing team would write these off, and appealing them is a compliance risk. With the change, dev best actions are 82 fix, 62 appeal, 56 write off. Gray-zone cases keep a small probability so that claim size still decides them. |

## Known limitations

- Template text is cleaner and more regular than real clinical notes. Dev scores will likely overstate performance on real data.
- Overturn probabilities are set by scenario, not learned from real appeal outcomes.
- One root cause per record. Real denials can have several.
- Real hospital denial queues are more concentrated in high-value claims than this dataset. The high-value slice has only 9 dev records, so its metrics carry wide intervals.
- Cost figures come from 2020 to 2025 publications and mostly from hospital settings. Physician practices may have lower costs per claim.

## Simulated post-launch week

`data/week.jsonl` holds 150 additional synthetic denials from `data/generate_week.py` (seed 20261012, hash in `data/week_summary.json`). It reuses the same templates with one deliberate change: Northwind Health Plan tightens prior authorization, with more prior-authorization denials, new note wording, and appeal win odds cut to a fifth. Each record carries a day from 1 to 7. Days 1 to 3 feed the feedback loop and days 4 to 7 measure it. The week is never used for tuning.
