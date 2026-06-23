"""
agents/agent1_idea_generator.py

Agent 1: Idea Generator
-----------------------
Takes the corpus of past Ig Nobel winners and generates exactly 3
novel research ideas eligible for the Ig Nobel prize.

Input:  data/past_winners.json
Output: outputs/ideas.json
"""

import json
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.llm_client import call_llm
from utils.validators import extract_json, validate_ideas

SYSTEM_PROMPT = """You are a creative scientist specializing in research that is simultaneously 
genuinely scientific and delightfully absurd — the hallmark of Ig Nobel Prize-winning work.

The Ig Nobel Prizes honor achievements that "first make people LAUGH, then make them THINK."
Winners are real scientific studies published in real journals. They are not jokes — they are 
legitimate research that happens to investigate something wonderfully unexpected.

Your job is to generate novel research ideas in this spirit. Each idea must:
1. Be scientifically plausible — it could realistically be conducted and published
2. Be genuinely funny or surprising in its premise
3. Investigate something nobody has thought to study before (or study a known thing in a bizarre new way)
4. Fit a recognizable Ig Nobel category (Medicine, Physics, Biology, Chemistry, Peace, Economics, etc.)

You must respond with ONLY a valid JSON object, no preamble, no explanation, no markdown prose.
The JSON must follow this exact schema:

{
  "ideas": [
    {
      "title": "Short catchy paper title",
      "hypothesis": "One sentence stating what the study tests or claims",
      "justification": "2-3 sentences on why this is Ig Nobel-worthy: what makes it funny AND what genuine scientific insight it might reveal",
      "ig_nobel_category": "The Ig Nobel category this fits (e.g. Medicine, Physics, Literature, etc.)",
      "proposed_methods": "1-2 sentences on how the study could realistically be conducted"
    }
  ]
}

Generate exactly 3 ideas. They must be distinct from each other and from the past winners provided."""


def run(winners_path: str = "data/past_winners.json", category: str | None = None) -> dict:
    """
    Generates 3 Ig Nobel research ideas inspired by past winners.
    If category is specified, filters context and output to that category.
    Returns the parsed ideas dict and saves to outputs/ideas.json.
    """
    with open(winners_path, "r") as f:
        winners_data = json.load(f)

    winners = winners_data["winners"]
    if category:
        winners = [w for w in winners if w["category"].lower() == category.lower()]

    winners_summary = "\n".join([
        f"- {w['year']} ({w['category']}): {w['title']} — {w['summary']}"
        for w in winners
    ])

    category_instruction = (
        f"All 3 ideas must be in the '{category}' category."
        if category else
        "Ideas may span any Ig Nobel category."
    )

    user_message = f"""Here are past Ig Nobel Prize winners for inspiration and to avoid duplication:

{winners_summary}

Generate 3 original, novel research ideas that could win an Ig Nobel Prize.
They must be meaningfully different from the examples above.
{category_instruction}
Respond with only the JSON object."""

    print("[Agent 1] Generating 3 research ideas...")
    raw_response = call_llm(SYSTEM_PROMPT, user_message)

    ideas = extract_json(raw_response)
    validate_ideas(ideas)

    os.makedirs("outputs", exist_ok=True)
    with open("outputs/ideas.json", "w") as f:
        json.dump(ideas, f, indent=2)

    print(f"[Agent 1] ✓ Generated {len(ideas['ideas'])} ideas → outputs/ideas.json")
    for i, idea in enumerate(ideas["ideas"], 1):
        print(f"  Idea {i}: {idea['title']}")

    return ideas


if __name__ == "__main__":
    run()
