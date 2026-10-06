# Brief: denial triage and appeal agent

## Problem

A hospital or clinic sends a claim to an insurer (the payer). The payer denies about 12% of hospital claims on first pass, up from 9% in 2016 ([Optum 2024 Denials Index](https://marketplace.optum.com/content/dam/change-healthcare/marketplace-assets/outcomes-and-insights/2024-denials-index.pdf)). Each denial is money the provider has already earned but has not collected.

The provider's billing team (the biller) works a queue of these denials. For each one, the biller must decide:

1. Why was it denied?
2. Is it worth any more work?
3. If yes, should we fix our own mistake and resend, or appeal the payer's decision with a letter?

Most denials are avoidable (84%), and about half of the avoidable ones are recoverable (Optum 2024). Work costs money: about 25 USD to rework a claim ([Change Healthcare 2020 via Becker's](https://www.beckershospitalreview.com/finance/86-of-denials-are-potentially-avoidable-strategies-to-better-prevent-manage-denials/)) and 57.23 USD on average to work a claim through adjudication, before any clinical labor ([Premier 2025, 2023 data](https://premierinc.com/newsroom/policy/claims-adjudication-costs-providers-257-billion-18-billion-is-potentially-unnecessary-expense)). A biller who appeals everything wastes hours. A biller who appeals nothing leaves money on the table.

## User

The primary user is a denial management specialist at a provider organization. The specialist works a queue of 50 to 200 denials a day and is measured on dollars recovered.

## What the product does

1. **Triage.** It reads the denial reason code, the claim, and the supporting documentation, and names the root cause.
2. **Route by expected value.** It estimates the chance an appeal succeeds and recommends one of four actions: appeal, fix and resubmit, write off, or human review. It appeals only when expected recovery exceeds the cost of the appeal.
3. **Draft.** For appeals, it drafts a letter in which every factual sentence cites a documentation line. A citation checker rejects any sentence that states a fact the documentation does not support.
4. **Monitor and learn.** Every decision is logged with its inputs, versions, confidence, and cost. Monitoring flags drift, such as a payer changing its rules. Real outcomes and human overrides feed back to recalibrate the win odds and review thresholds.

## What it does not do

- It does not submit anything to a payer. A person approves every action.
- It does not use real patient, provider, or payer data. All 300 records are synthetic.
- It does not give clinical or legal advice.

## Success measures

| Measure | Target |
| --- | --- |
| Root-cause accuracy | 85% or better |
| Appeal recall | 90% or better |
| Appeal precision | 75% or better |
| Value captured versus a perfect oracle | Beat both baselines |
| Prompt injection success rate | 0% |
| Drafts that pass the citation checker | 100% of shipped drafts |
| Model cost per denial | Under 0.02 USD |

Every metric is reported with a 95% bootstrap interval. The final score comes from 100 held-out records that are opened once.

## Constraints

- Budget: 40 USD hard cap on API spend, about 24 USD expected.
- Data: synthetic only, generated from a fixed seed.

## Roadmap

- **Now:** triage, expected-value routing, and grounded drafts on synthetic data.
- **Next:** payer rule packs (filing limits, authorization grids, and appeal formats per payer).
- **Later:** integration with a practice management system and real remittance (835) files, behind a privacy review.
