"""
utils/llm_client.py
Initializes and exposes a single Anthropic client instance.
All agents import from here — API key and model config live in one place.
"""

import os
import threading
import anthropic
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    raise EnvironmentError("ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.")

MODEL = os.environ.get("MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 4096

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


class PipelineCancelledError(Exception):
    pass


def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event and cancel_event.is_set():
        raise PipelineCancelledError()


def call_llm(system_prompt: str, user_message: str,
             cancel_event: threading.Event | None = None) -> str:
    """
    Single entry point for all LLM calls in the pipeline.
    Streams the response and checks cancel_event between chunks, so Stop
    takes effect within a fraction of a second rather than after the full response.
    Raises PipelineCancelledError if cancel_event is set.
    """
    _raise_if_cancelled(cancel_event)
    chunks = []
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for text in stream.text_stream:
            if cancel_event and cancel_event.is_set():
                raise PipelineCancelledError()
            chunks.append(text)
    return "".join(chunks)


def call_llm_with_search(system_prompt: str, user_message: str,
                         cancel_event: threading.Event | None = None) -> str:
    """
    LLM call with web search enabled for fact-checking and novelty verification.
    Handles the pause_turn continuation loop (server hits 10-iteration limit).
    Returns concatenated text from all response text blocks.
    Raises PipelineCancelledError before any API call if cancel_event is set.
    """
    tools = [{"type": "web_search_20260209", "name": "web_search"}]
    messages = [{"role": "user", "content": user_message}]
    all_text = []

    for _ in range(5):  # max 5 pause_turn continuations
        _raise_if_cancelled(cancel_event)
        message = client.messages.create(
            model=MODEL,
            max_tokens=8192,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )

        for block in message.content:
            if block.type == "text":
                all_text.append(block.text)

        if message.stop_reason == "end_turn":
            break
        elif message.stop_reason == "pause_turn":
            # Server hit its iteration limit; append assistant turn and continue
            messages.append({"role": "assistant", "content": message.content})
        else:
            break

    return "\n".join(all_text)
