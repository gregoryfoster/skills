# Host memory — the install peak, and a production service beside the session

Row U of [`troubleshooting.md`](troubleshooting.md), as procedures. Two
halves: the launch installs, and that install is the measured peak, so don't
install at launch; and on a host that also runs a production service, give that
service memory the sessions cannot take — then check that the setting which
says so actually does. `preflight.sh` reports total memory, swap, and whether a
unit's `MemoryLow=` can take effect on this host.

## Don't install at launch: the pinned pre-install

The plugin launches `npx -y --prefer-online socraticode@latest` unless
`SOCRATICODE_SPEC` says otherwise (below), and `mcp-driver.mjs` reused that
command verbatim — so the health hook, `index`,
`status` and `verify` each installed a server before talking to one.
`--prefer-online` revalidates against the registry on *every* launch, so a warm
cache is not a warm path on any day the package moved.

Install once, deliberately, under a cap:

```bash
# Pick the version deliberately — a literal, never `latest`, or the pin floats
# and buys nothing. This is what the plugin's own command would have resolved:
npm view socraticode version

# Linux with user systemd — the cap is the point; on a small host, run it here
# and nowhere else. choom as in row U: a session at -1000 (below) hands that
# score to the install, and at -1000 the cap stalls it instead of killing it.
systemd-run --user --scope -p MemoryHigh=1200M -p MemoryMax=1536M \
  choom -n 500 -- npm install --prefix ~/.socraticode/pin socraticode@<version>

# Anywhere else (macOS, a host without user systemd): the install is the same,
# just uncapped. Size the host for ~1.2 G rather than hoping.
npm install --prefix ~/.socraticode/pin socraticode@<version>
```

`resolveServerLaunch()` prefers that build over the plugin's command, so no
driver launch installs anything. Nothing else has to be configured: absent, the
pin resolves nothing and the chain is exactly what it was.
`SOCRATICODE_PIN_DIR` moves it; `node "<SKILL_DIR>/scripts/mcp-driver.mjs"
resolve` says which path won, without launching a server.

**Pin the session too: `SOCRATICODE_SPEC`.** The pin above covers the
driver's launches — the health hook, `index`, `status`, `verify`. The session's
server is the plugin's, and since upstream
[`0c33776`](https://github.com/giancarloerra/socraticode/commit/0c33776) (2026-09-20)
the plugin reads its package spec from a variable: its launch is
`npx -y --prefer-online ${SOCRATICODE_SPEC:-socraticode@latest}`. Set it to the
pin's version, so both launches are one build, **in Claude Code's environment
when it starts**:

| Claude Code runs from | Set it in |
|---|---|
| the VS Code extension | `claudeCode.environmentVariables` — a machine-scoped setting, so your user `settings.json`, or on a remote `~/.vscode-server/data/Machine/settings.json`; never a committed workspace setting |
| a terminal | an export in the shell that launches `claude` |

```json
{ "claudeCode.environmentVariables": [{ "name": "SOCRATICODE_SPEC", "value": "socraticode@<version>" }] }
```

**The repo's settings `env` block is not enough on its own.** On watcher,
notifier and address-validator (Claude Code 2.1.280, VS Code, after a full
reconnect) it reached the server's environment but not its launch: the
plugin's args were expanded before the block was merged, so the server ran
`npm exec socraticode@latest` with `SOCRATICODE_SPEC=socraticode@1.14.0` in its
environment. The machine setting pinned all three — though each reconnect also
moved the extension to 2.1.281, so whether the block alone works there is not
measured. On co-replicator (#327) the block alone worked, and why the hosts
differ is not known. Keep the block as the declared value if you like —
preflight compares against it — but not as the mechanism
([#332](https://github.com/gregoryfoster/skills/issues/332)).

**The first launch of a new exact spec installs.** npx keys its cache on the
spec string, so a warm `socraticode@latest` tree does not serve
`socraticode@1.14.0`, and the first session to launch it does a full, uncapped
install at an unattended start — #295's peak, once. Warm it deliberately,
under the cap; this builds the tree the plugin's pinned launch then uses:

```bash
systemd-run --user --scope -p MemoryHigh=1200M -p MemoryMax=1536M \
  choom -n 500 -- npm exec --yes --prefer-online --package=socraticode@<version> -- true
```

From then on an exact version resolves from the npx cache without installing —
the fix for the install at launch on a small or co-tenant host.
`preflight.sh` reports both pins, names a pinned spec no npx cache tree holds,
and says when the installed plugin does not read the variable
([#327](https://github.com/gregoryfoster/skills/issues/327)).

**Read the launched command, never a manifest.** The plugin ships three launch
manifests, and only the one `.claude-plugin/plugin.json` names is live:

| File | Launches | Live under Claude Code? |
|---|---|---|
| `.claude-plugin/mcp.json` | `${SOCRATICODE_SPEC:-socraticode@latest}` | **yes** — `plugin.json`'s `mcpServers` names it |
| `.mcp.json`, `mcp.json` (plugin root) | hardcoded `socraticode@latest` | no — since `0c33776`; before it, `plugin.json` named `./.mcp.json` |

Reading a root one confirms that the session cannot be pinned, and that is how
#295 came to say so. The variable also landed after the 1.14.0 release with no
version bump, so a cache directory labelled `1.14.0` can predate it: its
`plugin.json` names `./.mcp.json`, and the variable does nothing there.
`claude plugin update` can report success and keep reusing that directory;
move it aside and update again.

The process table is the only evidence of what launched — the server whose
parent is the session's own `claude`, which is `$PPID` in the Bash tool's shell:

```bash
ps -eo pid,ppid,args | awk -v p="$PPID" '$2 == p && $3 == "npm" && $4 == "exec"'   # e.g. `npm exec socraticode@1.14.0`
```

`claude mcp list` from a session shell is not evidence. It starts a server of
its own with that shell's environment, which carries the variable, so it
prints what a launch *with* it runs; in a folder the CLI has not trusted it
ignores the project block altogether. Nor is the variable in the session's
environment, which the block reaches either way. `preflight.sh` and
`health-check` read the process table themselves, and report a pin they could
not observe as not observed ([#332](https://github.com/gregoryfoster/skills/issues/332)).

**A pinned driver beside a floating session is a new divergence.** Before the
pin both floated and agreed by coincidence of timing; with only the driver
pinned, the driver is deterministic while the session goes on floating.
`health-check` measures it, and splits on how wide the gap is, because a pin is
*meant* to lag:

| Gap between the pin and what `@latest` resolves to | Reported as |
|---|---|
| Same version, or a patch (`1.14.0` vs `1.14.3`) | **note** — the intended steady state; a daily defect here would be crying wolf about the design working |
| A minor or major release (`1.13.2` vs `1.14.0`) | **defect** — two feature releases writing one store, the shape [`troubleshooting.md`](troubleshooting.md) row S is about. Re-pin deliberately |
| The registry did not answer, or no server version was recorded | **note**, worded as *NOT measured* — never silence, which would read as "no drift" |

Re-pinning is the same `npm install --prefix` line with the new version —
and the same version in `SOCRATICODE_SPEC`, its npx tree warmed first. Do it
as a decision, not on a schedule: the reason to pin was to stop an unattended
launch from installing.

## The health hook caps itself

`socraticode-health.sh` is the one launch nobody watches — SessionStart, once
a UTC day — and until
[#330](https://github.com/gregoryfoster/skills/issues/330) nothing capped it: on
co-replicator (3.82 GiB, no swap, a production co-tenant) it was the host's
only uncapped launcher. It now runs its check in [row U](troubleshooting.md)'s
scope wherever the host can create one. The probe is the same
`systemd-run --user --scope` command with the same properties, because a bare
probe succeeds where the properties are unsupported and the real call then
fails closed. Its payload asks systemd, from inside the scope, for the scope's
`MemoryCurrent`: without a memory controller — cgroup v1, or none delegated to
the user manager — `MemoryMax=` is accepted and never enforced, and on systemd
255 a 320 MB payload outlived a 64M cap. Where the host cannot cap — macOS, no
user systemd, no memory controller — the check runs uncapped as before, and
silently; a failed probe leaves a line in its log. A check the cap stops is
reported as stopped by its cap, and never re-run uncapped.
`SOCRATICODE_HEALTH_CAP` sets the properties, or `off`. Set it in
`.claude/settings.local.json`'s `env` block, since a ceiling belongs to the
host, not to every clone of the repo. A value the probe rejects runs uncapped
too; the log line names systemd's reason.

It is defence in depth, not the fix. Pinned, the hook's launch installs nothing
and peaks near 75 MB; the cap is for a host that never pinned, a pin that broke
(the pin directory removed, a re-pin mid-install), and an index that grew.

**A hand-rolled wrapper can go.** CannObserv/replicator wrapped the hook's
command in `.claude/settings.json` (`fb73b74..fba4cd9`). The installer rebuilds
that command from its constants on every run
([#259](https://github.com/gregoryfoster/skills/issues/259)), so the next Step C
re-run removes the wrapper, silently — which is why the cap lives in the
script, and why removing the wrapper now loses nothing. Kept, it is redundant:
the hook's own scope takes the payload.

## A production service on the same host

Measure, pin, reserve, and keep the kernel ahead of exhaustion — all four,
whatever the first step finds. The first step decides only what an early
killer is worth (§4). Five CannObserv VMs, and most findings rest on one of
them: broker (the install peak, sessions at -1000), notifier (sessions at 0,
the spaced earlyoom regex), wslcb-licensing-tracker (the inert `MemoryLow=`,
the `$`-anchored `--prefer`, earlyoom on stock arguments), address-validator
(the templated-slice clamp, and -1000 with no `exe-init` — both measured
there alone — plus the stock-arguments earlyoom again) and replicator (-1000
with swap — 8 GiB and 4 G when #331 measured it — where a dry run showed what
earlyoom reaches, and it was declined). Where the hosts disagreed, the
disagreement is stated rather than resolved
([#295](https://github.com/gregoryfoster/skills/issues/295),
[#303](https://github.com/gregoryfoster/skills/issues/303),
[#307](https://github.com/gregoryfoster/skills/issues/307),
[#331](https://github.com/gregoryfoster/skills/issues/331)).

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
| **-1000** | broker; address-validator; replicator | Inherited from `sshd` and `exe-init` on broker; address-validator has no `exe-init` process and lands there anyway. **No killer can pick a session** — not the kernel's, and not earlyoom, which skips a -1000 process exactly as the kernel does, `--prefer` or not (`kill.c`, v1.7 and since), so its `--prefer` reaches only a `choom`'d launch (§4). VSCode Server, Claude Code and any server they launch are never the victim, so under real exhaustion something else goes, the production service included, and a cgroup cap on a session **stalls** it rather than killing it. The service's `OOMScoreAdjust=` only reorders what *is* killable. The lever that works here is the session's own score: launch it under `choom -n 500 --` (raising is unprivileged), or inside [row U](troubleshooting.md)'s capped scope, which applies the same `choom` and bounds what it can take. |
| **0** | notifier | Only `sshd` and `exe-init` at -1000; every `claude`, `MainThread` and `npm exec socrat` at 0. The kernel's killer *can* pick a session, and so can earlyoom, so the production unit's `OOMScoreAdjust=` is what creates the gap, and a cap on a session **kills** rather than stalls. |

What decides it was not determined, and `exe-init`'s presence is not it:
notifier has one and sits at 0, address-validator has none and sits at -1000.
**The service-side actions below are the same either way.** Do not skip them
after measuring a 0: the reservation keeps reclaim off the service on any host,
and `OOMScoreAdjust=` puts the service behind every process a killer can take —
which, where sessions sit at 0, makes a session the one that goes. Where they
sit at -1000 nothing on the service's side can: add the `choom` launch above.

**Pin the reading, since nothing pins its cause.** A host can change class
under you, and the earlyoom configuration in §4 then silently means something
else. CannObserv/replicator holds its reading with a test: it walks from its
own process up to the child of `exe-init` or `sshd`, asserts that session
root's `oom_score_adj` is still what the host's configuration assumed, fails
naming the issue to reopen, and skips in CI and outside a session
(`bcf3e5a`, `TestTheEarlyoomDecline`). A host at 0 asserts the opposite.

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
`system.slice/system-foo.slice/`, created with no settings, so it grants 0.
Without `memory_recursiveprot` (address-validator's bare `rw` mount) that
clamps the unit exactly as `system.slice` did: there
`postgresql@16-main.service` stayed unprotected under a working `system.slice`
grant until `system-postgresql.slice.d/` had its own; the chain then read
1G / 384M / 384M. With it — systemd's mount wherever the kernel supports it —
the slice passes down a share of `system.slice`'s unclaimed grant in
proportion to usage: no clamp, and no reservation either, so grant it anyway.
A plain unit needs only the `system.slice` grant.

`systemctl daemon-reload` applies the slice grants with no restart.
`OOMScoreAdjust=` is set on the service's process when it starts, so restart
the service for that half, then check its `oom_score`.

**Verify the EFFECTIVE protection — nothing else is evidence.** On
wslcb-licensing-tracker a unit at `MemoryLow=256M` was protected by nothing
while `systemctl show -p MemoryLow`, the unit's own `memory.low`, a clean
`daemon-reload` and a healthy service all agreed it worked. The effective value
is at most the smallest `memory.low` on the way up from the unit — without
`memory_recursiveprot`; with it, a link granting less passes a usage-dependent
share this walk cannot read — so grant every link, which makes its figure the
unit's reservation either way. How many links there are depends on whether the
unit is templated, so walk its real `ControlGroup` rather than a path you
assume:

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
deep; it names the slice that clamps one (with `memory_recursiveprot`, that
passes it only a share), and the slice whose children's claims add up past its
grant.
On wslcb, after the fix, the service read 256 MiB effective. Its
`OOMScoreAdjust=-700` (`oom_score` 208) was calibrated to sit below 300, the
floor of an earlyoom `--prefer` match. That floor is a match whose own
`oom_score` is 0, which is a -1000 process, and earlyoom never takes one,
though a dry run prints the 300 anyway (§4); a session at 0 reads ~667 or
more, ~967 as a `--prefer` match. 300 is not a line worth calibrating to.

### 4. Keep the kernel ahead of exhaustion — `vm.min_free_kbytes`, and earlyoom where it reaches a session

Set `vm.min_free_kbytes` so the kernel keeps headroom for atomic allocations —
their failure, not an OOM kill, is how broker's outage presented
(CannObserv/broker#21, #25). That holds on either kind of host. earlyoom acts
before the kernel has to, and what it can act on is §1's reading:

| Sessions at | What its `--prefer` reaches | So |
|---|---|---|
| **0** | every session process — `MainThread`, `claude`, `npm exec socrat` | run it as configured below; it takes a session before the service |
| **-1000** | only a launch raised with `choom -n 500 --`; nothing else in a session | it is only as useful as the `choom` discipline around what it would need to kill. Otherwise it sheds small adj-0 daemons — the user manager, cron, logind, `tailscaled` unless avoided — in the kernel's own order, just sooner, freeing tens of MiB. That is a legitimate reason to decline it; replicator did |

On replicator's dry run a `choom`'d `node` was the victim at badness 1313;
without one it was `(sd-pam)` at 733. Two cohort hosts at -1000 installed
earlyoom and documented it as preferring dev tooling, which it never selects
there ([#331](https://github.com/gregoryfoster/skills/issues/331)).

**Read a dry run by its verdict, not its scores.** This kills nothing and
needs no root:

```bash
apt-get download earlyoom && dpkg-deb -x earlyoom_*.deb x
# Thresholds forced so it selects a victim at once; --dryrun sends no signal.
timeout -s INT 2 ./x/usr/bin/earlyoom --dryrun -d -r 0 -m 99,98 -s 100,100 \
  --prefer '^(MainThread|claude|npm|node|npx)' 2>&1 | grep -E '^pid|^sending' | head -20
```

The `-d` table prints each badness **before** the -1000 skip, which runs after
the `--prefer` bonus is added (`kill.c:242-253`, v1.7). So a -1000
`MainThread` at 300 there means "would be 300 if it were eligible" — how a
cohort table came to list eight of them as candidates. Read the row marked
`<--- new victim` and the `sending` line, never the badness column.

Five ways it silently runs something other than what you wrote:

- **No space inside a regex.** Debian's unit is
  `ExecStart=/usr/bin/earlyoom $EARLYOOM_ARGS`, expanded **unquoted**, so
  systemd splits the value into words. The split honours quotes (systemd 255:
  `EXTRACT_RELAX|EXTRACT_UNQUOTE`, confirmed through a transient unit on
  255.4), but the file's own double quotes are gone by then, so a bare space
  inside a `--prefer` or `--avoid` regex becomes a second argument, and
  earlyoom does not run the configuration you wrote — no early killer, under a
  unit that looks active (#303). Keep spaces out rather than quoting around
  them.
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
- **With swap, the memory threshold waits for swap.** earlyoom acts only when
  memory **and** swap are both below their minimums, and the package default
  is `-s 10`. On a host with swap, `-m 12,6` alone acts only after swap is ~90%
  used: on replicator (4 G, `vm.swappiness=10`) ~3.7 GB paged out before the
  first SIGTERM, and a dry run's startup line says so (`swap <= 10.00%`).
  `-s 100,100` lets memory alone decide, and changes nothing where there is no
  swap. Both figures: `-s 100` alone leaves SIGKILL's at half of it, so
  SIGKILL still waits until swap is half used. Keep the default only where
  paging first is the trade you mean.

One working configuration — name *this* host's production service in
`--avoid`. At -1000 its `--prefer` reaches only `choom`'d launches (above):

```sh
# /etc/default/earlyoom
EARLYOOM_ARGS="-r 3600 -m 12,6 -s 100,100 --avoid ^(uv|uvicorn|postgres|tailscaled|systemd|sshd|exe-init)$ --prefer ^(MainThread|claude|npm|node|npx)"
```

```bash
sudo systemctl restart earlyoom
# Each regex must come back as ONE argument:
tr '\0' '\n' < "/proc/$(systemctl show earlyoom -p MainPID --value)/cmdline"
# …and the daemon states what it parsed at startup:
journalctl -u earlyoom -b | grep -E 'Preferring|avoid|SIGTERM'
```
