# Bus roles (writer/reader-per-bus)

`eigsep_redis` exposes a shared `Transport` and paired `*Writer` / `*Reader`
classes — one pair per logical bus (metadata, status, heartbeat, config,
corr, vna). Two invariants, both structural:

1. **Wrong-bus writes are impossible.** `MetadataWriter` has no method that
   accepts a VNA payload. Enforced by
   `test_bus_classes_have_no_cross_bus_methods` in `tests/test_redis.py`.
2. **Wrong-role access is `AttributeError`.** A `PandaClient` has no
   `corr_reader`; an `EigObserver` has no `corr`/`vna` writer. Each role
   builds only the surfaces it needs. Enforced by
   `test_consumer_role_surfaces_are_structural`.

Source:
- [`eigsep_redis/src/eigsep_redis/{transport,metadata,status,heartbeat,config}.py`](https://github.com/EIGSEP/eigsep_redis/tree/v2.1.0/src/eigsep_redis)
- [`eigsep_redis/CLAUDE.md`](https://github.com/EIGSEP/eigsep_redis/blob/v2.1.0/CLAUDE.md) — architecture prose

## Metadata has two readers, on purpose

- `MetadataStreamReader.drain()` — streaming, used by the corr loop for
  per-integration averaging.
- `MetadataSnapshotReader.get()` — point-in-time, used for VNA packaging.

They look inconsistent but aren't. See `eigsep_observing/CLAUDE.md` for the
full rationale.
