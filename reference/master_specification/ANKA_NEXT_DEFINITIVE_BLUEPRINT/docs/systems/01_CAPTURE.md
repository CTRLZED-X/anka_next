# System 01 — Capture (`anka_capture`)

## Purpose

Capture converts OS/network observations into a trustworthy ordered transport stream for a particular client connection. It does not know Dofus semantic messages.

## Owned responsibilities

- select/initialize capture backend;
- bind packets to exact process/client/connection generation where evidence allows;
- filter configured server ports/flows;
- reconstruct TCP byte stream in direction order;
- identify duplicate, overlap, retransmission, reset and continuity gaps;
- timestamp and sequence transport evidence;
- optionally write bounded PCAPNG/raw evidence;
- publish capture health and loss/overflow diagnostics.

## Public inputs

- `CaptureScope`: target processes/ports/interfaces;
- process/socket binding hints from Client/App;
- backend selection/config;
- start/stop lifecycle.

## Public outputs

```text
WireEnvelope:
  capture_session_id
  client_instance_id
  connection_id / flow_id
  direction
  transport_start_offset / end_offset
  producer_sequence
  observed_wall_time
  monotonic_time
  payload bytes/reference
  continuity = COMPLETE | GAP_BEFORE | GAP_INSIDE | RECONNECTED
  source metadata
```

`CaptureHealth` includes backend readiness, queue depth, overflow/loss counts, ambiguous bindings, current flows and last good offset.

## Invariants

- Never silently discard selected gameplay bytes.
- A queue overflow becomes an explicit continuity failure.
- A packet/segment is never attributed to CRA/ENU from port alone when multiple candidate clients exist.
- Reconnect starts a new connection generation; previous decoder context cannot silently continue.
- PCAP evidence and reconstructed application stream are separate artifacts; PCAP is source bytes, not semantic truth.

## Dependencies

May import `anka_contracts` only among ANKA domain packages. Does not import Protocol.

## Diagnostics

Required events include backend start/stop, selected interface/filter, flow binding, first/last offset, retransmission/gap/overflow, reconnect/reset, and capture exception.

## Tests

- deterministic TCP reassembly fixtures;
- duplicate/retransmit/overlap/out-of-order segments;
- dropped segment and explicit gap;
- connection reset/reconnect;
- two account flows on same server port;
- queue overflow -> health fence, never silent success;
- replay backend parity with live-backend envelope schema;
- bounded memory/load tests for target account counts.

## Completion gate

Capture is complete when a fake Protocol consumer can receive exact ordered envelopes/gaps from known PCAP fixtures and all ambiguity/loss paths fail explicitly without importing protocol logic or emitting physical input.

