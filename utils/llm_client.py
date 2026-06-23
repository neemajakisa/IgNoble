"""
utils/llm_client.py
Initializes and exposes a single Anthropic client instance.
All agents import from here — API key and model config live in one place.
"""

import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    raise EnvironmentError("ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.")

MODEL = os.environ.get("MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 4096

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def call_llm(system_prompt: str, user_message: str) -> str:
    """
    Single entry point for all LLM calls in the pipeline.
    Returns the text content of the model's response.
    """
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[
            {"role": "user", "content": user_message}
        ]
    )
    return message.content[0].text
