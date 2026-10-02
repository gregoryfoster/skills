# Policy: postures, lanes, exceptions and owners

What a host is compared against. The probe reports a host's actual state, and any difference from the posture it declares is a **finding** unless an exception covers it. The skill never changes a host's posture on its own initiative: unmasking timers or editing apt or needrestart config is provisioning's job, or an owner-approved remedy.

## Two postures

A host declares one in its knob ([knob.md](knob.md)). **With no knob, or no `posture` line, the probe compares the host against `automatic`**, the reference policy, and reports every deviation, but never applies anything. A cohort that runs `scheduled` commits its knob to say so.

### `automatic`: the generic reference policy

Ubuntu's stock unattended-upgrades posture, plus one needrestart setting:

- the apt timers enabled, and `APT::Periodic::Enable "1"` effective. On the Docker base image it must be set in a file sorting after `docker-disable-periodic-update`, which sets it to 0;
- `unattended-upgrades` taking `-security` only;
- no automatic reboot;
- needrestart set to **list** restarts rather than perform them (`$nrconf{restart} = 'l';` in a `conf.d` drop-in).

It suits a host with **no local data store**. On a host with one it means unscheduled data-store restarts: `postgresql-16`'s maintainer script restarts the cluster whatever needrestart is set to, and so do others ([environments/exe-dev-exeuntu.md](environments/exe-dev-exeuntu.md)).

### `scheduled`: an owner-approved monthly run

The host is patched in a scheduled, gated run once a month, and the apt timers stay masked. A run is:

- a chosen window, clear of whatever the knob says constrains it;
- a fresh recovery point, copied off the node, for each declared data store. A host with no data store records its before-versions;
- the apply in held steps, each approved;
- a reboot if needrestart's list or `reboot-required` calls for one;
- the verification;
- a record.

The procedure is [run.md](run.md). This is the answer to #313's D4 (decided 2026-09-29), and the posture the CannObserv cohort took. The host repo's owner is accountable for the window, and approves each run in that host's own session.

The needrestart drop-in is part of both postures: every run relies on the hook restarting nothing.

## Two lanes

| Lane | Selection | Cadence |
|---|---|---|
| **security** | Ubuntu `-security` | daily under `automatic` (the apt timers); monthly under `scheduled` |
| **maintenance** | the security lane's, plus Ubuntu `-updates` and each third-party origin whose policy is *follow*: `apply.sh --lane maintenance` | monthly |

- **Under `scheduled`, both lanes run in the same monthly window.**
- **A security package never waits for the maintenance lane.** docker.io 29 and containerd 2.2 shipped in `noble-security`, so holding them "for the maintenance lane" leaves a security fix with no lane at all. Deferring one is an exception, with a reason and a review-by date.
- **Third-party origins** each get a policy in the knob: *follow* (taken in the maintenance lane), *pin* (a stated version), or *hold, with a reason*. The lane never takes a pinned or held one: a pin moves only by hand.
- **Tailscale** belongs in the maintenance lane, because upgrading tailscaled drops the host's tailnet path and needs a planned window. A Tailscale security bulletin expedites it into an out-of-cycle window.

## What a run leaves pending, by class

Every run records what it didn't take, in five classes:

1. **security**: should be 0 after a security-lane run;
2. **`-updates`**: the maintenance lane;
3. **third-party**: by origin and its policy;
4. **Ubuntu Pro / ESM**: `noble-security` doesn't patch `universe`. On wslcb, 546 of 1,617 installed packages came from universe, and 29 esm-apps security updates were pending on a host not attached to Pro (CannObserv/wslcb-licensing-tracker#184). Read it with `pro security-status` where `pro` exists. **"0 security pending" never covers this class.** Attaching Pro is the owner's decision; the skill only reports;
5. **outside apt**: agent binaries, container images, pinned tools, each with its owner (below).

## Exceptions

A deviation the owner accepts is declared, not ignored:

```
exception <what> <review-by YYYY-MM-DD> <reason>
```

- A passed review-by date **expires** the exception, and the deviation becomes a finding again.
- Keeping a dormant component is an exception: `exception keep:<component> <review-by> <reason>`.
- Each prune stage is declared the same way, as `disabled:<component>`, `removed:<component>` or `purged:<component>`. The review-by date is the prune calendar: when it passes, the probe proposes the next stage. A `purged:` line stays until the base image stops shipping the component.
- **A package hold is declared as `held:<package>`.** A hold on a package in the pending set defers its update, and a security package never waits without an exception ([Two lanes](#two-lanes)). So an undeclared hold on a pending package is a finding, whether the owner placed it or an aborted run left it ([run.md](run.md)).

**What `<what>` names.** Each probe finding an exception can cover carries it as `exception_what`:

| `<what>` | The deviation |
|---|---|
| `timer:<unit>` | `apt-daily.timer` or `apt-daily-upgrade.timer` isn't enabled under `automatic`, or isn't masked under `scheduled` |
| `periodic:<key>` | `APT::Periodic::Enable` isn't 1, `Update-Package-Lists` or `Unattended-Upgrade` is under 1, or one is set nowhere (`automatic`) |
| `package:unattended-upgrades` | it isn't installed (`automatic`) |
| `uu:origins` | unattended-upgrades takes more than `-security` and the release pocket, or no origin is set (`automatic`). `apply.sh` refuses the first under either posture unless this covers it, since the security lane would apply the rest too |
| `uu:automatic-reboot` | `Unattended-Upgrade::Automatic-Reboot` is true, or set nowhere (`automatic`) |
| `needrestart:restart` | no file sets `$nrconf{restart}` to `l`, or the file doesn't load (both postures) |
| `held:<package>` | an owner's hold on a pending package |
| `database:<name>` | a cluster database no `datastore` line names |
| `ordering:<service>` | a `service` with no `After=` on a data store |
| `journal:volatile` | the journal doesn't survive a reboot |
| `session:adj` | the session's chain to PID 1 runs at `oom_score_adj` -1000 |
| `keep:<component>` | a dormant component the owner keeps; a prune stage is `disabled:`, `removed:` or `purged:` |

The rest take no exception, because each is fixed where it is:
- a provisioning leftover, such as the setup script;
- a knob gap: an undeclared restarter, backup regime or third-party origin;
- a failing health check;
- a pending reboot.

## Dormant components

An installed engine or daemon that nothing uses is patch surface, disk and attack surface for no benefit. nginx was disabled on six hosts yet in every one's security set. The probe reports the evidence; it never removes anything.

- **The verdict** is `in-use`, `dormant`, `kept` (an exception) or `unknown`.
- **`dormant` needs 30 days of evidence** (decided 2026-09-27): uptime, database statistics since their reset, container history. Anything younger is `unknown`, as is anything the probe couldn't read. **No row written isn't idleness:** an app may only read, so a database with no write but a session since its statistics were reset is `unknown`. Likewise a Redis with no key may be a cache whose keys expired, or a bus: a lookup, an expiry, a subscription or another client since it started means it's in use. A volatile journal (see the profile) often can't reach back 30 days, so name the evidence source for each verdict.
- **A prune** runs on a disable → remove → purge calendar with a 30–90-day soak. With a savepoint (config tarball, before-versions, an off-node dump where data exists), the remove stage is skipped. The operator chooses the path, and can shorten any soak (decided 2026-09-27). The stages and their scripts: [pruning.md](pruning.md).
- **A prune covers groups and memberships, not only packages and units.** watcher's Docker removal left the `docker` group with `exedev` in it, which would make `exedev` root-equivalent the moment Docker returned (CannObserv/watcher#336).

## Owners

Every component apt doesn't reach has an update owner:

- **the image** (on exe.dev, also the platform's `exeuntu update`) owns what the image ships. A repo names whose image it is with a knob line, `image-owner <owner/name>`, and can assign one component elsewhere with `owner <glob> <repo>`. Until a knob names the image owner, what the image ships is recorded as owned by `image`, and no notice is proposed;
- **the repo** that installed a component owns it (a pinned tool, a container image);
- **the skill** only reports staleness and the owner. It updates none of them.

When an update is available for a component another repo owns, the skill proposes an issue in that repo. It files one only on approval, one per component, and deduplicates against an open issue by a hidden marker. A notice to a public repo carries no private-repo identifier, and no notice carries a secret.
