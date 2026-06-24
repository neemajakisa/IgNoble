# Ig Nobel Research Agent

A multi-agent pipeline that generates Ig Nobel Prize-eligible research, powered by Claude. Enter a research request in plain English; the system generates candidate ideas, selects the best one, produces an approved study plan, and optionally writes a full academic paper.

## Pipeline

```
User prompt
  → Agent 1 · Idea Generator        (Haiku — fast, generates N candidates)
  → Agent 2 · Idea Judge             (Sonnet + web search, parallelised per idea)
       ↓ selected idea + rationale shown immediately in UI
  → Agent 3 · Plan Generator         (Haiku — hypothesis, dataset, methods, expected finding)
  → Agent 4 · Plan Judge             (Sonnet — reviews plan, no web search)
       ↕ revision loop (configurable, default 2 attempts)
       ↓ approved plan shown in UI
  → [optional] Paper Writer          (Sonnet — full academic paper, on user request)
  → [optional] PDF                   (on user request)
```

Agents 2 scores each idea in a separate parallel thread (one web search call per idea), then runs a fast selection call — this replaces what was previously a single sequential call covering all ideas.

Agent 4 reviews the study plan only (not the full paper), so it runs without web search on a small input. The full paper is written once from the approved plan, with no revision loop.

## Setup

```bash
# 1. Create and activate conda environment
conda create -n IgNoble python=3.11
conda activate IgNoble

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure API key
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY
```

## Web interface (recommended)

```bash
conda activate IgNoble
python web/app.py
# Open http://localhost:5001
```

**UI features:**

| Control | Description |
|---|---|
| Category chips | Top 10 Ig Nobel categories from the winners corpus + "Choose at random" |
| Ideas to generate | How many candidate ideas Agent 1 produces (1–10, default 3) |
| Revision attempts | How many times the plan loop can revise before accepting (0–5, default 2) |
| Stop button | Cancels generation mid-pipeline |
| Ideas preview | Candidate ideas and selected idea appear as soon as Agent 2 finishes |
| Write Full Paper | Appears after the approved plan; triggers the paper writer on demand |
| Create & Download PDF | Appears after the paper is written |

**Logs** are written to `web/logs/pipeline.log` (and stdout) with timestamps, session IDs, per-attempt scores, and error tracebacks.

## Standalone pipeline (CLI)

The original agent scripts still work independently and write output files to `outputs/`:

```bash
conda activate IgNoble
python orchestrator.py [--num-ideas N] [--max-revision-loops N]
```

| Flag | Env var | Default | Description |
|---|---|---|---|
| `--num-ideas` | `$NUM_IDEAS` | `3` | Number of candidate ideas to generate |
| `--max-revision-loops` | `$MAX_REVISION_LOOPS` | `2` | Max write-up revision attempts |

Or run agents individually:

```bash
python agents/agent1_idea_generator.py
python agents/agent2_idea_judge.py
python agents/agent3_writeup_generator.py   # writes full paper directly
python agents/agent4_writeup_judge.py       # checks citations via web search
```

Note: the standalone agents use the original architecture (Agent 3 writes a full paper, Agent 4 checks citations with web search). The web app uses the newer plan-first architecture described above.

## Scoring rubrics

### Agent 2 — Idea Judge (all architectures)

Each idea is scored 1–10 on four rubrics. Most ideas should score 3–6; 7 means genuinely interesting; 8+ means it could actually win.

| Rubric | What is evaluated |
|---|---|
| **Novelty** | Web search for prior art. Score ≤ 4 if similar work exists; 7+ only for genuinely uncharted territory. |
| **Absurdity** | Is the scientific question itself inherently funny, without embellishment? The laugh must arrive before the explanation. |
| **Scientific plausibility** | Could it be funded, cleared by an ethics board, conducted in a real lab, and accepted by a legitimate peer-reviewed journal? |
| **Ig Nobel fit** | Does it make you laugh AND then make you think? Both must be true — the laugh must come first. |

The idea with the highest total is selected. Ties broken by Ig Nobel fit.

### Agent 4 — Plan Judge (web app)

The approved plan must pass before the paper writer is triggered. Passing threshold: **average ≥ 7.0 with no rubric below 5**.

| Rubric | What is evaluated |
|---|---|
| **Method soundness** | Is the procedure specific enough to replicate? Sample size, instruments, and statistical test all named? Score ≤ 4 if anything is missing or vague. |
| **Ig Nobel spirit** | Does the expected finding make you laugh AND reveal something real? The laugh must arrive before the explanation. |
| **Feasibility** | Could this be run in a real lab, cleared by an ethics board, and published in a legitimate journal? |

### Agent 4 — Write-up Judge (CLI only)

Used in the standalone pipeline where Agent 3 writes the full paper directly. Passing threshold: **average ≥ 7.0 with no rubric below 5**.

| Rubric | What is evaluated |
|---|---|
| **Academic register** | Does every sentence read like a peer-reviewed journal article? Formal tone, correct hedges, no colloquialisms. |
| **Internal consistency** | Numbers, p-values, and percentages consistent across sections; citations verified via web search (fabricated citations cap this score at 3). |
| **Ig Nobel spirit** | Title makes you laugh before you understand it; abstract surprises; paper teaches something real however absurd. |
| **Completeness** | All sections (abstract, introduction, methods, results, discussion, references) present and substantive. |

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required |
| `MODEL` | `claude-sonnet-4-6` | Model for judging agents and paper writer |
| `FAST_MODEL` | `claude-haiku-4-5` | Model for idea generation and plan generation |
| `PORT` | `5001` | Web server port (web app only) |

## API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Web UI |
| `POST` | `/generate` | Run the pipeline (idea gen → plan approval) |
| `GET` | `/status/<id>` | Poll pipeline stage and intermediate results |
| `POST` | `/cancel/<id>` | Stop a running pipeline |
| `GET` | `/categories` | Ig Nobel categories from the winners corpus |
| `POST` | `/write-paper` | Write full paper from an approved plan |
| `POST` | `/pdf` | Generate and download a PDF from paper JSON |

## Project structure

```
IgNoble/
├── web/
│   ├── app.py                   # Flask server — pipeline orchestration and all routes
│   ├── pdf_generator.py         # ReportLab PDF renderer
│   ├── templates/index.html     # Single-page UI
│   ├── logs/                    # pipeline.log written at runtime
│   └── outputs/                 # Temporary PDF files (deleted after download)
├── agents/
│   ├── agent1_idea_generator.py
│   ├── agent2_idea_judge.py
│   ├── agent3_writeup_generator.py
│   └── agent4_writeup_judge.py
├── utils/
│   ├── llm_client.py            # Anthropic client, call_llm(), call_llm_with_search()
│   └── validators.py            # JSON schema validation for each agent handoff
├── data/
│   └── past_winners.json        # Ig Nobel winners corpus (used for context + categories)
├── scripts/
│   └── scrape_winners.py        # Scraper to update the winners corpus
├── outputs/                     # CLI pipeline outputs (ideas.json, draft_paper.json, etc.)
├── pipeline.svg                 # Pipeline diagram
├── orchestrator.py              # CLI pipeline runner
├── requirements.txt
└── .env.example
```
