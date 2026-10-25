# Appendix F — Engineering References

These sources support general engineering choices. They do **not** prove ANKA behavior; source/runtime evidence does that.

- Martin Fowler — **Strangler Fig Application**  
  https://martinfowler.com/bliki/StranglerFigApplication.html  
  Incremental replacement is preferred over risky big-bang rewrites.

- SQLite — **Atomic Commit / Transactional behavior / WAL**  
  https://www.sqlite.org/atomiccommit.html  
  https://www.sqlite.org/transactional.html  
  https://www.sqlite.org/wal.html  
  Used to reason about durable journal/checkpoint crash boundaries.

- Python — **logging QueueHandler / QueueListener**  
  https://docs.python.org/3/library/logging.handlers.html  
  Useful for nonblocking local diagnostic paths; queue/failure behavior still needs explicit design.

- OpenTelemetry — **Logs / tracing concepts / semantic conventions**  
  https://opentelemetry.io/docs/specs/otel/logs/  
  https://opentelemetry.io/docs/specs/semconv/  
  Inspires correlation IDs/resource/event semantics without requiring a hosted collector.

- OWASP — **Logging Cheat Sheet**  
  https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html  
  Privacy, sanitization, log injection, failure/DoS considerations.

- Pact — **Consumer Driven Contracts**  
  https://docs.pact.io/  
  Supports verifying stable producer/consumer boundary semantics. ANKA need not adopt Pact itself.

- Hypothesis — **Stateful / rule-based testing**  
  https://hypothesis.readthedocs.io/en/latest/stateful.html  
  Useful for generated lifecycle/action transition sequences and invariant checking.

- Google SRE — **Monitoring Distributed Systems / Canarying Releases**  
  https://sre.google/sre-book/monitoring-distributed-systems/  
  https://sre.google/workbook/canarying-releases/  
  Supports actionable signals and staged qualification rather than noisy logging/big-bang rollout.

- Microsoft — **Windows Error Reporting: LocalDumps**  
  https://learn.microsoft.com/en-us/windows/win32/wer/collecting-user-mode-dumps  
  Optional advanced Windows crash evidence; not required/default.

