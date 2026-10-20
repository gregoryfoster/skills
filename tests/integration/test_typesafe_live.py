"""Integration test: one live call through the TypeSafe client (#448).

The structural suite drives `scripts/_typesafe.py` through a fake transport.
This test is the one place the real endpoint answers, so it checks what a fake
can't: the request shape the client builds is accepted, and the pinned model is
the one that answers. `GET /v1/models` lists only the aliases, but the pinned ID
is accepted anyway (the models page says so), so the pin is checked here, by its
answer, and never against that list.

Run with:
    bash scripts/run-integration-tests.sh -k typesafe

Skipped without TYPESAFE_API_KEY, whatever ANTHROPIC_API_KEY holds; the other
integration tests skip on theirs. Cost: about 300 input tokens at $0.042 per
million, output free.
"""

from __future__ import annotations

import importlib.util
import io
import os
from pathlib import Path

import pytest

CLIENT = Path(__file__).resolve().parents[2] / "scripts" / "_typesafe.py"


@pytest.mark.integration
def test_a_live_call_is_answered_by_the_pinned_model(tmp_path):
    if not os.environ.get("TYPESAFE_API_KEY"):
        pytest.skip(
            "TYPESAFE_API_KEY is not set; this test makes one live TypeSafe call. "
            "Set it in .env and run via scripts/run-integration-tests.sh."
        )
    spec = importlib.util.spec_from_file_location("_typesafe", CLIENT)
    ts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ts)

    err = io.StringIO()
    # The opt-in is a consuming repo's decision; this repo opts in for the
    # test alone, through the env var, so the whole connect() path runs.
    client = ts.connect(
        environ={**os.environ, ts.OPT_IN_ENV: "on"}, cwd=str(tmp_path), stderr=err
    )
    reply = client.ask(
        "The deploy finished and every health check passed.",
        {"healthy": {"type": "noul", "instructions": "Is the service healthy?"}},
    )

    assert reply["model"] == "jev-1.13.0"
    assert "answered by jev-1.13.0 (asked for jev-1.13.0)" in err.getvalue()
    noul = reply["answers"]["healthy"]["noul"]
    assert 0.0 <= noul <= 1.0
    assert os.environ["TYPESAFE_API_KEY"] not in err.getvalue()
