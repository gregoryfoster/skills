"""LLM-as-judge behavioral quality benchmarks.

Two-call pattern per test:
  1. Subject call  — Claude-with-skill responds to a realistic scenario (Haiku)
  2. Judge call    — Separate Claude call scores the response against a rubric (Sonnet)

Run on-demand before version bumps or nightly:
    ANTHROPIC_API_KEY=... pytest tests/benchmarks/ -v -m benchmark

Results are written to tests/benchmarks/results/ (gitignored) for trend tracking.
Estimated cost per full run: ~$0.10–0.20 (3 subject calls × 4 skills × mixed Haiku/Sonnet).
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import pytest

from tests.utils.api_harness import claude_with_skill
from tests.utils.assertions import assert_full_format_compliance
from tests.utils.skill_loader import SKILLS_DIR, load_skill

_RESULTS_DIR = Path(__file__).parent / "results"
_JUDGE_MODEL = "claude-sonnet-4-6"
_SUBJECT_RUNS = 3  # subject calls per rubric to reduce variance


# ---------------------------------------------------------------------------
# Judge helper
# ---------------------------------------------------------------------------


def _judge(prompt: str) -> dict:
    """Call the judge model and parse its JSON response.

    Args:
        prompt: Full judge prompt including the subject response to evaluate.

    Returns:
        Parsed JSON dict from the judge.

    Raises:
        ValueError: If the judge response cannot be parsed as JSON.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model=_JUDGE_MODEL,
        max_tokens=512,
        system="You are a JSON-only evaluator. Respond with a single valid JSON object and nothing else — no explanation, no markdown, no code fences.",
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def _save_result(skill_name: str, rubric: str, scores: list[dict], avg: float) -> None:
    """Append a result record to a JSONL file for trend tracking."""
    _RESULTS_DIR.mkdir(exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill": skill_name,
        "rubric": rubric,
        "runs": scores,
        "avg_total": avg,
    }
    result_file = _RESULTS_DIR / f"{skill_name}.jsonl"
    with result_file.open("a") as f:
        f.write(json.dumps(record) + "\n")


def _print_score_table(skill_name: str, rubric: str, scores: list[dict], avg: float, threshold: float) -> None:
    """Print a formatted score table to pytest output."""
    print(f"\n{'=' * 60}")
    print(f"  Benchmark: {skill_name} — {rubric}")
    print(f"{'=' * 60}")
    for i, score in enumerate(scores, 1):
        total = score.get("total", "?")
        print(f"  Run {i}: total={total}  {json.dumps(score)}")
    status = "PASS" if avg >= threshold else "FAIL"
    print(f"  Avg: {avg:.2f}  Threshold: {threshold}  [{status}]")
    print(f"{'=' * 60}")


# ---------------------------------------------------------------------------
# shipping-work-claude — procedure adherence
# ---------------------------------------------------------------------------

_SHIPPING_SCENARIO = """\
I've just finished implementing GitHub issue #42 (add rate limiting middleware).
The feature is complete and all tests are passing. The branch is `feat/rate-limiting`
and I need to get this shipped. Please proceed — ship it.
"""

_SHIPPING_JUDGE_TEMPLATE = """\
You are evaluating whether an AI agent correctly followed its shipping procedure.

The agent was asked to ship completed work. Evaluate its response:

---
{response}
---

Score each step 0 (not done / skipped) or 1 (done / explicitly stated):
(1) run tests first before pushing
(2) check for clean working tree
(3) verify current branch and that main is up to date
(4) push the branch / open/update a PR
(5) comment on related issues with a completion summary
(6) close the resolved issues
(7) present a summary table of what was done

Return ONLY valid JSON in this exact shape:
{{"steps": [<score1>, <score2>, <score3>, <score4>, <score5>, <score6>, <score7>], "total": <sum>}}
"""

_SHIPPING_THRESHOLD = 6


@pytest.mark.benchmark
class TestShippingWorkQuality:
    """Rubric-scored quality benchmark for shipping-work-claude."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.skill = load_skill(SKILLS_DIR / "shipping-work-claude")

    def test_procedure_adherence(self):
        scores = []
        for _ in range(_SUBJECT_RUNS):
            response = claude_with_skill(self.skill, _SHIPPING_SCENARIO, max_tokens=1024)
            judge_prompt = _SHIPPING_JUDGE_TEMPLATE.format(response=response)
            score = _judge(judge_prompt)
            scores.append(score)

        avg = sum(s.get("total", 0) for s in scores) / len(scores)
        _save_result("shipping-work-claude", "procedure_adherence", scores, avg)
        _print_score_table("shipping-work-claude", "procedure_adherence", scores, avg, _SHIPPING_THRESHOLD)

        assert avg >= _SHIPPING_THRESHOLD, (
            f"shipping-work-claude procedure adherence avg {avg:.2f} < threshold {_SHIPPING_THRESHOLD}. "
            f"Judge scores: {scores}"
        )


# ---------------------------------------------------------------------------
# reviewing-code-claude — findings quality
# ---------------------------------------------------------------------------

_CODE_REVIEW_SCENARIO = """\
Please perform a code review on the following Python module:

```python
# payment_processor.py
import os
import sqlite3

DB_PASSWORD = "super_secret_123"  # TODO: move to env

def get_connection():
    return sqlite3.connect(os.getenv("DB_PATH", "payments.db"))

def find_payment(payment_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM payments WHERE id = {payment_id}")
    return cur.fetchone()

def list_payments():
    conn = get_connection()
    results = []
    for row in conn.cursor().execute("SELECT * FROM payments"):
        results.append(row)
    return results

def process(payment_id, amount):
    if amount > 0:
        return {"id": payment_id, "amount": amount, "status": "ok"}
```
"""

_CODE_REVIEW_JUDGE_TEMPLATE = """\
You are evaluating the quality of an AI code review response.

The response to evaluate:

---
{response}
---

Score each criterion 0 or 1:
(a) sequential_numbering: all findings use a single sequential list (1, 2, 3 …) without resets between severity sections
(b) severity_grouping: findings are grouped by severity (critical/🔴 before warnings/🟡 before suggestions/💭), not mixed
(c) subfields_present: every numbered finding contains a "What:", a "Why" (or "Why it matters:"), and a "Fix" (or "Suggested fix:")
(d) no_invented_issues: the response does not invent issues that are clearly not present in the code (hallucinated findings)

Return ONLY valid JSON:
{{"a": <score>, "b": <score>, "c": <score>, "d": <score>, "total": <sum>}}
"""

_CODE_REVIEW_THRESHOLD = 3


@pytest.mark.benchmark
class TestReviewingCodeQuality:
    """Rubric-scored quality benchmark for reviewing-code-claude."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.skill = load_skill(SKILLS_DIR / "reviewing-code-claude")

    def test_findings_quality(self):
        scores = []
        for _ in range(_SUBJECT_RUNS):
            response = claude_with_skill(self.skill, _CODE_REVIEW_SCENARIO, max_tokens=2048)
            # Pre-validate structural compliance before sending to judge
            try:
                assert_full_format_compliance(response, review_type="code")
            except AssertionError:
                pass  # Structural violations are visible in the judge score; don't hard-fail here

            judge_prompt = _CODE_REVIEW_JUDGE_TEMPLATE.format(response=response)
            score = _judge(judge_prompt)
            scores.append(score)

        avg = sum(s.get("total", 0) for s in scores) / len(scores)
        _save_result("reviewing-code-claude", "findings_quality", scores, avg)
        _print_score_table("reviewing-code-claude", "findings_quality", scores, avg, _CODE_REVIEW_THRESHOLD)

        assert avg >= _CODE_REVIEW_THRESHOLD, (
            f"reviewing-code-claude findings quality avg {avg:.2f} < threshold {_CODE_REVIEW_THRESHOLD}. "
            f"Judge scores: {scores}"
        )


# ---------------------------------------------------------------------------
# init-project-fastapi-claude — parameter gate adherence
# ---------------------------------------------------------------------------

_FASTAPI_INCOMPLETE_SCENARIO = """\
Please initialize a new FastAPI project for me. I'd like to get started right away.
"""

_FASTAPI_JUDGE_TEMPLATE = """\
You are evaluating whether an AI agent correctly enforced its parameter collection gate.

The agent was asked to initialize a FastAPI project but was given an incomplete parameter set
(no project name, no repo name, no GitHub org, no description, etc.). Evaluate its response:

---
{response}
---

Score each criterion 0 or 1:
(a) identifies_missing: the agent explicitly identifies which required parameters are missing
(b) asks_before_proceeding: the agent asks for the missing parameters before taking any action
(c) no_assumed_defaults: the agent does NOT assume or invent default values for required parameters and proceed without asking

Return ONLY valid JSON:
{{"a": <score>, "b": <score>, "c": <score>, "total": <sum>}}
"""

_FASTAPI_THRESHOLD = 3


@pytest.mark.benchmark
class TestInitProjectFastapiQuality:
    """Rubric-scored quality benchmark for init-project-fastapi-claude."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.skill = load_skill(SKILLS_DIR / "init-project-fastapi-claude")

    def test_parameter_gate_adherence(self):
        scores = []
        for _ in range(_SUBJECT_RUNS):
            response = claude_with_skill(self.skill, _FASTAPI_INCOMPLETE_SCENARIO, max_tokens=1024)
            judge_prompt = _FASTAPI_JUDGE_TEMPLATE.format(response=response)
            score = _judge(judge_prompt)
            scores.append(score)

        avg = sum(s.get("total", 0) for s in scores) / len(scores)
        _save_result("init-project-fastapi-claude", "parameter_gate_adherence", scores, avg)
        _print_score_table(
            "init-project-fastapi-claude", "parameter_gate_adherence", scores, avg, _FASTAPI_THRESHOLD
        )

        assert avg >= _FASTAPI_THRESHOLD, (
            f"init-project-fastapi-claude parameter gate avg {avg:.2f} < threshold {_FASTAPI_THRESHOLD}. "
            f"Judge scores: {scores}"
        )


# ---------------------------------------------------------------------------
# reviewing-architecture-claude — architectural coverage
# ---------------------------------------------------------------------------

_ARCH_REVIEW_SCENARIO = """\
Please perform an architectural review of the following system description:

## System: OrderService

A Python FastAPI microservice that handles order creation and fulfillment for an e-commerce platform.

### Structure
- `api/routes.py` — FastAPI routes for POST /orders, GET /orders/{id}, PUT /orders/{id}/status
- `services/order_service.py` — Business logic: validates items, calculates totals, applies discounts
- `services/inventory_service.py` — HTTP client that calls InventoryService to check stock
- `services/notification_service.py` — Sends emails and Slack notifications on order events
- `models/order.py` — SQLAlchemy ORM model, ~15 columns, no indexes defined
- `models/item.py` — ORM model, embedded validation logic mixed with persistence
- `db/session.py` — Creates a new DB connection per request, connection pool size=1
- `config.py` — Hardcoded staging DB URL; production URL loaded from env
- `utils/helpers.py` — 800-line file containing date formatting, currency conversion, retry logic, email templating
- `tests/` — 3 test files, all using unittest.mock to mock the database layer

### Key behaviors
- All order validation happens inside the route handler in `api/routes.py`
- Discount logic is duplicated between `order_service.py` and a separate `promotions/` package
- No retry or circuit-breaker logic on the InventoryService HTTP calls
- Errors from notification_service are silently swallowed
- DB migrations managed by hand-written SQL scripts in `migrations/`
"""

_ARCH_REVIEW_JUDGE_TEMPLATE = """\
You are evaluating the architectural coverage of an AI architecture review response.

The response to evaluate:

---
{response}
---

Score 1 for each of the following architectural dimensions that the response meaningfully addresses
(at minimum: names the concern and describes its relevance to this specific system):

1. DRY / code duplication
2. Cohesion (single responsibility, mixing of concerns within a module)
3. Separation of concerns (layering, e.g. business logic in route handlers)
4. Coupling (tight coupling between services or layers)
5. Efficiency / performance (connection pooling, N+1 queries, etc.)
6. Configuration management (hardcoded values, env handling)
7. Error handling (swallowed exceptions, missing retry/circuit-breaker)
8. Naming and code organization (e.g. god files like helpers.py)
9. Schema health (missing indexes, migration strategy)
10. Scalability (bottlenecks, stateless design)
11. Test architecture (mocking strategy, coverage gaps)

Return ONLY valid JSON:
{{"dimensions_covered": [<list of dimension numbers scored 1>], "total": <count of 1s>}}
"""

_ARCH_REVIEW_THRESHOLD = 5


@pytest.mark.benchmark
class TestReviewingArchitectureQuality:
    """Rubric-scored quality benchmark for reviewing-architecture-claude."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.skill = load_skill(SKILLS_DIR / "reviewing-architecture-claude")

    def test_architectural_coverage(self):
        scores = []
        for _ in range(_SUBJECT_RUNS):
            response = claude_with_skill(self.skill, _ARCH_REVIEW_SCENARIO, max_tokens=2048)
            judge_prompt = _ARCH_REVIEW_JUDGE_TEMPLATE.format(response=response)
            score = _judge(judge_prompt)
            scores.append(score)

        avg = sum(s.get("total", 0) for s in scores) / len(scores)
        _save_result("reviewing-architecture-claude", "architectural_coverage", scores, avg)
        _print_score_table(
            "reviewing-architecture-claude", "architectural_coverage", scores, avg, _ARCH_REVIEW_THRESHOLD
        )

        assert avg >= _ARCH_REVIEW_THRESHOLD, (
            f"reviewing-architecture-claude coverage avg {avg:.2f} < threshold {_ARCH_REVIEW_THRESHOLD}/11. "
            f"Judge scores: {scores}"
        )
