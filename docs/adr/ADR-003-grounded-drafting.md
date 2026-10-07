# ADR-003: Grounded appeal letters with a deterministic citation checker

Date: 2026-10-07
Status: accepted

## Context

A denial routed to appeal needs a letter. A letter that states a wrong date, amount, or clinical fact can lose the appeal and is a compliance risk, so a fluent letter is not enough: every fact must be traceable to the record. The question is how to enforce that, which model writes the letters, and what happens to letters for weak cases.

## Options

**How facts are enforced**

- **A. Model only.** Ask the model to be accurate and trust it.
- **B. Model plus a model judge.** A second model grades each letter.
- **C. Model plus a deterministic checker.** Every sentence cites a documentation line or a claim field, and code verifies that every date, amount, code, and ID in the sentence appears in what it cites. A failure goes back to the model once with the reasons, and a second failure goes to a person.

**What a letter may cite**

- Documentation lines only, or documentation lines plus named claim fields such as `claim.service_date`.

**Which model writes**

- Claude Haiku 4.5 or Claude Sonnet 5.5.

## Decision

- Option C, with documentation lines and claim fields both citable. A model judge is added later for what code cannot check, such as tone and whether a sentence says what its source says.
- Claude Sonnet 5.5 writes the letters. Classification stays on Claude Haiku 4.5.
- Letters for appeals where the classifier found that the documentation does not support the appeal are still drafted from true facts only, then sent to a person with the recommendation and reasoning before they go out.

## Rules the checker enforces

1. Every cited ID must exist in the record.
2. Every sentence carries a citation, except the request sentence and the closing sentence.
3. Every date, amount, number, code, and ID in a sentence must appear in a source that sentence cites. Amount and date formats are normalized, so 964.9 and 964.90 USD match, and August 5, 2025 matches 2025-08-05.
4. A letter may not cite a line the classifier flagged as an attempt to give instructions.

The checker uses no model, so it costs nothing to run, and the same letter always gets the same verdict. It is tested on 11 cases in `tests/test_citations.py`, including a missing citation, a wrong line, an invented date, an invented amount, and an uncited statement with no numbers.

## Evidence

All runs draft the same 61 dev denials whose recommended action is appeal, using the classifications of the full dev run.

| Prompt | Model | Passed first try | Passed after one retry | Failed twice | API cost per letter |
| --- | --- | --- | --- | --- | --- |
| Version 3 | Haiku 4.5 | 13 | 19 | 29 | 0.0064 USD |
| Version 3 | Sonnet 5.5 | 40 | 13 | 8 | 0.0137 USD |
| Version 4 | Haiku 4.5 | 22 | 20 | 19 | 0.0061 USD |
| Version 4 | Sonnet 5.5 | 61 | 0 | 0 | 0.0104 USD |

Run files: [Haiku 4.5](../../evals/runs/20261007T211852Z-dev-drafts-small.json), [Sonnet 5.5](../../evals/runs/20261007T211852Z-dev-drafts-large.json).

What changed between versions:

- **Version 3 failures.** Most Haiku failures were conclusions with no citation, for example "The documented conservative therapy history exceeds the payer's stated threshold." The conclusion was correct, but nothing tied it to a source. Version 4 requires a conclusion to cite the facts it compares, for example `[D2][D5]`.
- **Missing letters.** Sonnet 5.5 reasons before it answers. On 8 letters the reasoning used the whole 900-token limit and the letter was cut off. The limit is now 2,500 tokens.

Why Sonnet 5.5:

- A letter that fails twice costs a 15 USD review. Haiku 4.5 would send 19 of 61 letters to a person, about 285 USD of reviewer time, to save 0.0043 USD per letter.
- Every Sonnet 5.5 letter for a well-supported case (48 of 48) cites at least one line that the answer key marks as key evidence. No letter from either model cites an injected line.

Smaller model for reading, larger model for writing: classification needs judgment on a short structured answer, where Haiku 4.5 scored best ([ADR-002](ADR-002-model-tiering.md)). Letters need strict instruction-following over a longer text, where Sonnet 5.5 is clearly better.

## Consequences

- Easier: every shipped letter is verifiable line by line, and a reviewer sees exactly which sentence failed and why.
- Easier: drafting adds about 0.0104 USD per appeal. With 61 appeals in 200 denials, that is about 0.003 USD per denial, so total cost per denial stays well under the 0.02 USD target.
- Harder: the checker verifies numbers and IDs, not meaning. A cited sentence with no numbers could still misstate its source. The judge covers this.
- Harder: letters omit facts that weaken the case. This is normal for an appeal, and the payer holds the same records, but letters for limited cases go to a person for that reason.

## Revisit when

- The judge finds cited sentences that misstate their source.
- The share of letters passing on the first try drops below 95% on held-out or in monitoring.
- A cheaper model passes the checker at the same rate.
