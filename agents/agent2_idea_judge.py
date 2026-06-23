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

from utils.llm_client import call_llm
from utils.validators import extract_json, validate_selected_idea

SYSTEM_PROMPT = """You are a panel judge for the Ig Nobel Prize committee — a group of genuine Nobel 
laureates and science journalists who take absurd science very seriously.

Your task is to evaluate candidate research ideas and select the one most worthy of an Ig Nobel Prize.

Score each idea on four rubrics, each from 1–10:

1. NOVELTY (1-10): Has this genuinely never been studied before? Is the angle truly original?
2. ABSURDITY (1-10): Does it make you laugh out loud? Is the premise wonderfully ridiculous?
3. SCIENTIFIC PLAUSIBILITY (1-10): Could this realistically be published in a peer-reviewed journal?
4. IG NOBEL FIT (1-10): Does it embody the spirit of "first laugh, then think"? Would it fit the ceremony?

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
      "brief_comment": "One sentence on its strengths/weaknesses"
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
Score each on the four rubrics, then select the winner.

IDEAS:
{ideas_text}

Respond with only the JSON object."""

    print("[Agent 2] Judging 3 ideas and selecting the best...")
    raw_response = call_llm(SYSTEM_PROMPT, user_message)

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
