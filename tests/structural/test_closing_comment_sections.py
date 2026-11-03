"""#397 — the closing comment's `Follow-up:`, `Known limits:` and `For #N:` sections.

`shipping-work` Step 5 ends each issue comment with up to three sections, and a
`coordinating-epics` coordinator harvests them at every check-in (check-in.md
§2). The producer and the consumer only agree while they spell the headings
the same way and write them in a form `harvest-candidates.sh` already settles
without a TypeSafe call. What this file pins:

- **The spelling.** Step 5 names each heading as a bold lead, `**Follow-up:**`,
  `**Known limits:**` and `**For #N:**`, and says an empty one is left out,
  never written as "none". check-in.md §2 and pr-mode.md's Step 5 bullet name
  the same three.
- **The form.** A comment built from Step 5's own leads, fed through the
  harvest's parser, names issue N on the `For #N:` lead and every item under
  it, and names nothing under the other two. A lead without a blank line before
  it is swallowed by the item above it, which is why Step 5 asks for one.
- **The pass-through.** `comment-issue.sh` hands the body to `gh issue comment
  --body` byte for byte.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPING = REPO_ROOT / "skills" / "shipping-work"
SKILL = SHIPPING / "SKILL.md"
PR_MODE = SHIPPING / "references" / "pr-mode.md"
COMMENT = SHIPPING / "scripts" / "comment-issue.sh"
EPICS = REPO_ROOT / "skills" / "coordinating-epics"
CHECK_IN = EPICS / "references" / "check-in.md"

HEADINGS = ("Follow-up:", "Known limits:", "For #N:")
LEADS = tuple(f"**{h}**" for h in HEADINGS)


def _between(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i : text.index(end, i + len(start))]


def _step5() -> str:
    return _between(SKILL.read_text(), "### Step 5", "### Step 6")


def _harvest_section() -> str:
    return _between(CHECK_IN.read_text(), "## 2. Harvest", "## 3.")


def _pr_mode_step5() -> str:
    return _between(PR_MODE.read_text(), "- **Step 5.**", "- **Step 6.**")


# --- the spelling -------------------------------------------------------------


def test_step_5_names_each_heading_as_a_bold_lead():
    step5 = _step5()
    missing = [lead for lead in LEADS if f"`{lead}`" not in step5]
    assert not missing, f"shipping-work Step 5 doesn't name {missing}"


def test_step_5_leaves_an_empty_section_out_rather_than_writing_none():
    step5 = _step5()
    assert 'never write "none"' in step5, step5


def test_check_in_reads_the_same_leads_first():
    harvest = _harvest_section()
    missing = [lead for lead in LEADS if f"`{lead}`" not in harvest]
    assert not missing, f"check-in.md §2 doesn't name {missing}"
    assert "shipping-work" in harvest and "predate" in harvest, (
        "§2 should say where the leads come from, and fall back to prose for "
        "a comment from a repo whose shipping-work predates them"
    )


def test_pr_mode_step_5_names_the_same_sections():
    bullet = _pr_mode_step5()
    missing = [h for h in HEADINGS if f"`{h}`" not in bullet]
    assert not missing, f"pr-mode.md's Step 5 bullet doesn't name {missing}"


# --- the form the harvest settles ---------------------------------------------


def _load_harvest():
    """The harvest's own module: one copy, shared with test_harvest_candidates.py."""
    if "_harvest" in sys.modules:
        return sys.modules["_harvest"]
    sys.dont_write_bytecode = True  # no __pycache__/ beside the skill's scripts
    sys.path.insert(0, str(EPICS / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "_harvest", EPICS / "scripts" / "_harvest.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_harvest"] = mod  # a dataclass looks its module up while it's built
    spec.loader.exec_module(mod)
    return mod


hv = _load_harvest()

HOST = "o/r"


def _lead(heading: str, n: int = 12) -> str:
    """Step 5's own spelling of a lead, with N filled in."""
    lead = next(lead for lead in LEADS if heading in lead)
    assert f"`{lead}`" in _step5()
    return lead.replace("#N", f"#{n}")


def _named(body: str) -> list[tuple[str, set[str]]]:
    return [(p.text, p.named) for p in hv.comment_paras({"id": 1, "body": body}, HOST)]


def test_a_comment_in_step_5s_shape_names_issue_n_under_its_lead_only():
    body = "\n\n".join(
        [
            "Shipped the retry.",
            "- the client retries a 503",
            "Commits: abc1234..def5678",
            _lead("Follow-up:"),
            "- the backoff cap is still a constant",
            _lead("Known limits:"),
            "- not live-verified",
            _lead("For #N:", 12),
            "- the error now carries `retry_after_seconds`",
            "- the route only forwards it",
            _lead("For #N:", 13),
            "- the lock order is A then B",
        ]
    )
    got = _named(body)
    want = {
        "**For #12:**": {"o/r#12"},
        "- the error now carries `retry_after_seconds`": {"o/r#12"},
        "- the route only forwards it": {"o/r#12"},
        "**For #13:**": {"o/r#13"},
        "- the lock order is A then B": {"o/r#13"},
    }
    for text, names in got:
        assert names == want.get(text, set()), (text, names)
    assert {t for t, _ in got} >= set(want), got


def test_a_lead_without_a_blank_line_before_it_joins_the_item_above():
    # Markdown reads the unindented line as a lazy continuation of the item,
    # so the harvest does too: the limit lands under #12.
    body = f"{_lead('For #N:', 12)}\n\n- a note\n{_lead('Known limits:')}\n\n- a limit"
    got = dict(_named(body))
    assert got[f"- a note\n{_lead('Known limits:')}"] == {"o/r#12"}
    assert got["- a limit"] == {"o/r#12"}


def test_a_plain_paragraph_under_a_lead_falls_outside_it():
    body = f"{_lead('For #N:', 12)}\n\nThe route only forwards it."
    assert dict(_named(body))["The route only forwards it."] == set()


# --- the pass-through ---------------------------------------------------------


def test_comment_issue_hands_the_body_to_gh_unchanged(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "argv"
    (bin_dir / "gh").write_text(
        "#!/usr/bin/env bash\n"
        f'for a in "$@"; do printf \'%s\\0\' "$a"; done > "{record}"\n'
    )
    (bin_dir / "gh").chmod(0o755)
    body = (
        "Shipped it.\n\n- `a` $(not run) \"quoted\" 'single'\n\n"
        "**Follow-up:**\n\n- x\n\n**Known limits:**\n\n- y\n\n"
        "**For #12:**\n\n- z\t\n"
    )
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    r = subprocess.run(
        ["bash", str(COMMENT), "397", body],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    argv = record.read_bytes().split(b"\0")[:-1]
    assert argv == [b"issue", b"comment", b"397", b"--body", body.encode()], argv
