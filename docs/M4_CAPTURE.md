# M4 — Capture: Ordered Transport Evidence

## Status

`FAULT_VERIFIED` offline. Current Windows capture acceptance remains a later Q10/Q11 concern.

## Definitive boundary

Capture owns packet acquisition, exact flow-to-client binding, connection generations, TCP byte ordering, retransmission/overlap handling, bounded buffering, explicit loss/gap fences, replay parity, and `WireEnvelope` production. Capture does **not** import Protocol or interpret Dofus semantics.

`TransportEnvelopeAssembler` emits stable envelopes with capture/client/connection identity, byte offsets, producer ordering, timestamps/provenance, connection generation, source packet number, and continuity (`COMPLETE`, `GAP_BEFORE`, `GAP_INSIDE`, `RECONNECTED`, etc.). Unknown/unbound flows and dropped/overflowed capture evidence make transport health uncertain rather than being guessed.

## Reused P61–P66 protections

The definitive boundary preserves IPv4/IPv6 fragmentation uncertainty, queue overflow/loss accounting, PCAPNG loss metadata, section integrity, opt-in raw evidence, interrupted-capture incomplete sealing, and P66 post-stop producer quiesce → queue drain → audit/consumer → final seal ordering.

## Acceptance

The Q4 joint Capture/Protocol gate includes the M4 transport suite. Current Windows/Npcap operation is explicitly not claimed by this offline milestone.
