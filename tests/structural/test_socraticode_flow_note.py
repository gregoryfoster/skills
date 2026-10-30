"""The generated doc's `codebase_flow` note names the right argument (#337).

`references/socraticode-doc.md`'s template is copied, marker to marker, into
every consumer's `docs/SOCRATICODE.md`, and every `init-socraticode` re-run
restores it, so a consumer cannot correct a wrong note durably. It told agents
to pass `codebase_flow` a file path, not a symbol name. The tool's schema says
the opposite: `entrypoint` is the symbol to trace from, and `file` only a hint
that disambiguates it. Observed in CannObserv/cli (socraticode 1.16.0):

    codebase_flow { entrypoint: "src/co_cli/archive/cli.py" }
    → No symbol named "src/co_cli/archive/cli.py" found.

An agent following the note reads that as "nothing to trace".
"""

import re

from .test_socraticode_policy_split import DOC_REF, _template


def _flow_note() -> str:
    """The template's `codebase_flow` bullet, joined onto one line."""
    template = _template(DOC_REF.read_text())
    found = re.search(
        r"^- \*\*`codebase_flow`\*\*.*?(?=^- |\n\n)", template, re.M | re.S
    )
    assert found, (
        f"references/{DOC_REF.name}'s template has no `codebase_flow` bullet "
        "under its per-tool notes"
    )
    return " ".join(found.group(0).split())


def test_the_note_does_not_ask_for_a_file_path() -> None:
    note = _flow_note()
    assert "pass a file path" not in note, (
        "the template tells agents to pass codebase_flow a file path; its "
        f"`entrypoint` is a symbol name, and a path answers 'No symbol named …' (#337)\n{note}"
    )


def test_the_note_names_entrypoint_as_a_symbol_and_file_as_the_hint() -> None:
    note = _flow_note()
    assert "symbol name as `entrypoint`" in note, note
    assert "`file` to disambiguate" in note, note


def test_the_note_says_what_no_arguments_does() -> None:
    """The tool description's own behaviour: no entry point lists them."""
    note = _flow_note()
    assert "with no arguments it lists detected entry points" in note, note
