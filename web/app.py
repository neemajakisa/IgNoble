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

from utils.llm_client import call_llm, call_llm_with_search, PipelineCancelledError
from utils.validators import extract_json, validate_ideas, validate_selected_idea, validate_draft_paper, validate_judgment
from web.pdf_generator import generate_pdf

from agents.agent1_idea_generator import SYSTEM_PROMPT as AGENT1_PROMPT, _format_winner
from agents.agent2_idea_judge import SYSTEM_PROMPT as AGENT2_PROMPT
from agents.agent3_writeup_generator import SYSTEM_PROMPT as AGENT3_PROMPT
from agents.agent4_writeup_judge import SYSTEM_PROMPT as AGENT4_PROMPT

app = Flask(__name__)

WINNERS_PATH = "data/past_winners.json"
OUTPUTS_DIR  = "web/outputs"
os.makedirs(OUTPUTS_DIR, exist_ok=True)

# Cancellation flags keyed by session_id
_cancel_flags: dict[str, threading.Event] = {}

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

def run_idea_generator(category: str | None, extra_constraints: str | None, winners: list,
                       num_ideas: int = 3,
                       cancel_event: threading.Event | None = None) -> dict:
    """Agent 1 — generates num_ideas ideas using the same prompt as agents/agent1_idea_generator.py."""
    if category:
        winners = [w for w in winners if w["category"].lower() == category.lower()]

    winners_summary = "\n".join(_format_winner(w) for w in winners)

    category_instruction = (
        f"All {num_ideas} ideas must be in the '{category}' category."
        if category else
        "Ideas may span any Ig Nobel category."
    )
    constraint_instruction = (
        f"\nAdditional user constraints: {extra_constraints}" if extra_constraints else ""
    )

    user_msg = f"""Here are past Ig Nobel Prize winners for inspiration and to avoid duplication:

{winners_summary}

Generate exactly {num_ideas} original, novel research ideas that could win an Ig Nobel Prize.
They must be meaningfully different from the examples above.
{category_instruction}{constraint_instruction}
Respond with only the JSON object."""

    raw = call_llm(AGENT1_PROMPT, user_msg, cancel_event=cancel_event)
    ideas = extract_json(raw)
    validate_ideas(ideas)
    return ideas


def run_idea_judge(ideas: dict,
                   cancel_event: threading.Event | None = None) -> dict:
    """Agent 2 — scores ideas with web search for prior art, selects the best one."""
    ideas_text = json.dumps(ideas["ideas"], indent=2)
    num_ideas = len(ideas["ideas"])

    user_msg = f"""Please evaluate the following {num_ideas} research ideas for the Ig Nobel Prize.

IMPORTANT: Before scoring NOVELTY for each idea, use web_search to search for prior research on
that idea's core concept. Include what you found in the brief_comment for each idea.

After searching, score each idea on all four rubrics, then select the winner.

IDEAS:
{ideas_text}

Respond with only the JSON object."""

    raw = call_llm_with_search(AGENT2_PROMPT, user_msg, cancel_event=cancel_event)
    selection = extract_json(raw)
    validate_selected_idea(selection)
    return selection


def run_writeup_generator(selection: dict, revision_feedback: dict | None = None,
                          cancel_event: threading.Event | None = None) -> dict:
    """Agent 3 — writes the full two-page paper using the same prompt as agents/agent3_writeup_generator.py."""
    idea = selection["selected_idea"]
    rationale = selection.get("selection_rationale", "")

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

    user_msg = f"""Write a complete Ig Nobel-caliber academic paper for the following research idea.

SELECTED IDEA:
{json.dumps(idea, indent=2)}

SELECTION RATIONALE:
{rationale}
{feedback_section}
Write the full paper now. Respond with only the JSON object."""

    raw = call_llm(AGENT3_PROMPT, user_msg, cancel_event=cancel_event)
    draft = extract_json(raw)
    validate_draft_paper(draft)
    return draft


def run_writeup_judge(draft: dict, attempt: int = 1,
                      cancel_event: threading.Event | None = None) -> dict:
    """Agent 4 — scores with web search for hallucination/citation checking."""
    user_msg = f"""Please evaluate the following research paper draft.

IMPORTANT: Before scoring INTERNAL CONSISTENCY, use web_search to verify:
1. That each citation in the references section actually exists — search for author + title or DOI.
   If a citation is fabricated, name it explicitly in your internal_consistency feedback.
2. That key factual claims and statistics in the paper are plausible.

After verifying, score the paper on all four rubrics and return your verdict.
Respond with only the JSON object.

DRAFT PAPER:
{json.dumps(draft, indent=2)}"""

    raw = call_llm_with_search(AGENT4_PROMPT, user_msg, cancel_event=cancel_event)
    judgment = extract_json(raw)
    validate_judgment(judgment)
    judgment["attempt"] = attempt
    return judgment


# ── Full pipeline ─────────────────────────────────────────────────────────────

def run_pipeline(prompt: str, session_id: str,
                 num_ideas: int = 3, max_revision_loops: int = 2,
                 cancel_event: threading.Event | None = None) -> dict:
    """
    Runs the full 4-agent pipeline for a given prompt.
    Returns a dict with the final paper data and PDF path.
    Raises PipelineCancelledError if cancel_event is set between stages.
    """
    if cancel_event is None:
        cancel_event = threading.Event()

    # Load winners corpus
    with open(WINNERS_PATH, "r") as f:
        winners = json.load(f)["winners"]

    # Parse user intent
    intent = parse_user_prompt(prompt)
    category = intent.get("category")
    constraints = intent.get("extra_constraints")

    # Agent 1: generate ideas (with category bias)
    ideas = run_idea_generator(category, constraints, winners, num_ideas=num_ideas,
                               cancel_event=cancel_event)

    # Agent 2: judge and select
    selection = run_idea_judge(ideas, cancel_event=cancel_event)

    # Agent 3 + 4: write-up loop
    revision_feedback = None
    final_draft = None
    final_judgment = None

    for attempt in range(1, max_revision_loops + 2):
        draft = run_writeup_generator(selection, revision_feedback, cancel_event=cancel_event)
        judgment = run_writeup_judge(draft, attempt, cancel_event=cancel_event)

        if judgment["verdict"] == "pass" or attempt > max_revision_loops:
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
    data = request.get_json() or {}
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Please enter a research request."}), 400

    num_ideas = max(1, min(10, int(data.get("num_ideas", 3))))
    max_revision_loops = max(0, min(5, int(data.get("max_revision_loops", 2))))

    # Accept a client-generated session_id so the stop button can reference it
    raw_sid = data.get("session_id", "")
    session_id = raw_sid if re.match(r'^[a-z0-9]{6,16}$', raw_sid) else uuid.uuid4().hex[:8]

    cancel_event = threading.Event()
    _cancel_flags[session_id] = cancel_event
    try:
        result = run_pipeline(prompt, session_id,
                              num_ideas=num_ideas, max_revision_loops=max_revision_loops,
                              cancel_event=cancel_event)
        return jsonify(result)
    except PipelineCancelledError:
        return jsonify({"cancelled": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        _cancel_flags.pop(session_id, None)


@app.route("/cancel/<session_id>", methods=["POST"])
def cancel(session_id):
    event = _cancel_flags.get(session_id)
    if event:
        event.set()
        return jsonify({"status": "cancelled"})
    return jsonify({"status": "not found"}), 404


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
    app.run(debug=True, port=port, threaded=True)
