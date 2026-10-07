# Assumptions log

Every number or rule that the results depend on but that was not measured directly. Each entry says where it is used, why the value was chosen, and how to test whether it matters. When an assumption changes, the old value moves to the change history at the bottom.

## Economics

| ID | Assumption | Value | Where used | Basis | How to test it |
| --- | --- | --- | --- | --- | --- |
| A1 | Cost of an administrative appeal | 57 USD | `triage/config.py`, answer key, router | 57.23 USD average provider cost to adjudicate a claim, 2023 data ([Premier 2025](https://premierinc.com/newsroom/policy/claims-adjudication-costs-providers-257-billion-18-billion-is-potentially-unnecessary-expense)) | Rerun routing at 40 and 80 USD |
| A2 | Cost of a clinical appeal (medical necessity, prior authorization) | 108 USD | Same as A1 | 57.23 USD plus 51.20 USD added clinical labor per inpatient surgery claim, AMA estimate ([Premier 2024](https://premierinc.com/newsroom/blog/trend-alert-private-payers-retain-profits-by-refusing-or-delaying-legitimate-medical-claims)) | Rerun routing at 70 and 150 USD |
| A3 | Cost to fix and resubmit | 25 USD | Same as A1 | 25.20 USD per reworked claim ([Change Healthcare 2020 via Becker's](https://www.beckershospitalreview.com/finance/86-of-denials-are-potentially-avoidable-strategies-to-better-prevent-manage-denials/)). No newer figure published | Rerun routing at 15 and 40 USD |
| A4 | A truly correctable denial is paid after a fix | 95% of the allowed amount | Answer key, router | Judgment. Some corrected claims hit a second edit | Rerun at 85% |
| A5 | Cost of one human review | 15 USD | Scorer, router | 24.59 USD per hour median wage ([BLS 2025](https://www.bls.gov/ooh/healthcare/medical-records-and-health-information-technicians.htm)) × 1.43 benefits load ([BLS ECEC 2025](https://www.bls.gov/news.release/archives/ecec_09122025.htm)) × 25 minutes, the time of a manual payer transaction ([CAQH Index 2024](https://www.caqh.org/hubfs/Index/2024%20Index%20Report/CAQH_IndexReport_2024_FINAL.pdf)) | Rerun at 30 USD |

## Human review

| ID | Assumption | Value | Where used | Basis | How to test it |
| --- | --- | --- | --- | --- | --- |
| A6 | High-risk claims always go to a person | Allowed amount of 5,000 USD or more (9 of 200 dev claims, 4.5% of the queue) | `triage/router.py` | Large claims are where a wrong automated call costs most. Kept small so reviewers see few claims | Value and reviewer load at 2,500 and 10,000 USD: 65 claims and 93% value captured, and 2 claims and 85%, for the best baseline |
| A7 | Every claim sent to a person carries the system's recommended action and its reasoning | Always | `triage/router.py`, decision events | The reviewer should confirm or overrule a stated recommendation, not start from zero | Test: every human review decision has a recommendation and a rationale |
| A8 | A reviewer always chooses the best action | 100% correct | `evals/metrics.py` | No reviewer data exists. This flatters any system that sends more claims to people, so the report also shows value captured for the system alone | Rerun with reviewers right 85% of the time |

## Data and answer key

| ID | Assumption | Value | Where used | Basis | How to test it |
| --- | --- | --- | --- | --- | --- |
| A9 | Overturn probability is fixed by scenario | Ranges per scenario in `data/templates.py`, for example 60% to 80% for well-documented medical necessity | Answer key | Judgment, anchored to reported overturn rates of about 70% for appealed hospital denials (Premier) and 80.7% for appealed Medicare Advantage prior authorization denials ([KFF 2026](https://www.kff.org/medicare/medicare-advantage-insurers-made-nearly-53-million-prior-authorization-determinations-in-2024/)) | Shift every range by 10 points and rerun |
| A10 | Denials with no factual basis to appeal have overturn probability 0 | True duplicate, truly late filing, plan exclusion, undocumented code, true coverage end | Answer key | Appealing these is a compliance risk and a billing team would write them off | Compare routing with a 2% floor |
| A11 | Root-cause mix | Optum 2024 Denials Index shares where reported; the remaining 19% split across coordination of benefits, timely filing, and duplicates | Generator | [Optum 2024](https://marketplace.optum.com/content/dam/change-healthcare/marketplace-assets/outcomes-and-insights/2024-denials-index.pdf) | Not tested |
| A12 | Claim amount mix | 20% under 1,000 USD, 72% from 1,000 to 4,999 USD, 8% at 5,000 USD or more | Generator | Chosen so results describe the bulk of the queue, not a handful of large claims. Real hospital queues are more concentrated | Regenerate with the earlier uniform prices and compare |
| A13 | One root cause per denial | 1 | Generator, scorer | Simplification | Not tested |

## System

| ID | Assumption | Value | Where used | Basis | How to test it |
| --- | --- | --- | --- | --- | --- |
| A14 | Structural rules generalize to unseen wording | Rules read only IDs, codes, and dates | `triage/rules.py` | Formats do not change with phrasing. The rules were written with knowledge of the generator, so their dev precision of 100% overstates real precision | Held-out evaluation; rule errors in monitoring |
| A15 | Win odds come from a table fitted on dev labels | Mean overturn probability by root cause, evidence support, and correctability. Cells with fewer than 10 records are shrunk with 3 pseudo-records toward the mean of all denials with the same evidence profile (supports an appeal, correctable), across root causes; larger cells use their own mean | `triage/probability.py` | Stands in for a provider's history of appeal outcomes | Held-out evaluation; recalibration on the simulated post-launch week |
| A16 | Reason-code defaults for the fallback | One root cause and action per code, listed in `triage/pipeline.py` | Baselines | The action a biller would take from the code alone | Not tested; it is a baseline |
| A17 | Fallback confidence | 0.5 for every reason-code guess | `triage/pipeline.py` | Used only by the no-model baseline. Model confidence is not used for routing, because it does not predict errors (see ADR-004) | Not tested; it is a baseline |
| A18 | A denial for an authorization that was never requested is not fixable | Retroactive authorization is treated as unavailable; such denials are appeals at 3% to 10% win odds or write-offs | Answer key | Some payers do accept retroactive authorization requests, so this is a simplification. The classifier sometimes disagrees and marks these fixable | Count disagreements in error analysis; rerun with a retroactive-authorization rule per payer once payer rule packs exist |
| A19 | A letter that fails the citation checker twice costs one human review | 15 USD, same as A5 | Drafting model choice in ADR-003 | A reviewer must rewrite or approve the letter | Rerun the comparison at 30 USD |
| A20 | Letters may omit facts that weaken the case | Letters state only cited facts that support payment | `prompts/draft_v4.md` | Usual practice in appeals; the payer holds the same records. Limited cases go to a person before sending | Judge review of omissions |
| A21 | A person resolves every two-read disagreement correctly | Same as A8 | `evals/two_read.py` | No reviewer data. The value captured for the system alone is reported beside it | Rerun with reviewers right 85% of the time |
| A22 | Monthly queue sizes used for grading cost | 1,000, 5,000, and 25,000 denials | ADR-005 | Scenarios for a small, mid-size, and large provider. Not measured | Replace with a real provider's volume |

## Change history

| Date | ID | Change | Reason |
| --- | --- | --- | --- |
| 2026-10-06 | A2 | 118 USD to 108 USD | The 118 USD figure was from 2016 data. Rebuilt from 2023 to 2025 sources |
| 2026-10-06 | A5 | Unsourced to sourced; value unchanged at 15 USD | Built from BLS wage data and CAQH transaction time |
| 2026-10-07 | A15 | All cells shrunk toward the root-cause mean to only cells under 10 records | Shrinking gave denials with no basis to appeal a 4.8% win chance instead of 0, which made appeals look worth 57 USD on claims above about 1,200 USD. Found on the first live run: 3 of 20 denials appealed and lost |
| 2026-10-07 | A12 | Uniform service prices to the mix above | With uniform prices, 23% of claims held 79% of recoverable dollars |
| 2026-10-07 | A15 | Small cells shrunk toward the evidence-profile mean instead of the root-cause mean | Strong appeals raised the root-cause mean, which gave small cells with no basis to appeal win odds of 13% to 15% (late filing with 7 records, all at 0%). On the full dev run, appeals not worth filing fell from 13 to 2 and appeal precision rose from 83% to 97% |
