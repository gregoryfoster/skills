"""#425 — the retire list has two copies, and they say the same thing.

`references/retiring.md` is the list an agent reads, with what each entry did;
`scripts/_retire_scan.py` is the list retire-check.sh matches a host against.
A host retirement added to one and not the other is either never found or
never explained, so each entry must be in both, by repo and implementation,
and an entry the script can only leave to the operator must say "by hand" in
the doc.
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


def test_each_doc_row_is_in_the_script():
    module = scan_module()
    scripted = {(repo, entry) for repo, entry, _ in module.RETIRE_LIST}
    by_hand = {repo for repo, _, _ in module.BY_HAND}
    for row in doc_rows():
        if row[0] in by_hand and "by hand" in row[2]:
            continue
        entry = re.sub(r"^scripts/", "", row[1].strip("`"))
        assert (row[0], entry) in scripted, (
            f"{DOC.name} lists {row[0]} {row[1]}, and the script doesn't"
        )
