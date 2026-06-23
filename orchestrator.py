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
  python orchestrator.py [--num-ideas N] [--max-revision-loops N]

Outputs are written to the outputs/ directory.
"""

import argparse
import os
import sys
import json
from dotenv import load_dotenv

load_dotenv()

# Add project root to path so agents can import utils
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from agents.agent1_idea_generator import run as run_agent1
from agents.agent2_idea_judge import run as run_agent2
from agents.agent3_writeup_generator import run as run_agent3
from agents.agent4_writeup_judge import run as run_agent4


def run_pipeline(num_ideas: int = 3, max_revision_loops: int = 2):
    print("\n" + "="*60)
    print("  IG NOBEL RESEARCH AGENT PIPELINE")
    print("="*60 + "\n")

    # ── Agent 1: Generate ideas ────────────────────────────────
    print("── STAGE 1: Idea Generation ──")
    ideas = run_agent1(winners_path="data/past_winners.json", num_ideas=num_ideas)
    print()

    # ── Agent 2: Judge ideas, select the best ─────────────────
    print("── STAGE 2: Idea Selection ──")
    selection = run_agent2(ideas_path="outputs/ideas.json")
    print()

    # ── Agent 3 + 4: Write-up loop ────────────────────────────
    revision_feedback = None
    final_judgment = None

    for attempt in range(1, max_revision_loops + 2):  # +2 so attempt 1 is the first try
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

        if attempt > max_revision_loops:
            print(f"[Orchestrator] Max revision loops ({max_revision_loops}) reached.")
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
    print(f"  → outputs/ideas.json          ({num_ideas} candidate ideas)")
    print(f"  → outputs/selected_idea.json  (chosen idea + scores)")
    print(f"  → outputs/draft_paper.json    (final draft)")
    print(f"  → outputs/judgment.json       (quality assessment)")
    print(f"  → outputs/final_paper.md      (formatted paper)")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ig Nobel Research Agent Pipeline")
    parser.add_argument(
        "--num-ideas", type=int,
        default=int(os.environ.get("NUM_IDEAS", 3)),
        help="Number of ideas to generate (default: 3, or $NUM_IDEAS)",
    )
    parser.add_argument(
        "--max-revision-loops", type=int,
        default=int(os.environ.get("MAX_REVISION_LOOPS", 2)),
        help="Max write-up revision attempts (default: 2, or $MAX_REVISION_LOOPS)",
    )
    args = parser.parse_args()
    run_pipeline(num_ideas=args.num_ideas, max_revision_loops=args.max_revision_loops)
