"""
agents/agent3_writeup_generator.py

Agent 3: Write-up Generator
----------------------------
Takes the selected research idea and produces a full two-page academic paper
with all required sections. On revision loops, also receives structured
feedback from Agent 4 to improve the draft.

Input:  outputs/selected_idea.json  (+ optional revision feedback dict)
Output: outputs/draft_paper.json
"""

import json
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.llm_client import call_llm
from utils.validators import extract_json, validate_draft_paper

SYSTEM_PROMPT = """You are a scientific writer who specializes in crafting Ig Nobel-caliber papers.
Your papers must read exactly like genuine academic publications — formal tone, passive voice, 
hedged conclusions, citation-laden introductions — while investigating something completely absurd.

The humor comes entirely from the contrast between the serious scientific register and the ridiculous subject matter.
Never wink at the reader. Never break the fourth wall. Write as if this is the most important study ever conducted.

You must produce a complete two-page research paper with ALL of the following sections.
Simulated results must be internally consistent — if you claim N=47 participants in methods, 
use N=47 throughout results and discussion.

You must respond with ONLY a valid JSON object, no markdown prose outside the JSON.

{
  "title": "Full formal paper title",
  "authors": ["Dr. A. Researcher", "Prof. B. Scientist"],
  "abstract": "150-200 word structured abstract with Background, Methods, Results, Conclusions",
  "introduction": "300-400 words. Cite 4-6 plausible (invented) prior studies. Establish why this gap in knowledge is critical.",
  "methods": "250-350 words. Participants/materials, procedure, statistical approach. Be specific with numbers.",
  "results": "200-300 words. Report specific statistics (means, p-values, confidence intervals). Include description of 1-2 tables or figures.",
  "discussion": "250-300 words. Interpret findings, acknowledge limitations, suggest future directions.",
  "references": [
    "Author, A., & Author, B. (year). Title of invented paper. Journal Name, volume(issue), pages.",
    "..."
  ]
}

Generate at least 6 references in APA format. All references may be invented but must look plausible."""


def run(selected_idea_path: str = "outputs/selected_idea.json",
        revision_feedback: dict | None = None) -> dict:
    """
    Generates a full two-page academic paper for the selected idea.
    If revision_feedback is provided, incorporates it into the prompt.
    Returns the draft dict and saves to outputs/draft_paper.json.
    """
    with open(selected_idea_path, "r") as f:
        selection_data = json.load(f)

    idea = selection_data["selected_idea"]
    rationale = selection_data.get("selection_rationale", "")

    idea_text = json.dumps(idea, indent=2)

    if revision_feedback:
        feedback_section = f"""
REVISION INSTRUCTIONS — This is attempt #{revision_feedback.get('attempt', 2)}.
The previous draft was rejected. You MUST address all of the following feedback:

{json.dumps(revision_feedback.get('feedback', {}), indent=2)}

Previous scores:
{json.dumps(revision_feedback.get('scores', {}), indent=2)}

Do not simply paraphrase the previous draft. Make substantive improvements based on the feedback above.
"""
    else:
        feedback_section = ""

    user_message = f"""Write a complete Ig Nobel-caliber academic paper for the following research idea.

SELECTED IDEA:
{idea_text}

SELECTION RATIONALE:
{rationale}
{feedback_section}
Write the full paper now. Respond with only the JSON object."""

    attempt = revision_feedback.get("attempt", 1) if revision_feedback else 1
    print(f"[Agent 3] Generating write-up (attempt {attempt})...")
    raw_response = call_llm(SYSTEM_PROMPT, user_message)

    draft = extract_json(raw_response)
    validate_draft_paper(draft)

    os.makedirs("outputs", exist_ok=True)
    with open("outputs/draft_paper.json", "w") as f:
        json.dump(draft, f, indent=2)

    print(f"[Agent 3] ✓ Draft paper written: '{draft['title']}' → outputs/draft_paper.json")

    return draft


if __name__ == "__main__":
    run()
