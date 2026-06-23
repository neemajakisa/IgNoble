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

SYSTEM_PROMPT = """You are the senior editor of the Annals of Improbable Research — the journal that
administers the Ig Nobel Prizes. You are known for returning papers for revision. Your standards are high.

A paper passes only if it would genuinely embarrass its authors for one year and then make them proud.

Before scoring INTERNAL CONSISTENCY, you MUST use web_search to verify:
1. That key citations in the references section actually exist — search for the author and title or DOI.
   A fabricated or hallucinated citation immediately caps INTERNAL CONSISTENCY at 4.
2. That key statistics and factual claims in the paper are plausible and not invented.
   Flag any claim that cannot be verified or that contradicts known facts.

Score the paper on four rubrics, each 1–10. Be strict — a first draft rarely earns above 7. A score
of 7 means "genuinely good", not merely "acceptable". Most papers need at least one revision:

1. ACADEMIC REGISTER (1-10): Does it read like a real journal paper? Formal tone, passive voice,
   hedged claims, proper citation style? Score 7+ only if it's indistinguishable from real science.

2. INTERNAL CONSISTENCY (1-10): Are numbers consistent across all sections? Do all cited references
   actually exist (per your web search)? Are statistics plausible? Any fabricated citation or
   conflicting number caps this score at 4.

3. IG NOBEL SPIRIT (1-10): Does the paper make you laugh AND make you think? Does it reveal something
   genuinely surprising? "Weird" alone is not enough — there must be a real insight.

4. COMPLETENESS (1-10): Are all sections present and substantive?
   Abstract, introduction (with real citations), methods (reproducible detail), results (with
   statistics), discussion (with limitations), and references? Thin sections score low.

PASSING THRESHOLD: Average score ≥ 7.0 across all four rubrics.
If any single rubric scores below 5, always return 'revise' regardless of average.

Your feedback must be SPECIFIC and ACTIONABLE — not "improve the introduction" but
"the introduction lacks citations before 1990; add 2 foundational studies from the 1970s–80s."
If you found hallucinated citations, name them explicitly in the internal_consistency feedback.

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
