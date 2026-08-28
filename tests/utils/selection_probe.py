"""The competitive-selection surface, as a reusable instrument (#242).

`tests/integration/test_trigger_routing.py` injects **one** skill as the system
prompt and asks a yes/no "does this match your skill" question. No call it makes
ever sees two skills, so it measures activation *in isolation* and is
structurally incapable of observing competition — its passing is fully
consistent with total shadowing between the eight members of the two variant
families ([#97 findings]).

The instrument that actually answered the question in #97 was an ad-hoc probe
that presented **every** skill's `name` + `description` in one listing — the
shape of the runtime's real selection surface — and asked for exactly one pick.
That probe lived only in a GitHub comment. This module is it, promoted.

## Split: what is free, what is billed

Everything here is pure — listing assembly, scenario generation, prompt
rendering, response parsing. Only `choose_skill()` touches the network. That
split is deliberate and is the lesson of #243: a contract whose only guard is
the opt-in, billed `-m integration` suite is a contract that rots silently.
`tests/structural/test_selection_probe_surface.py` exercises everything below
except `choose_skill` on every commit, for free;
`tests/integration/test_competitive_selection.py` spends money only on the one
question that genuinely needs a live model.

## Why the stack contexts describe evidence rather than name the stack

#97's probe stated the stack in one explicit sentence lifted close to the
variant's own wording ("the project is a Composer-managed PHP/WordPress
monorepo"), and flagged that as a caveat: a real session infers the stack from
files, not from a label handed to it. Echoing the description back at the model
turns the probe into a string-match test that a genuinely shadowed library
would still pass. The contexts below therefore name *artifacts* — `go.mod`,
`alembic/versions/`, a `[project.scripts]` entry point — and leave the
inference to the model.

No covered-stack context contains its own stack keyword: "PHP", "FastAPI", and
"Click" appear nowhere in the sentences below, so all three covered scenarios
test inference from evidence and none can be passed by token overlap alone.
That is a property worth keeping rather than a coincidence, so
`LABEL_NAMING_CONTEXTS` and its two structural guards hold it in place — a
future context that does name its stack has to say why.

The uncovered-stack context is the deliberate exception and names Go outright.
There is no variant whose wording it could echo, and the contract under test is
precisely that a *clearly identified* uncovered stack still reaches the
baseline rather than `NONE`.

## Why the stack keyword is the join

`_STACK_CONTEXTS` is keyed on the same stack keyword `VARIANT_FAMILIES` carries
(`"PHP"`, `"FastAPI"`, `"Click"`), so scenario coverage is derived from the
family declaration rather than hand-listed beside it. Adding
`reviewing-code-go` to `VARIANT_FAMILIES` without adding a `"Go"` context is
then a loud structural failure naming the fix — not a silent shrinking of what
the billed suite covers.

[#97 findings]: https://github.com/gregoryfoster/skills/issues/97#issuecomment-5443191395
"""

import os
from dataclasses import dataclass

import anthropic

from tests.utils.skill_families import BASELINES, VARIANT_FAMILIES
from tests.utils.skill_loader import Skill, all_skills

# The literal a model must emit when it judges that no skill fits. Parsed
# case-insensitively; kept as a named constant because both the prompt and the
# assertions depend on it agreeing.
NONE_CHOICE = "NONE"

# Stack evidence a real session would see, keyed on the stack keyword declared
# in VARIANT_FAMILIES. None reuse their variant's description phrasing, and none
# contain their own stack keyword — see the module docstring.
_STACK_CONTEXTS: dict[str, str] = {
    "PHP": (
        "The repository is a WordPress site: `composer.json` at the root, themes under "
        "`web/app/themes/`, and Blade templates."
    ),
    "FastAPI": (
        "The repository is a Python web service: `app/main.py` instantiates the ASGI app "
        "and serves async HTTP routes, and `alembic/versions/` holds the schema migrations."
    ),
    "Click": (
        "The repository is a Python command-line tool: `pyproject.toml` declares a "
        "`[project.scripts]` console entry point, and the commands are decorated functions "
        "grouped into subcommands."
    ),
}

# A stack no variant covers. This is the case #240 exists for: #97 measured
# Haiku picking NONE 8/8 here, because nothing on the selection surface said the
# baselines were the fallback. The expected answer is the family's baseline.
UNCOVERED_STACK = "Go"

# Covered stacks whose context is allowed to contain its own stack keyword.
# Naming the stack weakens a scenario from "infer the stack from evidence" to
# "match this token", so it is an exception with a stated reason rather than a
# default — same shape as `skill_families.NOT_VARIANTS`, and for the same
# reason: it forces the question to be answered rather than defaulted.
# `test_selection_probe_surface` fails on any undeclared self-naming context.
# Empty today: all three covered contexts describe artifacts without naming
# their stack, so every covered scenario currently tests real inference.
LABEL_NAMING_CONTEXTS: dict[str, str] = {}

_UNCOVERED_CONTEXT = (
    "The repository is a Go service: `go.mod` at the root, `cmd/server/main.go`, "
    "and the suite runs with `go test ./...`."
)

_NO_CONTEXT = ""

_PROMPT_TEMPLATE = """You are the skill-selection layer of a coding agent. The following skills are available; each entry is a skill's name and the description its author wrote.

<available_skills>
{listing}
</available_skills>

A software developer sends the request below during an active development session.{context}

Choose the single most appropriate skill to invoke for this request. Respond with exactly one skill name on the first line and nothing else on that line. If no skill is appropriate, respond with exactly {none_choice}.

User request: "{request}"
"""


@dataclass(frozen=True)
class Scenario:
    """One (family, stack) cell of the competitive-selection matrix."""

    family: str
    """The baseline skill whose family this scenario probes."""

    trigger: str
    """The user request — the family's first declared trigger phrase."""

    stack: str
    """Stack keyword, `UNCOVERED_STACK`, or `"none"` when no context is given."""

    context: str
    """The stack-evidence sentence prepended to the request, or empty."""

    expected: str
    """The skill directory name selection must land on."""

    @property
    def id(self) -> str:
        return f"{self.family}/{self.stack}"


def skill_listing(skills: list[Skill] | None = None) -> str:
    """Render every skill's name + description as the runtime's selection surface.

    Order is `all_skills()`'s (sorted by directory name), which interleaves the
    two families rather than grouping them — a grouped listing would hand the
    model a structural hint the real surface does not provide.
    """
    skills = all_skills() if skills is None else skills
    return "\n".join(
        f"- name: {skill.name}\n  description: {skill.description}" for skill in skills
    )


def _first_trigger(skill: Skill) -> str:
    """The family's canonical bare trigger, read from frontmatter, not retyped.

    `reviewing-code` declares `CR, code review, perform a review`;
    `shipping-work` declares `ship it, push GH, close GH, wrap up`. Taking the
    first keeps this test and `test_trigger_routing.py` reading one source, so
    a renamed trigger cannot leave a stale literal here.
    """
    triggers = skill.skill_metadata.get("triggers", "")
    return next((t.strip() for t in triggers.split(",") if t.strip()), "")


def scenarios(skills: list[Skill] | None = None) -> list[Scenario]:
    """The full matrix: per family, no context + one per covered stack + uncovered.

    Derived from `VARIANT_FAMILIES`, so a new variant extends the billed suite
    automatically once its stack keyword has a context.
    """
    skills = all_skills() if skills is None else skills
    by_dir = {skill.dir_name: skill for skill in skills}

    out: list[Scenario] = []
    for family in BASELINES:
        baseline = by_dir.get(family)
        if baseline is None:
            continue
        trigger = _first_trigger(baseline)

        out.append(
            Scenario(
                family=family,
                trigger=trigger,
                stack="none",
                context=_NO_CONTEXT,
                expected=family,
            )
        )
        for base, variant, stack in VARIANT_FAMILIES:
            if base != family or stack not in _STACK_CONTEXTS:
                continue
            out.append(
                Scenario(
                    family=family,
                    trigger=trigger,
                    stack=stack,
                    context=_STACK_CONTEXTS[stack],
                    expected=variant,
                )
            )
        out.append(
            Scenario(
                family=family,
                trigger=trigger,
                stack=UNCOVERED_STACK,
                context=_UNCOVERED_CONTEXT,
                expected=family,
            )
        )
    return out


def selection_prompt(scenario: Scenario, listing: str) -> str:
    """Render the single-turn prompt for one scenario against one listing."""
    context = f" {scenario.context}" if scenario.context else ""
    return _PROMPT_TEMPLATE.format(
        listing=listing,
        context=context,
        none_choice=NONE_CHOICE,
        request=scenario.trigger,
    )


def parse_choice(response: str) -> str:
    """Normalise a model response to a bare skill name or `NONE_CHOICE`.

    Only the first line is read, and only decoration is stripped — a response
    that names two skills, or wraps the name in a sentence, deliberately does
    NOT normalise to a valid name. Selection under competition is the thing
    being measured; a lenient parser that finds a name anywhere in prose would
    score hedging as a clean pick.
    """
    first_line = response.strip().split("\n")[0].strip()
    token = first_line.strip("`\"'*[]() \t.,:;")
    if token.upper() == NONE_CHOICE:
        return NONE_CHOICE
    return token


def choose_skill(
    prompt: str,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 32,
) -> str:
    """The one billed call: ask a live model to pick from the listing.

    Temperature is left at the API default rather than pinned to 0. The trial
    count is the instrument here — the question is whether selection is
    *deterministic under sampling*, and a temperature-0 run of N trials would
    answer a different, weaker question N times.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text
