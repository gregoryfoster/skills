"""#425 — the retire list has two copies, and they say the same thing.

`references/retiring.md` is the list an agent reads, with what each entry did;
`scripts/_retire_scan.py` is the list retire-check.sh matches a host against.
A host retirement added to one and not the other is either never found or
never explained, so each entry must be in both, by repo and implementation,
an entry the script can only leave to the operator must say "by hand" in the
doc, and one its repo has already retired must say "retired" (#558).
"""

import importlib.util
import re

from tests.structural import maintaining_host_disk_rig as rig

DOC = rig.SKILL / "references" / "retiring.md"


def scan_module():
    spec = importlib.util.spec_from_file_location(
        "_retire_scan", rig.SCRIPTS / "_retire_scan.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def doc_rows():
    text = DOC.read_text()
    section = text.split("## The retire list", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if (
            len(cells) >= 3
            and cells[0] not in ("Repo", "")
            and not set(cells[0]) <= set("-")
        ):
            rows.append(cells)
    return rows


def test_each_scripted_entry_is_in_the_doc():
    rows = doc_rows()
    for repo, entry, tokens in scan_module().RETIRE_LIST:
        hits = [
            r
            for r in rows
            if r[0] == repo and r[1].replace("scripts/", "") == f"`{entry}`"
        ]
        assert hits, (
            f"{repo} {entry} is matched by the script but not listed in {DOC.name}"
        )
        for token in tokens:
            assert f"`{token}`" in hits[0][2], (
                f"{DOC.name} doesn't say {entry} is matched by {token}"
            )


def test_each_by_hand_entry_says_so_in_the_doc():
    rows = doc_rows()
    for repo, _entry, _why in scan_module().BY_HAND:
        hits = [r for r in rows if r[0] == repo]
        assert hits and "by hand" in hits[0][2], (
            f"{repo} must read 'by hand' in {DOC.name}"
        )


def test_each_retired_entry_says_so_in_the_doc():
    """#558: an entry whose tool its repo has already retired is matched by
    nothing; the doc's row says "retired" where the match would be, and names
    the issue the script's note names."""
    rows = doc_rows()
    for repo, entry, note in scan_module().RETIRED:
        hits = [r for r in rows if r[0] == repo and r[2] == "retired"]
        assert hits, f"{repo} {entry} must read 'retired' in {DOC.name}"
        issue = re.search(r"\w+/[\w-]+#\d+", note)
        assert issue, f"the script's note for {repo} names no issue: {note!r}"
        assert issue[0] in hits[0][3], (
            f"{DOC.name}'s {repo} row doesn't name {issue[0]}, as the script does"
        )


def test_558_observo_reads_as_retired_in_both_copies():
    """#558: observo's cache units had fixed names all along, so "no fixed
    name to match" was never true; and CannObserv/observo#705 retired them
    when observo adopted the canonical GC. Its row is retired, in the doc and
    the script alike, and names no unit: observo is a private repo."""
    module = scan_module()
    assert "observo" not in {repo for repo, _, _ in module.BY_HAND}
    (note,) = [n for repo, _e, n in module.RETIRED if repo == "observo"]
    assert "CannObserv/observo#705" in note
    assert "no fixed" not in note
    (row,) = [r for r in doc_rows() if r[0] == "observo"]
    assert row[2] == "retired", row
    assert "CannObserv/observo#705" in row[3], row
    assert "no fixed name" not in " | ".join(row), row


def test_each_doc_row_is_in_the_script():
    module = scan_module()
    scripted = {(repo, entry) for repo, entry, _ in module.RETIRE_LIST}
    by_hand = {repo for repo, _, _ in module.BY_HAND}
    retired = {repo for repo, _, _ in module.RETIRED}
    for row in doc_rows():
        if row[0] in by_hand and "by hand" in row[2]:
            continue
        if row[0] in retired and row[2] == "retired":
            continue
        entry = re.sub(r"^scripts/", "", row[1].strip("`"))
        assert (row[0], entry) in scripted, (
            f"{DOC.name} lists {row[0]} {row[1]}, and the script doesn't"
        )


def test_each_not_disk_entry_is_named_in_the_doc():
    """#548: a unit the check reports under `not_disk` rather than as a
    candidate is named, with its repo, where the doc says what `not_disk` is."""
    text = DOC.read_text()
    section = text.split("## What the check automates", 1)[1].split("\n## ", 1)[0]
    (bullet,) = [line for line in section.splitlines() if "**not_disk:**" in line]
    for repo, unit, _command, _why in scan_module().NOT_DISK:
        assert repo in bullet and f"`{unit}`" in bullet, (
            f"{DOC.name}'s not_disk line doesn't name {repo}'s {unit}"
        )
