"""#537 — the doctor repoints a skill its vendor retired.

Folding the `shipping-work-*` variants into one `shipping-work` happens in two
releases. Release 1 ships the replacement and a `retired-skills` map at the
vendor's root (`<old> <new>` per line); release 2 deletes the old directories.
In between, every consumer's `.skills/doctor.sh` reads the map and moves both
links of the chain — `skills/<old>` → `../skills-vendor/<v>/skills/<old>` and
`.claude/skills/<old>` → `../../skills/<old>` — onto `<new>`.

What this file pins:

- **A whole-directory symlink into the vendor is repointed**, both links, and
  the report names the paths to commit. Exit code unchanged.
- **Repointed before the dangling scan**, so a straggler whose old target is
  already gone (release 2) heals without a submodule init — and after one, so
  a fresh worktree whose vendor only appears with the init heals too.
- **A tracked file still naming `skills/<old>/` holds it** — a wrapper's
  `DELEGATE`, the scaffolded `load_env` line — because repointing under it
  would break the repo's gate. The doctor's own copy is not such a file. A
  link that already dangles is repointed regardless: nothing works through
  it, and the references are reported.
- **Never rewritten, only reported**: a directory at `skills/<old>` (an
  override, or per-file links), and a `skills/<new>` that is not the vendor's
  link. Silent for a link into another vendor.
- **`--check-only` changes nothing** and says what it would do.
- **A doctor that predates the map** repoints on the run after it syncs, and
  nothing dangles in between: release 1 keeps the old directories.

No API calls.
"""

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO_ROOT / "skills" / "managing-skills" / "scripts"
DOCTOR = SCRIPTS / "doctor.sh"
INSTALLER = SCRIPTS / "install-doctor.sh"

VENDOR = "acme-skills"
OLD = "shipping-work-php"
NEW = "shipping-work"
OLD_TARGET = f"../skills-vendor/{VENDOR}/skills/{OLD}"
NEW_TARGET = f"../skills-vendor/{VENDOR}/skills/{NEW}"


def _clean_env() -> dict:
    """No inherited GIT_* vars: a fixture's git must not reach the real repo
    (#189)."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env=_clean_env(),
    )


def _doctor(repo: Path, *args: str, doctor: Path = DOCTOR, path_prefix=None):
    env = _clean_env()
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}:{env.get('PATH', '/usr/bin:/bin')}"
    return subprocess.run(
        ["bash", str(doctor), "--no-preflight", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


def _vendor_skill(repo: Path, name: str) -> None:
    d = repo / "skills-vendor" / VENDOR / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: x\n---\n")


def _vendor(repo: Path, map_text: str = f"{OLD} {NEW}\n", old=True) -> None:
    if old:
        _vendor_skill(repo, OLD)
    _vendor_skill(repo, NEW)
    (repo / "skills-vendor" / VENDOR / "retired-skills").write_text(map_text)


def _consumer(tmp_path: Path, claude=True, **vendor) -> Path:
    """A consumer linking OLD through both chains, vendor checked out."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _vendor(repo, **vendor)
    (repo / "skills").mkdir()
    os.symlink(OLD_TARGET, repo / "skills" / OLD)
    if claude:
        (repo / ".claude" / "skills").mkdir(parents=True)
        os.symlink(f"../../skills/{OLD}", repo / ".claude" / "skills" / OLD)
    (repo / "README.md").write_text("consumer\n")
    _git(repo, "add", "README.md", "skills")
    if claude:
        _git(repo, "add", ".claude")
    _git(repo, "commit", "-q", "-m", "consumer")
    return repo


def _track(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    _git(repo, "add", rel)
    _git(repo, "commit", "-q", "-m", f"add {rel}")


def _link(repo: Path, rel: str):
    p = repo / rel
    return os.readlink(p) if p.is_symlink() else None


def _repointed(repo: Path) -> bool:
    return (
        _link(repo, f"skills/{NEW}") == NEW_TARGET
        and not (repo / "skills" / OLD).is_symlink()
    )


class TestRepoint:
    def test_both_links_move_to_the_new_skill(self, tmp_path):
        repo = _consumer(tmp_path)
        r = _doctor(repo)
        assert r.returncode == 0, r.stderr
        assert _repointed(repo), r.stderr
        assert _link(repo, f".claude/skills/{NEW}") == f"../../skills/{NEW}"
        assert not (repo / ".claude" / "skills" / OLD).is_symlink()
        assert (repo / ".claude" / "skills" / NEW / "SKILL.md").is_file()

    def test_the_report_names_what_to_commit(self, tmp_path):
        repo = _consumer(tmp_path)
        r = _doctor(repo)
        assert f"skills/{OLD} -> skills/{NEW}" in r.stderr
        assert "git add -A --" in r.stderr
        for rel in (f"skills/{OLD}", f"skills/{NEW}", f".claude/skills/{OLD}"):
            assert rel in r.stderr

    def test_the_named_paths_commit_cleanly(self, tmp_path):
        """The printed command is the commit: after it, the tree is clean."""
        repo = _consumer(tmp_path)
        r = _doctor(repo)
        cmd = next(
            line.split("commit it: ", 1)[1]
            for line in r.stderr.splitlines()
            if "commit it: " in line
        )
        subprocess.run(cmd, shell=True, cwd=repo, check=True, env=_clean_env())
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", "skills", ".claude"],
            cwd=repo,
            capture_output=True,
            text=True,
            env=_clean_env(),
        ).stdout
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-status"],
            cwd=repo,
            capture_output=True,
            text=True,
            env=_clean_env(),
        ).stdout
        assert status.strip() and all(line[0] != "?" for line in status.splitlines())
        assert f"skills/{NEW}" in staged and f"skills/{OLD}" in staged

    def test_a_healthy_rerun_is_silent(self, tmp_path):
        repo = _consumer(tmp_path)
        _doctor(repo)
        r = _doctor(repo)
        assert r.returncode == 0
        assert "retired" not in r.stderr, r.stderr

    def test_without_claude_skills(self, tmp_path):
        repo = _consumer(tmp_path, claude=False)
        r = _doctor(repo)
        assert r.returncode == 0, r.stderr
        assert _repointed(repo)

    def test_a_claude_skills_dir_symlink_is_left_to_the_skills_link(self, tmp_path):
        """`.claude/skills -> ../skills` (this repo's own shape): repointing
        skills/ is all there is to do."""
        repo = _consumer(tmp_path, claude=False)
        (repo / ".claude").mkdir()
        os.symlink("../skills", repo / ".claude" / "skills")
        r = _doctor(repo)
        assert r.returncode == 0, r.stderr
        assert _repointed(repo)
        assert _link(repo, ".claude/skills") == "../skills"

    def test_the_new_skill_already_linked_just_drops_the_old(self, tmp_path):
        repo = _consumer(tmp_path)
        os.symlink(NEW_TARGET, repo / "skills" / NEW)
        os.symlink(f"../../skills/{NEW}", repo / ".claude" / "skills" / NEW)
        r = _doctor(repo)
        assert r.returncode == 0, r.stderr
        assert _repointed(repo)
        assert not (repo / ".claude" / "skills" / OLD).is_symlink()


class TestBeforeTheScan:
    def test_a_dangling_retired_link_heals_without_an_init(self, tmp_path):
        """Release 2: the vendor deleted OLD, the map still names it."""
        repo = _consumer(tmp_path, old=False)
        r = _doctor(repo)
        assert r.returncode == 0, r.stderr
        assert _repointed(repo)
        assert "initializing submodules" not in r.stderr

    def test_repointed_after_an_init_exposes_the_vendor(self, tmp_path):
        """A fresh worktree: the vendor appears only with the init, so the
        first pass found no map and the post-heal pass must."""
        repo = _consumer(tmp_path, old=False)
        shutil.rmtree(repo / "skills-vendor")
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        real_git = shutil.which("git") or "/usr/bin/git"
        vroot = repo / "skills-vendor" / VENDOR
        (bin_dir / "git").write_text(
            "#!/usr/bin/env bash\n"
            'if [ "$1" = "submodule" ] && [ "$2" = "update" ]; then\n'
            f'  mkdir -p "{vroot}/skills/{NEW}"\n'
            f'  printf -- "---\\nname: {NEW}\\n---\\n" > "{vroot}/skills/{NEW}/SKILL.md"\n'
            f'  printf "{OLD} {NEW}\\n" > "{vroot}/retired-skills"\n'
            "  exit 0\n"
            "fi\n"
            f'exec {real_git} "$@"\n'
        )
        (bin_dir / "git").chmod(0o755)
        r = _doctor(repo, path_prefix=bin_dir)
        assert r.returncode == 0, r.stderr
        assert _repointed(repo), r.stderr


class TestHeld:
    def test_a_tracked_reference_holds_the_link(self, tmp_path):
        repo = _consumer(tmp_path)
        _track(
            repo,
            "scripts/pre-ship.sh",
            f'DELEGATE="skills/{OLD}/scripts/pre-ship.sh"\n',
        )
        r = _doctor(repo)
        assert r.returncode == 0, r.stderr
        assert _link(repo, f"skills/{OLD}") == OLD_TARGET
        assert not (repo / "skills" / NEW).exists()
        assert "scripts/pre-ship.sh" in r.stderr

    def test_an_uncommitted_edit_releases_it(self, tmp_path):
        """git grep reads the working tree: fixing the reference is enough."""
        repo = _consumer(tmp_path)
        _track(repo, "AGENTS.md", f"run skills/{OLD}/scripts/pre-ship.sh\n")
        (repo / "AGENTS.md").write_text(f"run skills/{NEW}/scripts/pre-ship.sh\n")
        r = _doctor(repo)
        assert _repointed(repo), r.stderr

    def test_the_doctors_own_copy_does_not_hold(self, tmp_path):
        repo = _consumer(tmp_path)
        _track(repo, ".skills/doctor.sh", f"# once: skills/{OLD}/scripts/x.sh\n")
        r = _doctor(repo)
        assert _repointed(repo), r.stderr

    def test_a_dangling_link_is_repointed_despite_references(self, tmp_path):
        repo = _consumer(tmp_path, old=False)
        _track(repo, "AGENTS.md", f"run skills/{OLD}/scripts/pre-ship.sh\n")
        r = _doctor(repo)
        assert r.returncode == 0, r.stderr
        assert _repointed(repo)
        assert "AGENTS.md" in r.stderr

    def test_an_override_directory_is_reported_not_rewritten(self, tmp_path):
        repo = _consumer(tmp_path)
        os.unlink(repo / "skills" / OLD)
        (repo / "skills" / OLD).mkdir()
        (repo / "skills" / OLD / "SKILL.md").write_text(
            f"---\nname: {OLD}\nmetadata:\n  overrides: {VENDOR}/{OLD}\n---\n"
        )
        r = _doctor(repo)
        assert r.returncode == 0, r.stderr
        assert (repo / "skills" / OLD / "SKILL.md").is_file()
        assert not (repo / "skills" / NEW).exists()
        assert f"skills/{OLD}" in r.stderr and "directory" in r.stderr

    def test_a_local_new_skill_is_not_clobbered(self, tmp_path):
        repo = _consumer(tmp_path)
        (repo / "skills" / NEW).mkdir()
        (repo / "skills" / NEW / "SKILL.md").write_text("local\n")
        r = _doctor(repo)
        assert r.returncode == 0, r.stderr
        assert _link(repo, f"skills/{OLD}") == OLD_TARGET
        assert (repo / "skills" / NEW / "SKILL.md").read_text() == "local\n"
        assert f"skills/{NEW}" in r.stderr

    def test_a_blocked_claude_side_holds_both_links(self, tmp_path):
        """CR 1398: moving skills/<old> first and finding .claude/skills/<new>
        in the way left .claude/skills/<old> pointing at nothing."""
        repo = _consumer(tmp_path)
        (repo / ".claude" / "skills" / NEW).mkdir()
        r = _doctor(repo)
        assert r.returncode == 0, r.stderr
        assert _link(repo, f"skills/{OLD}") == OLD_TARGET
        assert not (repo / "skills" / NEW).exists()
        assert (repo / ".claude" / "skills" / OLD / "SKILL.md").is_file()
        assert f".claude/skills/{NEW}" in r.stderr

    def test_another_vendors_skill_of_that_name_is_left_alone(self, tmp_path):
        repo = _consumer(tmp_path)
        other = repo / "skills-vendor" / "other-skills" / "skills" / OLD
        other.mkdir(parents=True)
        (other / "SKILL.md").write_text("x\n")
        os.unlink(repo / "skills" / OLD)
        os.symlink(f"../skills-vendor/other-skills/skills/{OLD}", repo / "skills" / OLD)
        r = _doctor(repo)
        assert r.returncode == 0, r.stderr
        assert _link(repo, f"skills/{OLD}").endswith(f"other-skills/skills/{OLD}")
        assert "retired" not in r.stderr, r.stderr

    def test_a_malformed_line_is_reported_and_the_rest_applied(self, tmp_path):
        repo = _consumer(
            tmp_path,
            map_text=f"# comment\nBad_Name {NEW}\n{OLD} {NEW}  # trailing\n",
        )
        r = _doctor(repo)
        assert r.returncode == 0, r.stderr
        assert _repointed(repo)
        assert "Bad_Name" in r.stderr


class TestCheckOnly:
    def test_nothing_changes_and_it_says_what_it_would_do(self, tmp_path):
        repo = _consumer(tmp_path)
        r = _doctor(repo, "--check-only")
        assert r.returncode == 0, r.stderr
        assert _link(repo, f"skills/{OLD}") == OLD_TARGET
        assert not (repo / "skills" / NEW).exists()
        assert "would repoint" in r.stderr


class TestADoctorThatPredatesTheMap:
    def test_it_repoints_on_the_run_after_it_syncs(self, tmp_path):
        """The plan's ordering risk (#537): a consumer whose installed doctor
        has no map support. Its first run syncs the new doctor and leaves the
        link — which still resolves, since release 1 keeps OLD — and the next
        run repoints. The doctor ships with the map in release 1 so that this
        lag ends before release 2 deletes anything."""
        repo = _consumer(tmp_path)
        scripts = repo / "skills-vendor" / VENDOR / "skills" / "managing-skills"
        (scripts / "scripts").mkdir(parents=True)
        shutil.copy2(DOCTOR, scripts / "scripts" / "doctor.sh")
        shutil.copy2(INSTALLER, scripts / "scripts" / "install-doctor.sh")
        text = DOCTOR.read_text()
        assert text.count("\nrepoint_retired\n") == 1
        assert text.count("|| repoint_retired\n") == 1
        old = text.replace("\nrepoint_retired\n", "\n:\n").replace(
            "|| repoint_retired\n", "|| :\n"
        )
        installed = repo / ".skills" / "doctor.sh"
        installed.parent.mkdir()
        installed.write_text(old)
        installed.chmod(0o755)

        first = _doctor(repo, doctor=installed)
        assert first.returncode == 0, first.stderr
        assert "refreshed .skills/doctor.sh" in first.stderr
        assert _link(repo, f"skills/{OLD}") == OLD_TARGET
        assert (repo / "skills" / OLD / "SKILL.md").is_file()

        second = _doctor(repo, doctor=installed)
        assert second.returncode == 0, second.stderr
        assert _repointed(repo), second.stderr
