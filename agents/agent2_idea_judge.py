"""
agents/agent2_idea_judge.py

Agent 2: Idea Judge
-------------------
Receives the 3 candidate ideas from Agent 1, scores each on four rubrics,
and selects the single best candidate with a written rationale.

Input:  outputs/ideas.json
Output: outputs/selected_idea.json
"""

import json
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.llm_client import call_llm_with_search
from utils.validators import extract_json, validate_selected_idea

SYSTEM_PROMPT = """You are a highly critical panel judge for the Ig Nobel Prize committee — genuine
Nobel laureates and science journalists who take absurd science very seriously and are hard to impress.

Before scoring NOVELTY for each idea, you MUST use web_search to search for prior research on that
idea's core concept. Search for the key phenomenon or hypothesis being studied to verify it has not
already been published. If similar research exists, the NOVELTY score must reflect that.

Score each idea on four rubrics, each from 1–10. Apply strict standards — scores of 8+ are rare and
reserved for truly exceptional ideas. Most ideas should score 5–7:

1. NOVELTY (1-10): Based on your web search results, has this genuinely never been studied before?
   If similar work exists in the literature, score accordingly. Truly novel ideas are uncommon.
2. ABSURDITY (1-10): Does it make you laugh out loud? Merely "quirky" is not enough — it must be
   wonderfully ridiculous. Be honest; most ideas are not as funny as they seem at first glance.
3. SCIENTIFIC PLAUSIBILITY (1-10): Could this realistically be conducted and published in a
   peer-reviewed journal? Vague methods, unverifiable hypotheses, or impractical designs score low.
4. IG NOBEL FIT (1-10): Does it embody "first laugh, then think"? It must BOTH amuse AND reveal a
   genuine insight. Ideas that only amuse, or only reveal, do not qualify.

Select the idea with the highest total score. In case of a tie, prefer the one with higher Ig Nobel Fit.

You must respond with ONLY a valid JSON object, no preamble, no markdown prose.

{
  "scores": [
    {
      "title": "Exact title of idea",
      "novelty": 8,
      "absurdity": 9,
      "scientific_plausibility": 7,
      "ig_nobel_fit": 9,
      "total": 33,
      "brief_comment": "One sentence on its strengths/weaknesses, including what your novelty search found"
    }
  ],
  "selected_idea": {
    "title": "...",
    "hypothesis": "...",
    "justification": "...",
    "ig_nobel_category": "...",
    "proposed_methods": "..."
  },
  "selection_rationale": "2-3 sentences explaining why this idea was chosen over the others"
}"""


def run(ideas_path: str = "outputs/ideas.json") -> dict:
    """
    Judges the 3 ideas and selects the best one.
    Returns the selection dict and saves to outputs/selected_idea.json.
    """
    with open(ideas_path, "r") as f:
        ideas_data = json.load(f)

    ideas_text = json.dumps(ideas_data["ideas"], indent=2)

    user_message = f"""Please evaluate the following 3 research ideas for the Ig Nobel Prize.

IMPORTANT: Before scoring NOVELTY for each idea, use web_search to search for prior research on
that idea's core concept. Include what you found in the brief_comment for each idea.

After searching, score each idea on all four rubrics, then select the winner.

IDEAS:
{ideas_text}

Respond with only the JSON object."""

    print("[Agent 2] Judging 3 ideas with web search for prior art...")
    raw_response = call_llm_with_search(SYSTEM_PROMPT, user_message)

    selection = extract_json(raw_response)
    validate_selected_idea(selection)

    os.makedirs("outputs", exist_ok=True)
    with open("outputs/selected_idea.json", "w") as f:
        json.dump(selection, f, indent=2)

    winner = selection["selected_idea"]
    print(f"[Agent 2] ✓ Selected: '{winner['title']}' → outputs/selected_idea.json")
    print(f"  Rationale: {selection['selection_rationale'][:100]}...")

    return selection


if __name__ == "__main__":
    run()
