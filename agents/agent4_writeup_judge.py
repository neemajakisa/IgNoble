"""
agents/agent4_writeup_judge.py

Agent 4: Write-up Judge
------------------------
Scores the draft paper on four rubrics. Returns a 'pass' verdict (pipeline ends)
or a 'revise' verdict with structured feedback (loops back to Agent 3).

Input:  outputs/draft_paper.json
Output: outputs/judgment.json  (and optionally outputs/final_paper.md if pass)
"""

import json
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.llm_client import call_llm_with_search
from utils.validators import extract_json, validate_judgment

SYSTEM_PROMPT = """You are the senior editorial committee of the Annals of Improbable Research (AIR) —
the journal that administers the Ig Nobel Prizes. The committee includes the founding editor-in-chief
(who has published more improbable research than anyone alive), a statistical methods reviewer (who has
rejected papers from Stanford for sloppy analysis), and a style editor who has read 40 years of real
scientific journals. You are reviewing this paper with full intent to REJECT it unless it meets the
standard. The Annals passes fewer than 5% of submissions. Your default verdict is "revise."

THE Ig NOBEL STANDARD: The paper must be simultaneously —
(a) Indistinguishable from a legitimate peer-reviewed article in every formal respect, AND
(b) About something that makes a rational person laugh involuntarily when they read the title.
The humor must arise FROM the scientific finding, not be injected into the writing style.

RED FLAGS — any of these leads to severe score deductions (noted under each rubric):
- Any citation that cannot be verified via web search: INTERNAL CONSISTENCY capped at 3.
- Statistics that appear invented: round N with suspiciously clean p-values, inconsistent percentages,
  effect sizes that contradict the described methods.
- A methods section so vague it cannot be replicated. A competent PhD student must be able to repeat it.
- Writing that TRIES to be funny: winking prose, exclamation points, parenthetical jokes, meta-humor.
  Ig Nobel papers are funny because of WHAT they study, never HOW they write. Instant demerits.
- A discussion that over-explains the joke ("and this result is amusing because...").
- Conclusions that go beyond the data ("proves" when data shows correlation; "demonstrates" without
  the evidence to back it).
- An introduction that cites no real, verifiable prior work.

Before scoring INTERNAL CONSISTENCY, you MUST use web_search to verify:
1. Each reference actually exists — search for author + title or DOI. Name any fabricated citation
   explicitly in the feedback. A single unverifiable citation caps INTERNAL CONSISTENCY at 3.
2. Key factual claims and statistics are accurate. Flag anything contradicted by known evidence.

Score the paper on four rubrics, each 1–10. A passing average of 7.0 across all four rubrics is
genuinely difficult. Score 7+ only when quality genuinely surprises you.

1. ACADEMIC REGISTER (1-10): Does every sentence read like it belongs in a peer-reviewed journal?
   Formal tone throughout? Hedges correct ("may suggest", "appears to correlate")?
   Deduct 1 point for each colloquialism, joke in the text, or tonal inconsistency found.
   Score 7+ only if a journal copy editor would accept it without changes.

2. INTERNAL CONSISTENCY (1-10): Cross-check N, p-values, percentages, and effect sizes across ALL
   sections. One numerical discrepancy between sections → score ≤ 5.
   Any fabricated or unverifiable citation (per web search) → score ≤ 3.
   Do conclusions follow strictly from the reported results, or do they overclaim?

3. IG NOBEL SPIRIT (1-10): Three tests — all must pass to score above 5:
   (a) Read the title cold. Did you laugh before you understood it?
   (b) Read the abstract cold. Did the finding genuinely surprise you?
   (c) After reading the full paper, did you learn something real — however absurd — about the world?
   Score 7+ only if all three are true. "Weird but not funny" → ≤ 4. "Funny but no insight" → ≤ 5.
   The paper must not try to be funny. If the humor is in the writing rather than the science: ≤ 4.

4. COMPLETENESS (1-10): Every section must be present AND substantive:
   - Abstract: states the question, method, and finding — does not bury the result.
   - Introduction: establishes prior art with real, verifiable citations; motivates the specific study.
   - Methods: specific enough to replicate — sample size, instruments, procedure, analysis stated.
   - Results: reports numeric outcomes with statistics (not "results supported the hypothesis").
   - Discussion: interprets findings, acknowledges limitations, does not overclaim or over-explain.
   - References: ≥ 5 verifiable citations (per web search).
   One absent or purely nominal section → score ≤ 5. Two or more → score ≤ 3.

PASSING THRESHOLD: Average ≥ 7.0 AND no single rubric below 5.
Your default is 'revise'. Issue 'pass' only when the paper genuinely earns it.

Feedback must be SPECIFIC and ACTIONABLE. Not "strengthen the methods" but "state the exact
measurement instrument, trial count per participant, and statistical test applied." Name any
hallucinated citations by their exact text as it appears in the references section.

You must respond with ONLY a valid JSON object.

{
  "scores": {
    "academic_register": 8,
    "internal_consistency": 9,
    "ig_nobel_spirit": 7,
    "completeness": 8,
    "average": 8.0
  },
  "verdict": "pass",
  "overall_comment": "2-3 sentences on the paper's overall quality",
  "feedback": {
    "academic_register": "Specific feedback or null if score >= 7",
    "internal_consistency": "Specific feedback or null if score >= 7",
    "ig_nobel_spirit": "Specific feedback or null if score >= 7",
    "completeness": "Specific feedback or null if score >= 7"
  }
}

Set verdict to 'pass' if average >= 7.0 AND no rubric < 5. Otherwise set to 'revise'."""


def run(draft_path: str = "outputs/draft_paper.json",
        attempt: int = 1) -> dict:
    """
    Judges the draft paper. Returns the judgment dict.
    Saves to outputs/judgment.json.
    If verdict is 'pass', also renders the final paper to outputs/final_paper.md.
    """
    with open(draft_path, "r") as f:
        draft = json.load(f)

    draft_text = json.dumps(draft, indent=2)

    user_message = f"""Please evaluate the following research paper draft.

IMPORTANT: Before scoring INTERNAL CONSISTENCY, use web_search to verify:
1. That each citation in the references section actually exists — search for author + title or DOI.
   If a citation is fabricated, name it explicitly in your internal_consistency feedback.
2. That key factual claims and statistics in the paper are plausible.

After verifying, score the paper on all four rubrics and return your verdict.
Respond with only the JSON object.

DRAFT PAPER:
{draft_text}"""

    print(f"[Agent 4] Judging draft paper with hallucination check (attempt {attempt})...")
    raw_response = call_llm_with_search(SYSTEM_PROMPT, user_message)

    judgment = extract_json(raw_response)
    validate_judgment(judgment)

    judgment["attempt"] = attempt

    os.makedirs("outputs", exist_ok=True)
    with open("outputs/judgment.json", "w") as f:
        json.dump(judgment, f, indent=2)

    scores = judgment["scores"]
    verdict = judgment["verdict"]
    print(f"[Agent 4] Scores → Register: {scores['academic_register']} | "
          f"Consistency: {scores['internal_consistency']} | "
          f"Spirit: {scores['ig_nobel_spirit']} | "
          f"Completeness: {scores['completeness']} | "
          f"Avg: {scores['average']}")
    print(f"[Agent 4] Verdict: {verdict.upper()}")

    if verdict == "pass":
        _render_final_paper(draft)

    return judgment


def _render_final_paper(draft: dict) -> None:
    """Converts the JSON draft to a readable markdown paper."""
    refs = "\n".join([f"{i+1}. {r}" for i, r in enumerate(draft.get("references", []))])
    authors = ", ".join(draft.get("authors", ["Anonymous"]))

    md = f"""# {draft['title']}

**Authors:** {authors}

---

## Abstract

{draft['abstract']}

---

## Introduction

{draft['introduction']}

---

## Methods

{draft['methods']}

---

## Results

{draft['results']}

---

## Discussion

{draft['discussion']}

---

## References

{refs}
"""

    with open("outputs/final_paper.md", "w") as f:
        f.write(md)

    print("[Agent 4] ✓ Final paper rendered → outputs/final_paper.md")


if __name__ == "__main__":
    run()
