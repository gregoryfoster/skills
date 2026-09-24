"""No live Mayfly channel URL anywhere in the tree (#302).

A Mayfly channel URL, `/c/<id>#<key>`, is the whole access-control model of
the channel: whoever holds it can read the conversation, post into two agents'
working context, and delete the record, with no owner and no revocation. This
repo is public, and so are the cohort repos that vendor it, so a URL that
reaches any file here is published the moment it is pushed. The
`using-mayfly-chat` skill's Iron Law says the URL never reaches a durable
store; this file is the part of that rule the repo can enforce on itself.

Two properties, both from findings on #302:

- **Match the key, not the host.** A joiner's first `curl` of a channel returns
  the keyless view URL, which is harmless: the id alone derives no bearer and
  no encryption key. A guard that fires on `mayfly.chat/c/` cries wolf on every
  session and gets switched off (comment 10 §2). The pattern here requires the
  22-character id AND the `#` fragment with its 43-character key, on any host,
  because a self-hosted instance leaks the same way.
- **The pattern cannot match itself.** A leak check whose own text contains the
  literal it hunts reports itself (comment 13 §2). The regex below is
  assembled from a character class, which no live URL contains, and
  `test_the_detector_is_live` builds a positive control at runtime so a broken
  assembly fails loudly rather than passing vacuously.

Scope: every file `git ls-files` reports that decodes as UTF-8. Untracked
scratch files are the agent's own business and are covered by the skill's
goodbye gate, not by this test.

No API calls required.
"""

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent

# base64url alphabet; an id is 16 bytes (22 chars), a key 32 bytes (43 chars).
_B64URL = "[A-Za-z0-9_-]"
CHANNEL_URL = re.compile("/c/" + _B64URL + "{22}" + "#" + _B64URL + "{43}")


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=True
    )
    paths = [REPO_ROOT / p for p in out.stdout.decode().split("\0") if p]
    return [p for p in paths if p.is_file()]


def _utf8_text(path: Path) -> str | None:
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return None


class TestNoChannelUrls:
    def test_the_detector_is_live(self) -> None:
        """A positive control, built at runtime so this file never holds one."""
        live = "https://example.test/c/" + "A" * 22 + "#" + "b" * 43
        assert CHANNEL_URL.search(live), "the assembled pattern must match a live URL"
        # The keyless view URL and the docs' placeholder are both fine.
        assert not CHANNEL_URL.search("https://example.test/c/" + "A" * 22)
        assert not CHANNEL_URL.search("https://example.test/c/<ID>#<key>")

    def test_no_tracked_file_holds_a_channel_url(self) -> None:
        offenders: list[str] = []
        for path in _tracked_files():
            text = _utf8_text(path)
            if text is None:
                continue
            for match in CHANNEL_URL.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{line}")
        assert not offenders, (
            "A live Mayfly channel URL (id plus #key) is committed here, which "
            "publishes read, write and delete access to that channel:\n  "
            + "\n  ".join(offenders)
            + "\nRemove it, then treat the channel as leaked: stop the agents "
            "using it, delete it, and distribute a new URL privately "
            "(skills/using-mayfly-chat/references/security.md)."
        )
