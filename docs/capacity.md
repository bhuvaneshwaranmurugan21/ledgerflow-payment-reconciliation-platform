# Modeled production capacity

Classification: `MODELED_PRODUCTION_CAPACITY`

The reference requirement is 10 million lifecycle arrivals per day across 20 logical sources.
This is a sizing model, not a retained cloud benchmark.

```text
average events/second = 10,000,000 / 86,400 = 115.74
modeled peak factor   = 12
peak events/second    = 1,388.89
modeled event size    = 1.5 KiB
peak ingress          = 2.03 MiB/second
```

Kinesis provisioned capacity must satisfy both bytes and records. With operational headroom,
the initial modeled stream uses four shards and scales from observed `IncomingBytes`,
`IncomingRecords`, throttles and hot-key distribution.

Glue and Redshift sizes are deliberately variables. A production acceptance report must retain
worker type/count, immutable input checksum, five measured runs after warm-up, runtime percentiles,
shuffle/spill, output files, DPU-hours, query concurrency and cost. No local timing is extrapolated
into an AWS throughput claim.

