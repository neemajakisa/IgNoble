"""
utils/validators.py
Validates agent outputs against expected schemas before handoff.
"""

import json
import re


def extract_json(text: str) -> dict | list:
    """
    Extracts JSON from model output, handling markdown code fences.
    """
    # Strip ```json ... ``` fences if present
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        text = match.group(1)
    return json.loads(text.strip())


def validate_ideas(data: dict) -> None:
    """Agent 1 output: must have exactly 3 ideas with required fields."""
    assert "ideas" in data, "Missing 'ideas' key"
    assert len(data["ideas"]) == 3, f"Expected 3 ideas, got {len(data['ideas'])}"
    for i, idea in enumerate(data["ideas"]):
        for field in ["title", "hypothesis", "justification", "ig_nobel_category"]:
            assert field in idea, f"Idea {i+1} missing field '{field}'"


def validate_selected_idea(data: dict) -> None:
    """Agent 2 output: must have a selected idea with scores."""
    for field in ["selected_idea", "selection_rationale", "scores"]:
        assert field in data, f"Missing field '{field}'"
    idea = data["selected_idea"]
    for field in ["title", "hypothesis", "justification", "ig_nobel_category"]:
        assert field in idea, f"Selected idea missing field '{field}'"


def validate_draft_paper(data: dict) -> None:
    """Agent 3 output: must have all required paper sections."""
    required_sections = [
        "title", "abstract", "introduction",
        "methods", "results", "discussion", "references"
    ]
    for section in required_sections:
        assert section in data, f"Draft paper missing section '{section}'"


def validate_judgment(data: dict) -> None:
    """Agent 4 output: must have a verdict and scores."""
    assert "verdict" in data, "Missing 'verdict' field"
    assert data["verdict"] in ("pass", "revise"), f"Verdict must be 'pass' or 'revise', got '{data['verdict']}'"
    assert "scores" in data, "Missing 'scores' field"
    if data["verdict"] == "revise":
        assert "feedback" in data, "Revise verdict requires 'feedback' field"
