"""
orchestrator.py

Pipeline Orchestrator
----------------------
Runs the full Ig Nobel research agent pipeline in sequence:

  Agent 1 (Idea Generator)
    → Agent 2 (Idea Judge)
      → Agent 3 (Write-up Generator)
        → Agent 4 (Write-up Judge)
          → [loop back to Agent 3 if revise, up to MAX_REVISION_LOOPS]
            → final_paper.md

Usage:
  python orchestrator.py

Outputs are written to the outputs/ directory.
"""

import os
import sys
import json
from dotenv import load_dotenv

load_dotenv()

MAX_REVISION_LOOPS = int(os.environ.get("MAX_REVISION_LOOPS", 2))

# Add project root to path so agents can import utils
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from agents.agent1_idea_generator import run as run_agent1
from agents.agent2_idea_judge import run as run_agent2
from agents.agent3_writeup_generator import run as run_agent3
from agents.agent4_writeup_judge import run as run_agent4


def run_pipeline():
    print("\n" + "="*60)
    print("  IG NOBEL RESEARCH AGENT PIPELINE")
    print("="*60 + "\n")

    # ── Agent 1: Generate 3 ideas ──────────────────────────────
    print("── STAGE 1: Idea Generation ──")
    ideas = run_agent1(winners_path="data/past_winners.json")
    print()

    # ── Agent 2: Judge ideas, select the best ─────────────────
    print("── STAGE 2: Idea Selection ──")
    selection = run_agent2(ideas_path="outputs/ideas.json")
    print()

    # ── Agent 3 + 4: Write-up loop ────────────────────────────
    revision_feedback = None
    final_judgment = None

    for attempt in range(1, MAX_REVISION_LOOPS + 2):  # +2 so attempt 1 is the first try
        print(f"── STAGE 3: Write-up Generation (attempt {attempt}) ──")
        draft = run_agent3(
            selected_idea_path="outputs/selected_idea.json",
            revision_feedback=revision_feedback
        )
        print()

        print(f"── STAGE 4: Write-up Judgment (attempt {attempt}) ──")
        judgment = run_agent4(
            draft_path="outputs/draft_paper.json",
            attempt=attempt
        )
        print()

        if judgment["verdict"] == "pass":
            final_judgment = judgment
            break

        if attempt > MAX_REVISION_LOOPS:
            print(f"[Orchestrator] Max revision loops ({MAX_REVISION_LOOPS}) reached.")
            print("[Orchestrator] Accepting best draft and rendering final paper.")
            # Force-render the last draft as final paper even without a pass
            from agents.agent4_writeup_judge import _render_final_paper
            _render_final_paper(draft)
            final_judgment = judgment
            break

        # Prepare feedback for Agent 3's next attempt
        revision_feedback = {
            "attempt": attempt + 1,
            "feedback": judgment.get("feedback", {}),
            "scores": judgment.get("scores", {})
        }
        print(f"[Orchestrator] Revision requested. Looping back to Agent 3...\n")

    # ── Summary ────────────────────────────────────────────────
    print("="*60)
    print("  PIPELINE COMPLETE")
    print("="*60)

    with open("outputs/selected_idea.json") as f:
        idea_title = json.load(f)["selected_idea"]["title"]

    print(f"\n  Paper: {idea_title}")
    print(f"  Final verdict: {final_judgment['verdict'].upper()}")
    print(f"  Final scores: {final_judgment['scores']}")
    print(f"\n  Outputs saved to outputs/")
    print(f"  → outputs/ideas.json          (3 candidate ideas)")
    print(f"  → outputs/selected_idea.json  (chosen idea + scores)")
    print(f"  → outputs/draft_paper.json    (final draft)")
    print(f"  → outputs/judgment.json       (quality assessment)")
    print(f"  → outputs/final_paper.md      (formatted paper)")
    print()


if __name__ == "__main__":
    run_pipeline()
