"""
web/app.py

Flask web server for the Ig Nobel Research Agent.
Accepts a natural language prompt, extracts category + intent,
runs the relevant pipeline agents, and returns the write-up + a PDF download link.

Run from the project root:
    python web/app.py
Then open: http://localhost:5001  (or set PORT env var to use a different port)
"""

import io
import json
import logging
import os
import re
import sys
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, request, jsonify, send_file, render_template

# Allow imports from project root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.llm_client import call_llm, call_llm_with_search, PipelineCancelledError, FAST_MODEL
from utils.validators import (
    extract_json, validate_ideas, validate_selected_idea,
    validate_study_plan, validate_draft_paper, validate_judgment,
)
from web.pdf_generator import generate_pdf

from agents.agent1_idea_generator import SYSTEM_PROMPT as AGENT1_PROMPT, _format_winner
from agents.agent2_idea_judge import SYSTEM_PROMPT as AGENT2_PROMPT
from agents.agent3_writeup_generator import SYSTEM_PROMPT as AGENT3_PROMPT
from agents.agent4_writeup_judge import SYSTEM_PROMPT as AGENT4_PROMPT

# Agent 3: study plan (replaces full-paper draft in the revision loop)
AGENT3_PLAN_PROMPT = """You are a scientific designer specialising in Ig Nobel-caliber research.
Your job is to design a rigorous, reproducible study plan for the given research idea.

The plan must be specific enough that a graduate student could execute it without asking questions.
Write in plain, precise scientific language — the humor comes from WHAT is studied, not HOW you describe it.

Respond with ONLY a valid JSON object:
{
  "title": "Working title for the study",
  "ig_nobel_category": "e.g. Physics",
  "hypothesis": "The precise, falsifiable, one-sentence claim",
  "dataset_description": "Subjects/materials/stimuli required. Specify sample size, source, inclusion and exclusion criteria.",
  "methods_plan": "Step-by-step procedure: recruitment, apparatus, trials, measurements, and the named statistical test (e.g. paired t-test, one-way ANOVA). Include specific numbers — N, trials per participant, measurement units.",
  "expected_finding": "The concrete result expected — direction and approximate magnitude. This is where the Ig Nobel comedy lives."
}"""

# Agent 4: plan judge (no web search — input is tiny, no citations to check)
AGENT4_PLAN_JUDGE_PROMPT = """You are the Ig Nobel Prize scientific review board evaluating a proposed
study plan (not yet a paper). Ensure the plan is rigorous enough to produce real publishable science
and absurd enough to win.

Score on three rubrics (each 1–10):
1. METHOD_SOUNDNESS: Is the procedure specific enough to replicate? Sample size, instruments, and
   statistical test all named? Score ≤ 4 if any is missing or vague.
2. IG_NOBEL_SPIRIT: Does the expected finding make you laugh AND reveal something real? The laugh must
   arrive before the explanation.
3. FEASIBILITY: Could this be run in a real lab, cleared by an ethics board, and published in a
   legitimate journal?

Passing threshold: average ≥ 7.0 and no rubric below 5.
Default is 'revise'. Issue 'pass' only when the plan is genuinely executable and absurd.
Feedback must be specific — not "improve methods" but "name the exact instrument and trial count".

Respond with ONLY a valid JSON object:
{
  "scores": {
    "method_soundness": 7,
    "ig_nobel_spirit": 8,
    "feasibility": 7,
    "average": 7.3
  },
  "verdict": "pass",
  "feedback": {
    "method_soundness": null,
    "ig_nobel_spirit": null,
    "feasibility": null
  }
}"""

# Parallel Agent 2: one scoring call per idea (web search), then a fast selection call
AGENT2_SCORE_ONE_PROMPT = """You are an Ig Nobel Prize judge scoring a single research idea.

Before scoring NOVELTY, use web_search to find prior research on this idea's core concept and hypothesis.

Score on four rubrics (each 1–10):
1. NOVELTY: What did your search find? Score ≤ 4 if similar work exists. Score 7+ only for genuinely uncharted territory.
2. ABSURDITY: Is it inherently funny as a scientific question without any embellishment?
3. SCIENTIFIC PLAUSIBILITY: Could it be funded, cleared by an ethics board, and published in a legitimate peer-reviewed journal?
4. IG NOBEL FIT: Does it make you laugh AND then think? The laugh must arrive before the explanation does.

Automatic disqualifiers (ig_nobel_fit ≤ 4): humor is in the framing not the science; merely taboo or edgy; finding would surprise nobody; absurdity was added not discovered.

Respond with ONLY a valid JSON object:
{
  "title": "exact title of the idea",
  "novelty": 7,
  "absurdity": 8,
  "scientific_plausibility": 6,
  "ig_nobel_fit": 8,
  "total": 29,
  "brief_comment": "One sentence on strengths/weaknesses including what your novelty search found."
}"""

AGENT2_SELECT_PROMPT = """You are the chair of the Ig Nobel Prize judging panel. Individual judges have
pre-scored each idea (including web searches for prior art). Select the single best candidate.

Choose the idea with the highest total score; in a tie, prefer higher ig_nobel_fit.
Populate selected_idea using the original idea details provided — do not invent new content.

Respond with ONLY a valid JSON object:
{
  "scores": [<the scored ideas array, exactly as given>],
  "selected_idea": {
    "title": "...",
    "hypothesis": "...",
    "justification": "...",
    "ig_nobel_category": "...",
    "proposed_methods": "..."
  },
  "selection_rationale": "2-3 sentences explaining why this idea was chosen over the others"
}"""

app = Flask(__name__)

WINNERS_PATH = "data/past_winners.json"
OUTPUTS_DIR  = "web/outputs"
LOGS_DIR     = "web/logs"
os.makedirs(OUTPUTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────

log = logging.getLogger("ignoble")
log.setLevel(logging.DEBUG)

_fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                         datefmt="%Y-%m-%d %H:%M:%S")

_file_handler = logging.FileHandler(os.path.join(LOGS_DIR, "pipeline.log"))
_file_handler.setFormatter(_fmt)

_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(_fmt)

log.addHandler(_file_handler)
log.addHandler(_console_handler)

# Cancellation flags keyed by session_id
_cancel_flags: dict[str, threading.Event] = {}

# Current pipeline stage, keyed by session_id
_pipeline_status: dict[str, str] = {}

# Intermediate results available before the pipeline finishes (set after Agent 2)
_pipeline_data: dict[str, dict] = {}


def _set_status(session_id: str, message: str) -> None:
    _pipeline_status[session_id] = message
    log.info("[%s] %s", session_id, message)

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

    raw = call_llm(AGENT1_PROMPT, user_msg, cancel_event=cancel_event, model=FAST_MODEL)
    ideas = extract_json(raw)
    validate_ideas(ideas)
    return ideas


def run_idea_judge(ideas: dict,
                   cancel_event: threading.Event | None = None) -> dict:
    """Agent 2 — scores each idea in parallel (one web-search call each), then selects."""
    idea_list = ideas["ideas"]

    def score_one(idea: dict) -> dict:
        user_msg = (
            f"Score this Ig Nobel Prize research idea:\n\n"
            f"{json.dumps(idea, indent=2)}\n\n"
            f"Respond with only the JSON object."
        )
        raw = call_llm_with_search(AGENT2_SCORE_ONE_PROMPT, user_msg, cancel_event=cancel_event)
        return extract_json(raw)

    # Fan out — one scoring thread per idea
    scores = []
    with ThreadPoolExecutor(max_workers=len(idea_list)) as executor:
        futures = {executor.submit(score_one, idea): idea for idea in idea_list}
        for future in as_completed(futures):
            exc = future.exception()
            if exc:
                raise exc  # propagates PipelineCancelledError and API errors
            scores.append(future.result())

    # Fan in — cheap selection call (no web search needed)
    user_msg = (
        f"Pre-scored ideas:\n{json.dumps(scores, indent=2)}\n\n"
        f"Original idea details:\n{json.dumps(idea_list, indent=2)}\n\n"
        f"Select the best idea and respond with only the JSON object."
    )
    raw = call_llm(AGENT2_SELECT_PROMPT, user_msg, cancel_event=cancel_event, model=FAST_MODEL)
    selection = extract_json(raw)
    validate_selected_idea(selection)
    return selection


def run_plan_generator(selection: dict, revision_feedback: dict | None = None,
                       cancel_event: threading.Event | None = None) -> dict:
    """Agent 3 — generates a short study plan (fast, Haiku). Replaces full-paper draft in the loop."""
    idea = selection["selected_idea"]
    rationale = selection.get("selection_rationale", "")

    if revision_feedback:
        revision_section = f"""
REVISION INSTRUCTIONS — attempt #{revision_feedback.get('attempt', 2)}.
The previous plan was rejected. Address ALL of the following feedback before responding:

{json.dumps(revision_feedback.get('feedback', {}), indent=2)}
"""
    else:
        revision_section = ""

    user_msg = f"""Design a rigorous study plan for this Ig Nobel research idea.

SELECTED IDEA:
{json.dumps(idea, indent=2)}

SELECTION RATIONALE:
{rationale}
{revision_section}
Respond with only the JSON object."""

    raw = call_llm(AGENT3_PLAN_PROMPT, user_msg, cancel_event=cancel_event, model=FAST_MODEL)
    plan = extract_json(raw)
    validate_study_plan(plan)
    return plan


def run_plan_judge(plan: dict, attempt: int = 1,
                   cancel_event: threading.Event | None = None) -> dict:
    """Agent 4 — reviews the study plan. No web search: tiny input, no citations to check."""
    user_msg = f"""Review this proposed study plan for scientific rigour and Ig Nobel potential.
Score it and return your verdict. Respond with only the JSON object.

STUDY PLAN:
{json.dumps(plan, indent=2)}"""

    raw = call_llm(AGENT4_PLAN_JUDGE_PROMPT, user_msg, cancel_event=cancel_event)
    judgment = extract_json(raw)
    validate_judgment(judgment)
    judgment["attempt"] = attempt
    return judgment


def run_paper_writer(plan: dict, selection: dict,
                     cancel_event: threading.Event | None = None) -> dict:
    """Final step — writes the full paper from the approved plan. Single Sonnet call, no loop."""
    user_msg = f"""Write a complete Ig Nobel-caliber academic paper based on the approved study plan below.

APPROVED STUDY PLAN:
{json.dumps(plan, indent=2)}

ORIGINAL IDEA CONTEXT:
{json.dumps(selection["selected_idea"], indent=2)}

The methods in the plan are final — expand them into full prose. Generate realistic (invented but
plausible) results consistent with the expected finding in the plan.
Respond with only the JSON object."""

    raw = call_llm(AGENT3_PROMPT, user_msg, cancel_event=cancel_event)
    draft = extract_json(raw)
    validate_draft_paper(draft)
    return draft


# ── Full pipeline ─────────────────────────────────────────────────────────────

def run_pipeline(prompt: str, session_id: str,
                 num_ideas: int = 3, max_revision_loops: int = 2,
                 write_paper: bool = True,
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
    _set_status(session_id, "Parsing research request…")
    intent = parse_user_prompt(prompt)
    category = intent.get("category")
    constraints = intent.get("extra_constraints")

    # Agent 1: generate ideas (with category bias)
    _set_status(session_id, f"Agent 1 — generating {num_ideas} candidate idea(s)…")
    ideas = run_idea_generator(category, constraints, winners, num_ideas=num_ideas,
                               cancel_event=cancel_event)

    # Agent 2: judge and select
    _set_status(session_id, "Agent 2 — judging ideas (searching for prior art)…")
    selection = run_idea_judge(ideas, cancel_event=cancel_event)
    winner = selection["selected_idea"]
    log.info("[%s] Selected idea: %s", session_id, winner["title"])

    # Make ideas + selection visible in the UI before Agent 3 starts
    _pipeline_data[session_id] = {
        "ideas": ideas["ideas"],
        "selected_idea": selection["selected_idea"],
        "selection_rationale": selection.get("selection_rationale", ""),
    }

    # Agent 3 + 4: fast plan revision loop
    revision_feedback = None
    final_plan = None
    final_judgment = None

    for attempt in range(1, max_revision_loops + 2):
        label = f"attempt {attempt}" if attempt > 1 else "first draft"
        _set_status(session_id, f"Agent 3 — drafting study plan ({label})…")
        plan = run_plan_generator(selection, revision_feedback, cancel_event=cancel_event)
        log.info("[%s] Plan drafted: %s", session_id, plan.get("title", "untitled"))

        _set_status(session_id, f"Agent 4 — reviewing plan ({label})…")
        judgment = run_plan_judge(plan, attempt, cancel_event=cancel_event)
        scores = judgment.get("scores", {})
        log.info(
            "[%s] Plan judgment (attempt %d): verdict=%s  avg=%.1f  "
            "soundness=%s  spirit=%s  feasibility=%s",
            session_id, attempt, judgment["verdict"],
            scores.get("average", 0),
            scores.get("method_soundness", "?"),
            scores.get("ig_nobel_spirit", "?"),
            scores.get("feasibility", "?"),
        )

        if judgment["verdict"] == "pass" or attempt > max_revision_loops:
            final_plan = plan
            final_judgment = judgment
            break

        revision_feedback = {
            "attempt": attempt + 1,
            "feedback": judgment.get("feedback", {}),
        }

    # Optional: write full paper from approved plan (Sonnet, single call)
    final_draft = None
    if write_paper:
        _set_status(session_id, "Writing full paper from approved plan…")
        final_draft = run_paper_writer(final_plan, selection, cancel_event=cancel_event)
        log.info("[%s] Paper written: %s", session_id, final_draft.get("title", "untitled"))
    log.info("[%s] Done", session_id)
    return {
        "session_id": session_id,
        "intent": intent,
        "ideas": ideas["ideas"],
        "selected_idea": selection["selected_idea"],
        "selection_rationale": selection.get("selection_rationale", ""),
        "scores": selection.get("scores", []),
        "plan": final_plan,
        "paper": final_draft,
        "judgment": final_judgment,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/categories")
def categories():
    """Returns Ig Nobel categories that appear at least twice in the winners corpus."""
    from collections import Counter
    with open(WINNERS_PATH, "r") as f:
        winners = json.load(f)["winners"]
    counts = Counter(w["category"] for w in winners)
    result = [cat for cat, n in counts.most_common() if n >= 2]
    return jsonify(result)


@app.route("/generate", methods=["POST"])
def generate():
    data = request.get_json() or {}
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Please enter a research request."}), 400

    num_ideas = max(1, min(10, int(data.get("num_ideas", 3))))
    max_revision_loops = max(0, min(5, int(data.get("max_revision_loops", 2))))
    write_paper = bool(data.get("write_paper", False))

    # Accept a client-generated session_id so the stop button can reference it
    raw_sid = data.get("session_id", "")
    session_id = raw_sid if re.match(r'^[a-z0-9]{6,16}$', raw_sid) else uuid.uuid4().hex[:8]

    log.info("[%s] New request — prompt=%r  num_ideas=%d  max_loops=%d  write_paper=%s",
             session_id, prompt[:80], num_ideas, max_revision_loops, write_paper)

    cancel_event = threading.Event()
    _cancel_flags[session_id] = cancel_event
    _pipeline_status[session_id] = "Starting…"
    try:
        result = run_pipeline(prompt, session_id,
                              num_ideas=num_ideas, max_revision_loops=max_revision_loops,
                              write_paper=write_paper, cancel_event=cancel_event)
        return jsonify(result)
    except PipelineCancelledError:
        log.info("[%s] Cancelled by user", session_id)
        return jsonify({"cancelled": True})
    except Exception as e:
        log.exception("[%s] Pipeline error: %s", session_id, e)
        return jsonify({"error": str(e)}), 500
    finally:
        _cancel_flags.pop(session_id, None)
        _pipeline_status.pop(session_id, None)
        _pipeline_data.pop(session_id, None)


@app.route("/status/<session_id>")
def pipeline_status(session_id):
    return jsonify({
        "status": _pipeline_status.get(session_id, ""),
        "preview": _pipeline_data.get(session_id),
    })


@app.route("/cancel/<session_id>", methods=["POST"])
def cancel(session_id):
    event = _cancel_flags.get(session_id)
    if event:
        event.set()
        return jsonify({"status": "cancelled"})
    return jsonify({"status": "not found"}), 404


@app.route("/write-paper", methods=["POST"])
def write_paper_route():
    data = request.get_json() or {}
    plan = data.get("plan")
    selected_idea = data.get("selected_idea")
    if not plan or not selected_idea:
        return jsonify({"error": "Missing plan or selected_idea."}), 400
    try:
        paper = run_paper_writer(plan, {"selected_idea": selected_idea})
        return jsonify({"paper": paper})
    except PipelineCancelledError:
        return jsonify({"cancelled": True})
    except Exception as e:
        log.exception("Paper writer error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/pdf", methods=["POST"])
def create_pdf():
    data = request.get_json() or {}
    paper = data.get("paper")
    if not paper:
        return jsonify({"error": "No paper data provided."}), 400
    pdf_path = os.path.join(OUTPUTS_DIR, f"ig_nobel_{uuid.uuid4().hex[:8]}.pdf")
    try:
        generate_pdf(paper, pdf_path)
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
    title_slug = re.sub(r"[^a-z0-9]+", "_", (paper.get("title") or "ig_nobel").lower()).strip("_")
    filename = f"{title_slug[:60]}.pdf"
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


@app.route("/download/<filename>")
def download(filename):
    # Safety: only serve files from our outputs dir, no path traversal
    safe_name = os.path.basename(filename)
    path = os.path.join(OUTPUTS_DIR, safe_name)
    if not os.path.exists(path):
        return jsonify({"error": "File not found"}), 404
    return send_file(path, as_attachment=True, download_name=safe_name)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    print(f" * Open: http://localhost:{port}")
    app.run(debug=True, port=port, threaded=True)
