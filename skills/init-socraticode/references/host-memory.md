# Host memory — the install peak, and a production service beside the session

Row U of [`troubleshooting.md`](troubleshooting.md), as procedures. Two
halves: the launch installs, and that install is the measured peak, so don't
install at launch; and on a host that also runs a production service, give that
service memory the sessions cannot take — then check that the setting which
says so actually does. `preflight.sh` reports total memory, swap, and whether a
unit's `MemoryLow=` can take effect on this host.

## Don't install at launch: the pinned pre-install

The plugin's `mcp.json` is `npx -y --prefer-online socraticode@latest`, and
`mcp-driver.mjs` reused that command verbatim — so the health hook, `index`,
`status` and `verify` each installed a server before talking to one.
`--prefer-online` revalidates against the registry on *every* launch, so a warm
cache is not a warm path on any day the package moved.

Install once, deliberately, under a cap:

```bash
# Pick the version deliberately — a literal, never `latest`, or the pin floats
# and buys nothing. This is what the plugin's own command would have resolved:
npm view socraticode version

# Linux with user systemd — the cap is the point; on a small host, run it here
# and nowhere else.
systemd-run --user --scope -p MemoryHigh=1200M -p MemoryMax=1536M \
  -- npm install --prefix ~/.socraticode/pin socraticode@<version>

# Anywhere else (macOS, a host without user systemd): the install is the same,
# just uncapped. Size the host for ~1.2 G rather than hoping.
npm install --prefix ~/.socraticode/pin socraticode@<version>
```

`resolveServerLaunch()` prefers that build over the plugin's command, so no
driver launch installs anything. Nothing else has to be configured: absent, the
pin resolves nothing and the chain is exactly what it was.
`SOCRATICODE_PIN_DIR` moves it; `node "<SKILL_DIR>/scripts/mcp-driver.mjs"
resolve` says which path won, without launching a server.

**What the pin does not do, and why the hook now says so.** It does not pin the
*session*. Claude Code cannot override a plugin's MCP server command, so the
plugin keeps launching `@latest` — the driver becomes deterministic while the
session goes on floating. That is a **new** divergence: before the pin both
floated and agreed by coincidence of timing. `health-check` measures it, and
splits on how wide the gap is, because a pin is *meant* to lag:

| Gap between the pin and what `@latest` resolves to | Reported as |
|---|---|
| Same version, or a patch (`1.14.0` vs `1.14.3`) | **note** — the intended steady state; a daily defect here would be crying wolf about the design working |
| A minor or major release (`1.13.2` vs `1.14.0`) | **defect** — two feature releases writing one store, the shape [`troubleshooting.md`](troubleshooting.md) row S is about. Re-pin deliberately |
| The registry did not answer, or no server version was recorded | **note**, worded as *NOT measured* — never silence, which would read as "no drift" |

Re-pinning is the same `npm install --prefix` line with the new version. Do it
as a decision, not on a schedule: the reason to pin was to stop an unattended
launch from installing.

## A production service on the same host

Measure, pin, reserve, and run an early killer — all four, whatever the first
step finds. Everything below was measured on three CannObserv VMs (broker,
notifier, wslcb-licensing-tracker) and corroborated on a fourth
(address-validator); where the hosts disagreed, the disagreement is stated
rather than resolved
([#295](https://github.com/gregoryfoster/skills/issues/295),
[#303](https://github.com/gregoryfoster/skills/issues/303),
[#307](https://github.com/gregoryfoster/skills/issues/307)).

### 1. Measure which kind of host this is

Whether the kernel's OOM killer can pick a session process at all **varies by
host**, and it decides which half of the mitigation is load-bearing. Read it
off the processes themselves — `comm` is what the kernel and earlyoom both see:

```bash
for p in $(pgrep -x 'claude|MainThread|npm exec socrat'); do
  printf '%s %s oom_score_adj=%s\n' "$p" "$(cat "/proc/$p/comm")" "$(cat "/proc/$p/oom_score_adj")"
done
```

| Sessions at | Measured on | What follows |
|---|---|---|
| **-1000** | broker; address-validator | Inherited from `sshd` and `exe-init` on broker; address-validator has no `exe-init` process and lands there anyway. **No killer can pick a session** — not the kernel's, and not earlyoom, which skips a -1000 process exactly as the kernel does, `--prefer` or not (`kill.c`, v1.7 and since). VSCode Server, Claude Code and any server they launch are never the victim, so under real exhaustion something else goes, the production service included, and a cgroup cap on a session **stalls** it rather than killing it. The service's `OOMScoreAdjust=` only reorders what *is* killable. The lever that works here is the session's own score: launch it under `choom -n 500 --` (raising is unprivileged), or inside [row U](troubleshooting.md)'s capped scope, which applies the same `choom` and bounds what it can take. |
| **0** | notifier | Only `sshd` and `exe-init` at -1000; every `claude`, `MainThread` and `npm exec socrat` at 0. The kernel's killer *can* pick a session, and so can earlyoom, so the production unit's `OOMScoreAdjust=` is what creates the gap, and a cap on a session **kills** rather than stalls. |

What decides it was not determined, and `exe-init`'s presence is not it:
notifier has one and sits at 0, address-validator has none and sits at -1000.
**The service-side actions below are the same either way.** Do not skip them
after measuring a 0: the reservation keeps reclaim off the service on any host,
and `OOMScoreAdjust=` puts the service behind every process a killer can take —
which, where sessions sit at 0, makes a session the one that goes. Where they
sit at -1000 nothing on the service's side can: add the `choom` launch above.

### 2. Pin

The section above. It removes the 1.2 G peak, which is the only step that makes
the launch itself small.

### 3. Reserve — on the unit, and on every slice above it

Give the production unit a reservation and a lower OOM score:

```ini
# /etc/systemd/system/<unit>.d/10-memory.conf
[Service]
# wslcb's figure — size it to the service.
MemoryLow=256M
# At adj 0 a service reads ~667 (broker), like any small process at 0;
# -500 puts it behind them. It cannot make a -1000 session killable.
OOMScoreAdjust=-500
```

systemd reads a `#` only at the start of a line: a comment after a value
becomes part of it, which is why these sit above.

**Then grant it on the parent, or it is inert.** cgroup v2 caps a unit's
effective protection at what every ancestor grants — the kernel scales a
child's protection by its parent's effective protection
(`effective_protection()` in `mm/page_counter.c`), and systemd documents that
"it is generally required to set a corresponding allocation on all ancestors".
`system.slice` ships `memory.low` 0, so a unit under it is protected by
nothing. The `memory_recursiveprot` mount option does not change that: it
shares a parent's *unclaimed* grant among children that set none, and a parent
at 0 has none to share.

```ini
# /etc/systemd/system/system.slice.d/10-memory-protection.conf
[Slice]
# At least the sum of every child's MemoryLow=.
MemoryLow=512M
```

**A templated unit needs one more.** `foo@bar.service` lives in an implicit
`system.slice/system-foo.slice/`, created with no settings, so it grants 0 and
clamps the unit exactly as `system.slice` did. On address-validator
`postgresql@16-main.service` stayed unprotected under a working `system.slice`
grant until `system-postgresql.slice.d/` had its own; the chain then read
1G / 384M / 384M. A plain unit needs only the `system.slice` grant.

`systemctl daemon-reload` applies the slice grants with no restart.
`OOMScoreAdjust=` is set on the service's process when it starts, so restart
the service for that half, then check its `oom_score`.

**Verify the EFFECTIVE protection — nothing else is evidence.** On
wslcb-licensing-tracker a unit at `MemoryLow=256M` was protected by nothing
while `systemctl show -p MemoryLow`, the unit's own `memory.low`, a clean
`daemon-reload` and a healthy service all agreed it worked. The effective value
is at most the smallest `memory.low` on the way up from the unit, and how many
links that is depends on whether the unit is templated, so walk its real
`ControlGroup` rather than a path you assume:

```bash
unit=<unit>
fs=/sys/fs/cgroup
cg="$(systemctl show "$unit" -p ControlGroup --value)"
eff=max n=0
while [ -n "$cg" ] && [ "$cg" != / ]; do
  v="$(cat "$fs$cg/memory.low")" || break
  n=$((n + 1))
  if [ "$v" != max ] && { [ "$eff" = max ] || [ "$v" -lt "$eff" ]; }; then eff="$v"; fi
  cg="${cg%/*}"
done
if [ "$n" -eq 0 ]; then
  echo "$unit: no memory.low read — is it running?"
else
  [ "$eff" = max ] || eff="$((eff / 1048576)) MiB"
  echo "$unit keeps at most $eff ($n levels read)"
fi
```

"At most": if the children's grants add up past the parent's, each keeps a
share in proportion to its usage, which is why the parent's grant is at least
their sum. `preflight.sh` reads the same chain, top down, for every unit under
`system.slice` that claims a `MemoryLow=`, through nested slices six levels
deep; it names the slice that clamps one, and the slice whose children's
claims add up past its grant.
On wslcb, after the fix, the service read 256 MiB effective. Its
`OOMScoreAdjust=-700` (`oom_score` 208) was calibrated to sit below 300, the
floor of an earlyoom `--prefer` match. That floor is a match whose own
`oom_score` is 0, which is a -1000 process, and earlyoom never takes one; a
session at 0 reads ~667 or more, ~967 as a `--prefer` match. 300 is not a line
worth calibrating to.

### 4. Keep the kernel ahead of exhaustion — `vm.min_free_kbytes`, and earlyoom

Set `vm.min_free_kbytes` so the kernel keeps headroom for atomic allocations —
their failure, not an OOM kill, is how broker's outage presented
(CannObserv/broker#21, #25). Then run earlyoom, which acts before the kernel
has to. Four ways it silently runs something other than what you wrote:

- **No space inside a regex.** Debian's unit is
  `ExecStart=/usr/bin/earlyoom $EARLYOOM_ARGS`, expanded **unquoted**, so
  systemd splits the value into words. The split honours quotes (systemd 255:
  `EXTRACT_RELAX|EXTRACT_UNQUOTE`), but the file's own double quotes are gone
  by then, so a bare space inside a `--prefer` or `--avoid` regex becomes a
  second argument, and earlyoom does not run the configuration you wrote — no
  early killer, under a unit that looks active (#303). Keep spaces out rather
  than quoting around them.
- **No backslash either.** The same split drops a backslash and keeps the
  character after it, so `\.` reaches earlyoom as `.`, which matches anything,
  with no error. A literal dot is `[.]`.
- **Never `$`-anchor `--prefer`.** The regexes match `/proc/<pid>/comm`, which
  the kernel truncates to 15 characters: `npm exec socraticode@latest` is
  `npm exec socrat`, so `^(node|npm|npx)$` never matches the server, with no
  startup error (#307). Spell it `^npm`, start-anchored, which also keeps the
  spaces out. Name `MainThread`: node renames its main thread, so sessions do
  not appear under a matchable binary name.
- **Installing starts it on stock arguments.** `apt install earlyoom` starts
  the daemon before any configuration exists, and `systemctl enable --now` on
  an already-active unit reloads nothing — wslcb and address-validator both sat
  `active` and `enabled` on Debian's `-r 3600`, with no `--prefer` and no
  `--avoid`. **Restart it** after writing the file.

One working configuration — name *this* host's production service in
`--avoid`:

```sh
# /etc/default/earlyoom
EARLYOOM_ARGS="-r 3600 -m 12,6 --avoid ^(uv|uvicorn|postgres|tailscaled|systemd|sshd|exe-init)$ --prefer ^(MainThread|claude|npm|node|npx)"
```

```bash
sudo systemctl restart earlyoom
# Each regex must come back as ONE argument:
tr '\0' '\n' < "/proc/$(systemctl show earlyoom -p MainPID --value)/cmdline"
# …and the daemon states what it parsed at startup:
journalctl -u earlyoom -b | grep -E 'Preferring|avoid|SIGTERM'
```
