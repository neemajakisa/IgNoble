# Ig Nobel Research Agent

A semi-autonomous multi-agent pipeline that generates Ig Nobel Prize-eligible research papers.

## Architecture

```
Agent 1 (Idea Generator)
  → Agent 2 (Idea Judge)
    → Agent 3 (Write-up Generator)
      → Agent 4 (Write-up Judge)
        → [revision loop if needed, max 2 times]
          → final_paper.md
```

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Configure your API key
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

## Run

```bash
python orchestrator.py
```

## Run individual agents

```bash
python agents/agent1_idea_generator.py
python agents/agent2_idea_judge.py
python agents/agent3_writeup_generator.py
python agents/agent4_writeup_judge.py
```

## Output files

| File | Description |
|------|-------------|
| `outputs/ideas.json` | 3 candidate research ideas |
| `outputs/selected_idea.json` | Chosen idea with scoring rationale |
| `outputs/draft_paper.json` | Full paper as structured JSON |
| `outputs/judgment.json` | Quality assessment + scores |
| `outputs/final_paper.md` | Human-readable formatted paper |

## Configuration

Edit `.env` to change:
- `MODEL` — which Claude model to use (default: `claude-sonnet-4-6`)
- `MAX_REVISION_LOOPS` — how many times Agent 3 can revise before accepting (default: `2`)

## Project structure

```
ig_nobel_agent/
├── orchestrator.py              # Main pipeline runner
├── agents/
│   ├── agent1_idea_generator.py
│   ├── agent2_idea_judge.py
│   ├── agent3_writeup_generator.py
│   └── agent4_writeup_judge.py
├── utils/
│   ├── llm_client.py            # Shared Anthropic client + call_llm()
│   └── validators.py            # JSON schema validation for each handoff
├── data/
│   └── past_winners.json        # Ig Nobel winners corpus
├── outputs/                     # Generated at runtime
├── requirements.txt
└── .env.example
```
