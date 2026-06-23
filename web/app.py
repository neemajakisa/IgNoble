"""
web/app.py

Flask web server for the Ig Nobel Research Agent.
Accepts a natural language prompt, extracts category + intent,
runs the relevant pipeline agents, and returns the write-up + a PDF download link.

Run from the project root:
    python web/app.py
Then open: http://localhost:5001  (or set PORT env var to use a different port)
"""

import json
import os
import re
import sys
import uuid
import threading

from flask import Flask, request, jsonify, send_file, render_template

# Allow imports from project root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.llm_client import call_llm
from utils.validators import extract_json, validate_ideas, validate_selected_idea, validate_draft_paper, validate_judgment
from web.pdf_generator import generate_pdf

app = Flask(__name__)

WINNERS_PATH = "data/past_winners.json"
OUTPUTS_DIR  = "web/outputs"
os.makedirs(OUTPUTS_DIR, exist_ok=True)

# ── Prompt parser ─────────────────────────────────────────────────────────────

def parse_user_prompt(prompt: str) -> dict:
    """
    Uses the LLM to extract structured intent from a free-form user prompt.
    Returns: { category, extra_constraints, raw_prompt }
    """
    system = """You extract structured intent from a user's request for an Ig Nobel Prize research idea.

Return ONLY a JSON object with these fields:
{
  "category": "The Ig Nobel category requested (e.g. Physics, Biology, Medicine, Chemistry, Economics, Psychology, Literature, Peace, Engineering, Nutrition, etc.). If none specified, return null.",
  "extra_constraints": "Any additional constraints or themes the user mentioned, in one sentence. If none, return null.",
  "is_valid": true
}"""

    raw = call_llm(system, f"User request: {prompt}")
    try:
        return extract_json(raw)
    except Exception:
        return {"category": None, "extra_constraints": None, "is_valid": True}


# ── Agent runners (single-session versions that return data, not write files) ──

def run_idea_generator(category: str | None, extra_constraints: str | None, winners: list) -> dict:
    """Agent 1 — generates 3 ideas, biased toward the requested category."""

    winners_summary = "\n".join([
        f"- {w['year']} ({w['category']}): {w['title']}"
        + (f"\n  Abstract: {w['abstract'][:200]}" if w.get("abstract") else "")
        for w in winners
    ])

    category_instruction = ""
    if category:
        category_instruction = f"\nIMPORTANT: ALL 3 ideas MUST be in the '{category}' category. Do not generate ideas for other categories.\n"

    constraint_instruction = ""
    if extra_constraints:
        constraint_instruction = f"\nAdditional user constraints: {extra_constraints}\n"

    system = f"""You are a creative scientist specializing in absurd-but-legitimate research — the hallmark of Ig Nobel Prize-winning work.

The Ig Nobel Prizes honor achievements that "first make people LAUGH, then make them THINK."

Generate exactly 3 novel research ideas. Each must:
1. Be scientifically plausible — publishable in a real journal
2. Be genuinely funny or surprising in its premise
3. Be distinct from past winners listed below
4. Fit a recognizable Ig Nobel category
{category_instruction}{constraint_instruction}
Respond with ONLY valid JSON:
{{
  "ideas": [
    {{
      "title": "Short catchy paper title",
      "hypothesis": "One sentence stating what the study tests",
      "justification": "2-3 sentences: why it's funny AND what genuine insight it reveals",
      "ig_nobel_category": "Category name",
      "proposed_methods": "1-2 sentences on how it could be conducted"
    }}
  ]
}}"""

    user_msg = f"Past winners (avoid duplicating these):\n{winners_summary}\n\nGenerate 3 original ideas now."
    raw = call_llm(system, user_msg)
    ideas = extract_json(raw)
    validate_ideas(ideas)
    return ideas


def run_idea_judge(ideas: dict) -> dict:
    """Agent 2 — scores ideas and selects the best one."""
    system = """You are a judge for the Ig Nobel Prize committee.

Score each idea on four rubrics (1-10):
1. NOVELTY: Genuinely never studied before?
2. ABSURDITY: Makes you laugh out loud?
3. SCIENTIFIC PLAUSIBILITY: Could be published in a peer-reviewed journal?
4. IG NOBEL FIT: Embodies "first laugh, then think"?

Select the highest scorer. Ties: prefer higher Ig Nobel Fit.

Respond with ONLY valid JSON:
{
  "scores": [
    {
      "title": "exact title",
      "novelty": 8, "absurdity": 9, "scientific_plausibility": 7, "ig_nobel_fit": 9,
      "total": 33,
      "brief_comment": "one sentence"
    }
  ],
  "selected_idea": {
    "title": "...", "hypothesis": "...", "justification": "...",
    "ig_nobel_category": "...", "proposed_methods": "..."
  },
  "selection_rationale": "2-3 sentences why this was chosen"
}"""

    raw = call_llm(system, f"Evaluate these ideas:\n{json.dumps(ideas['ideas'], indent=2)}")
    selection = extract_json(raw)
    validate_selected_idea(selection)
    return selection


def run_writeup_generator(selection: dict, revision_feedback: dict | None = None) -> dict:
    """Agent 3 — writes the full two-page paper."""
    feedback_section = ""
    if revision_feedback:
        feedback_section = f"""
REVISION INSTRUCTIONS (attempt {revision_feedback.get('attempt', 2)}):
Address ALL of this feedback:
{json.dumps(revision_feedback.get('feedback', {}), indent=2)}
"""

    system = """You are a scientific writer crafting Ig Nobel-caliber papers.
Write exactly like a real academic paper — formal tone, passive voice, hedged claims, citations — 
while investigating something completely absurd. Never break the fourth wall.

Simulated results must be internally consistent (same N throughout methods/results/discussion).

Respond with ONLY valid JSON:
{
  "title": "Full formal paper title",
  "authors": ["Dr. A. Researcher", "Prof. B. Scientist"],
  "abstract": "150-200 word structured abstract",
  "introduction": "300-400 words with 4-6 invented citations",
  "methods": "250-350 words with specific participant numbers and procedure",
  "results": "200-300 words with specific statistics (means, p-values, CIs)",
  "discussion": "250-300 words with limitations and future directions",
  "references": ["Author, A. (year). Title. Journal, vol(issue), pages."]
}
Include at least 6 references in APA format."""

    idea = selection["selected_idea"]
    user_msg = f"Write a complete paper for this idea:\n{json.dumps(idea, indent=2)}\n\nRationale: {selection.get('selection_rationale','')}\n{feedback_section}"
    raw = call_llm(system, user_msg)
    draft = extract_json(raw)
    validate_draft_paper(draft)
    return draft


def run_writeup_judge(draft: dict, attempt: int = 1) -> dict:
    """Agent 4 — scores the draft, returns pass or revise with feedback."""
    system = """You are senior editor of the Annals of Improbable Research.

Score on four rubrics (1-10):
1. ACADEMIC REGISTER: Reads like a real journal paper?
2. INTERNAL CONSISTENCY: Numbers consistent across all sections?
3. IG NOBEL SPIRIT: Makes you laugh AND think?
4. COMPLETENESS: All sections present and substantive?

PASS if average >= 7.0 AND no single rubric < 5. Otherwise REVISE.

Respond with ONLY valid JSON:
{
  "scores": {
    "academic_register": 8, "internal_consistency": 9,
    "ig_nobel_spirit": 7, "completeness": 8, "average": 8.0
  },
  "verdict": "pass",
  "overall_comment": "2-3 sentences",
  "feedback": {
    "academic_register": "specific feedback or null",
    "internal_consistency": "specific feedback or null",
    "ig_nobel_spirit": "specific feedback or null",
    "completeness": "specific feedback or null"
  }
}"""

    raw = call_llm(system, f"Evaluate this draft:\n{json.dumps(draft, indent=2)}")
    judgment = extract_json(raw)
    validate_judgment(judgment)
    judgment["attempt"] = attempt
    return judgment


# ── Full pipeline ─────────────────────────────────────────────────────────────

def run_pipeline(prompt: str, session_id: str) -> dict:
    """
    Runs the full 4-agent pipeline for a given prompt.
    Returns a dict with the final paper data and PDF path.
    """
    # Load winners corpus
    with open(WINNERS_PATH, "r") as f:
        winners = json.load(f)["winners"]

    # Parse user intent
    intent = parse_user_prompt(prompt)
    category = intent.get("category")
    constraints = intent.get("extra_constraints")

    # Agent 1: generate ideas (with category bias)
    ideas = run_idea_generator(category, constraints, winners)

    # Agent 2: judge and select
    selection = run_idea_judge(ideas)

    # Agent 3 + 4: write-up loop (max 2 revisions)
    MAX_LOOPS = 2
    revision_feedback = None
    final_draft = None
    final_judgment = None

    for attempt in range(1, MAX_LOOPS + 2):
        draft = run_writeup_generator(selection, revision_feedback)
        judgment = run_writeup_judge(draft, attempt)

        if judgment["verdict"] == "pass" or attempt > MAX_LOOPS:
            final_draft = draft
            final_judgment = judgment
            break

        revision_feedback = {
            "attempt": attempt + 1,
            "feedback": judgment.get("feedback", {}),
            "scores": judgment.get("scores", {})
        }

    # Generate PDF
    pdf_filename = f"ig_nobel_{session_id}.pdf"
    pdf_path = os.path.join(OUTPUTS_DIR, pdf_filename)
    generate_pdf(final_draft, pdf_path)

    return {
        "session_id": session_id,
        "intent": intent,
        "ideas": ideas["ideas"],
        "selected_idea": selection["selected_idea"],
        "selection_rationale": selection.get("selection_rationale", ""),
        "scores": selection.get("scores", []),
        "paper": final_draft,
        "judgment": final_judgment,
        "pdf_filename": pdf_filename,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    data = request.get_json()
    prompt = (data or {}).get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Please enter a research request."}), 400

    session_id = uuid.uuid4().hex[:8]
    try:
        result = run_pipeline(prompt, session_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/download/<filename>")
def download(filename):
    # Safety: only serve files from our outputs dir, no path traversal
    safe_name = os.path.basename(filename)
    path = os.path.join(OUTPUTS_DIR, safe_name)
    if not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404
    return send_file(path, as_attachment=True, download_name=safe_name)


def _find_port(default: int) -> int:
    """Return default if free, otherwise let the OS pick any free port."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("", default))
            return default
        except OSError:
            s.bind(("", 0))
            return s.getsockname()[1]


if __name__ == "__main__":
    port = _find_port(int(os.environ.get("PORT", 5001)))
    print(f" * Open: http://localhost:{port}")
    app.run(debug=True, port=port)
