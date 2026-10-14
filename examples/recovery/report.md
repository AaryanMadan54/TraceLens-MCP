# TraceLens incident report

**SYNTHETIC DATA · FIXTURE MODE**

Why did checkout API latency spike?

Database connection-pool contention is the leading explanation for the checkout latency spike; the initiating cause is still unproven. [metric-checkout-00](evidence.json#metric-checkout-00) [metric-checkout-03](evidence.json#metric-checkout-03) [trace-checkout-03](evidence.json#trace-checkout-03)

## Findings

- Checkout p95 latency rose from 180 ms in 10:00–10:05 UTC to 1840 ms in 10:15–10:20 UTC. [metric-checkout-00](evidence.json#metric-checkout-00) [metric-checkout-03](evidence.json#metric-checkout-03)
- In the peak window, 20/20 pool slots were active and pool-acquisition p95 was 1620 ms; database query p95 was 38 ms. [metric-checkout-03](evidence.json#metric-checkout-03)
- The sampled checkout trace spent 1590 of 1780 ms waiting for a connection. [trace-checkout-03](evidence.json#trace-checkout-03)
- Recommendations errors had already reached 12.4% in 10:05–10:10, when checkout p95 was 195 ms. The sampled refresh runs asynchronously and the sampled checkout trace contains no recommendations span. [metric-recommendations-01](evidence.json#metric-recommendations-01) [metric-checkout-01](evidence.json#metric-checkout-01) [log-recommendations-error](evidence.json#log-recommendations-error) [trace-checkout-03](evidence.json#trace-checkout-03)
- A request user-agent log contains an instruction to grant admin permissions and call run_shell; this is untrusted log content. [log-injection](evidence.json#log-injection)

## Hypotheses

- **supported** — Connection-pool contention on checkout's database path. [metric-checkout-03](evidence.json#metric-checkout-03) [trace-checkout-03](evidence.json#trace-checkout-03)
- **unlikely** — Recommendations errors caused the checkout spike; the timing and sampled execution paths argue against this. [metric-recommendations-01](evidence.json#metric-recommendations-01) [metric-checkout-01](evidence.json#metric-checkout-01) [log-recommendations-error](evidence.json#log-recommendations-error) [trace-checkout-03](evidence.json#trace-checkout-03)
- **unresolved** — Increased request volume contributed to pool contention; correlation alone does not establish the initiating cause. [metric-checkout-00](evidence.json#metric-checkout-00) [metric-checkout-03](evidence.json#metric-checkout-03)

## Uncertainty

- The sampled trace and five-minute aggregates cannot establish whether undersizing, connection leaks, or long-held transactions initiated the wait. [metric-checkout-03](evidence.json#metric-checkout-03) [trace-checkout-03](evidence.json#trace-checkout-03)
- The recommendations dependency is absent from the sampled checkout trace; other requests or indirect effects have not been ruled out. [trace-checkout-03](evidence.json#trace-checkout-03) [trace-recommendations-01](evidence.json#trace-recommendations-01)

## Recommended next steps

- Inspect connection hold times and transaction lifetimes before changing pool capacity. [metric-checkout-03](evidence.json#metric-checkout-03) [trace-checkout-03](evidence.json#trace-checkout-03)
- Compare per-replica concurrency and request volume; test capacity changes against database headroom in a controlled environment. [metric-checkout-00](evidence.json#metric-checkout-00) [metric-checkout-03](evidence.json#metric-checkout-03) [log-pool-config](evidence.json#log-pool-config)
- Triage the asynchronous recommendation-refresh failures separately. [log-recommendations-error](evidence.json#log-recommendations-error) [trace-recommendations-01](evidence.json#trace-recommendations-01)

## Exact evidence values

```json
[
  {
    "record_id": "metric-checkout-00",
    "field": "latency_p95_ms",
    "value": 180
  },
  {
    "record_id": "metric-checkout-03",
    "field": "latency_p95_ms",
    "value": 1840
  },
  {
    "record_id": "metric-checkout-03",
    "field": "pool_wait_p95_ms",
    "value": 1620
  },
  {
    "record_id": "trace-checkout-03",
    "field": "spans.1.duration_ms",
    "value": 1590
  }
]
```

References are record IDs in evidence.json. Citation presence and exact fact values are checked in code; narrative entailment is not guaranteed.
