# ADR 0004: Keep local evidence separate from production capacity

Status: Accepted

SQLite is used to prove transaction boundaries, replay behavior and failure recovery on synthetic
data. It does not emulate Iceberg performance or AWS availability. Production volume, SLO and cost
numbers remain modeled requirements until a retained cloud benchmark and deployment report exist.

This makes the repository useful in review without presenting an unexecuted architecture as a
measured production result.
