# Data stores: Redis and Qdrant

What each engine a `datastore` line names takes, beyond [run.md](run.md)'s steps. Postgres's dump and its three gates are run.md §2's own example.

## Redis

### Reaching it

- **Whether the unit's own Redis listens at its address is read from the socket**, as root (`ss -Hltnp`, or `ss -Hlxp` for a socket path), with no login: the unit's `MainPID` must be among the listeners. The address comes from the unit's file and its own arguments, which Redis takes over the file's.
- **A command that needs a login** (a dump's `BGSAVE`, a save before a backup runs, the chain's `SAVE`) logs in as the `datastore redis <unit> <user> <key-file>` line's user. Its key file is root-only, or a `systemd-creds` credential under `/etc/credstore.encrypted/`, which root decrypts. The password reaches `REDISCLI_AUTH` inside root's own sh, never an argv.
- **With no user on the line**, the scripts log in as `default` with the file's `requirepass`. **Under an `aclfile` they don't try it**: the users are the aclfile's, and broker's `requirepass` is a password nobody holds. A command that needs a login then refuses before it runs.
- **A refused login is an `ACL LOG` entry** the host has to attribute (CannObserv/broker#48). So the scripts try one only where a command needs it, and only once. They name it (`NOAUTH`, `WRONGPASS` or `NOPERM`), never "reaches no Redis" (#379). Never re-enable `default`, or widen an ACL, to get past one.
- Measured on noble's 7.0:
  - an anonymous command gets `NOAUTH` and writes nothing to `ACL LOG`;
  - a failed login prints `AUTH failed: …` on stderr and `NOAUTH` on stdout, exits 0, and writes an `ACL LOG` entry;
  - a save's child closes the listening sockets.

### The recovery point

- **A dump:** `BGSAVE`, wait until `LASTSAVE` moves past the request and the save reports ok, then copy the RDB file as root at mode 600, and read it back with `redis-check-rdb` where it's installed.
- **A backup unit that ships the RDB file ships it as it stands**, and Redis rewrites the file only at a save point: broker's was 44 minutes old, with 91 changes since (#382). So `recovery-point.sh` saves each Redis a `backup` line covers before it starts the unit: a `BGSAVE` and the wait, where it can log in. Where it can't, it reads the file's own time (`dir` and `dbfilename` from the file, as root), and refuses one written more than `--rdb-within` (600 s) before the run began. Then `SAVE` by hand, as a user that may, and take the recovery point again.
- **The record says how each Redis persists:** `persistence redis <unit> aof|rdb|none|unknown`, read from its file and arguments, whether it was dumped or shipped.

### The chain's stop

`systemctl stop` fsyncs the AOF under `appendonly yes`, and saves the RDB file where save points are set. With no `save` line, Redis keeps its default save points; `save ""` clears them, and a later `save` line adds them back (measured on 7.0). `reboot-chain.sh` reads which from the file and the unit's arguments, as root, so it logs in only to `SAVE` a Redis with neither. Where an `include`, or a file root can't read, leaves it unknown, the chain asks at the stop. A Redis that isn't running at the gate has nothing to save.

### A restore under `appendonly yes`

**It isn't a copy of the RDB file** (#381). Redis then loads its AOF at start and ignores `dump.rdb`, so an RDB file copied back into place restores nothing: the server comes up from whatever AOF is there, or an empty one.

Stage the RDB file as the AOF's base instead, with Redis stopped. Under multi-part AOF (7.0 and later):
- it becomes a new `appendonly.aof.<n>.base.rdb` in `appenddirname`;
- beside an empty `appendonly.aof.<n>.incr.aof`;
- and `appendonly.aof.manifest` names just those two (`file … seq <n> type b`, then `type i`).

Measured on noble's 7.0: a snapshot copied over `dump.rdb` came up with the AOF's keys, and the same file staged as the base came up with its own. Or use the host's own restore procedure, as broker's `docs/RECOVERY.md` is. The record's `persistence redis <unit> aof` says when this applies, and so does `recovery-point.sh`'s `next`. A backup line that ships the RDB file carries the same caveat.

### After a restart

`probe.sh --post-boot` reads each Redis from its own log, and so does a held step that restarted one (noble's `redis-server` postinst does). That log is the `logfile` its file sets, read as root, or the unit's journal where it sets none. broker's logs to a file, so a check of the journal alone would read an empty pass (#380). Its run starts at its main PID's banner, or its first line after another process's, since a PID can come round again after a boot. The check wants:
- **the process before it** to have ended on `Redis is now ready to exit, bye bye...`, a clean shutdown;
- **this one** to have logged `DB loaded from …` where it persists anything, then `Ready to accept connections`.

Under `appendonly yes`, `Creating AOF base file … on server start` means it found no AOF, so it loaded nothing: the check fails, and the recovery point is what restores it. `keys loaded: <N>` counts the RDB base alone, not the incr's keys, so it's no total (measured on 7.0). A held step asks once a second, for up to `--health-within` seconds, until it logs that it's ready.

## Qdrant

### The recovery point

Each collection's exact point count, kept on the node, then a full-storage snapshot through its API (`POST /snapshots?wait=true`), as #367 decided. **Copy it out of the container:** its snapshots directory isn't on a volume, so under `docker run --rm` the next restart deletes it (co-index: 1.56 GB in 48 s). The copy counts when it reads back with `tar -tf`, at mode 600, with its sha256 read; then delete the copy inside.

### After a restart

Its collections are checked against the recovery point's counts after the boot. A held step that restarted it gets the same check (Docker's restart does, through `Requires=`). The check asks once a second, for up to `--health-within` seconds, while it loads its collections; a held step's span budgets that time on top of its health checks (CR 218). Clients may still be writing, so a count may move either way: only a collection gone or emptied is a loss, and counts that can't be read fail. A real query stays a `health` line, since the embedding model is the host's own.
