"""Crash-consistent M11 action ledger.

SQLite can make the *intent boundary* durable; it cannot make an external mouse
operation transactional. SEND_STARTED is therefore deliberately ambiguous after a
crash and is recovered as UNCERTAIN, never as NOT_SENT.
"""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
from hashlib import sha256
import json,sqlite3
from anka_contracts.action import ActionCommand
from anka_contracts.execution import ExecutionLedgerAction,ExecutionOutcomeEvidence

class DefinitiveExecutionLedgerError(RuntimeError):pass
class DefinitiveExecutionLedgerRejected(ValueError):pass

def _json(obj):return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)
def _hash(seq,action,event,payload,prev):return sha256(_json({'seq':seq,'action':action,'event':event,'payload':payload,'prev':prev}).encode()).hexdigest()

def command_from_dict(d:dict)->ActionCommand:
    x=dict(d);x['semantic_target']=tuple(tuple(v) for v in x.get('semantic_target',()));x['expected_outcome_proofs']=tuple(x.get('expected_outcome_proofs',()));x['validity_constraints']=tuple(x.get('validity_constraints',()))
    return ActionCommand(**x)

class DefinitiveExecutionLedger:
    UNRESOLVED=frozenset({'PREPARED','SEND_STARTED','PENDING','CONFIRMED_UNSETTLED','UNCERTAIN'})
    TERMINAL=frozenset({'REJECTED_NOT_SENT','SETTLED_SUCCESS','PROVEN_FAILURE','TERMINAL_UNRESOLVED'})
    def __init__(self,path:Path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self._db() as con:
            con.executescript('''
            CREATE TABLE IF NOT EXISTS actions(
              action_id TEXT PRIMARY KEY, action_key TEXT NOT NULL, run_id TEXT NOT NULL, account_id TEXT NOT NULL,
              client_instance_id TEXT NOT NULL, fight_epoch INTEGER NOT NULL, turn_epoch INTEGER NOT NULL,
              command_json TEXT NOT NULL, run_generation INTEGER NOT NULL, authority_generation INTEGER NOT NULL,
              status TEXT NOT NULL, attempt_id TEXT, send_state TEXT NOT NULL, prepared_ref TEXT NOT NULL,
              evidence_json TEXT NOT NULL, obligations_json TEXT NOT NULL, reason TEXT NOT NULL,
              UNIQUE(run_id,account_id,fight_epoch,turn_epoch,action_key));
            CREATE TABLE IF NOT EXISTS events(
              seq INTEGER PRIMARY KEY, action_id TEXT NOT NULL, event_type TEXT NOT NULL, payload TEXT NOT NULL,
              previous_hash TEXT NOT NULL, record_hash TEXT NOT NULL,
              FOREIGN KEY(action_id) REFERENCES actions(action_id));
            CREATE TRIGGER IF NOT EXISTS execution_events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'APPEND_ONLY_EXECUTION_EVENTS'); END;
            CREATE TRIGGER IF NOT EXISTS execution_events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'APPEND_ONLY_EXECUTION_EVENTS'); END;
            ''')
    @contextmanager
    def _db(self):
        con=sqlite3.connect(str(self.path),timeout=3,isolation_level=None,check_same_thread=False)
        try:
            con.execute('PRAGMA foreign_keys=ON');con.execute('PRAGMA busy_timeout=3000');con.execute('PRAGMA journal_mode=WAL');con.execute('PRAGMA synchronous=FULL');yield con
        finally:con.close()
    @staticmethod
    def _append(con,action_id,event,payload):
        tail=con.execute('SELECT seq,record_hash FROM events ORDER BY seq DESC LIMIT 1').fetchone();seq=1 if tail is None else tail[0]+1;prev='GENESIS' if tail is None else tail[1];enc=_json(payload)
        con.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',(seq,action_id,event,enc,prev,_hash(seq,action_id,event,enc,prev)))
        return f'exec-event-{seq}'
    def _insert(self,command,run_generation,authority_generation,status,reason,*,require_no_unresolved=False):
        command_json=_json(command.to_dict());command_sha256=sha256(command_json.encode()).hexdigest()
        pref='prepared-'+sha256((command.action_id+command.action_key+command_sha256).encode()).hexdigest()[:32]
        with self._db() as con:
            con.execute('BEGIN IMMEDIATE')
            try:
                if require_no_unresolved:
                    row=con.execute("SELECT action_id FROM actions WHERE status IN ('PREPARED','SEND_STARTED','PENDING','CONFIRMED_UNSETTLED','UNCERTAIN') LIMIT 1").fetchone()
                    if row is not None:raise DefinitiveExecutionLedgerRejected('UNRESOLVED_ACTION_FENCE')
                con.execute('INSERT INTO actions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(command.action_id,command.action_key,command.run_id,command.account_id,command.client_instance_id,command.fight_epoch,command.turn_epoch,command_json,run_generation,authority_generation,status,None,'NOT_SENT',pref,'[]',_json(list(command.expected_outcome_proofs)),reason))
                eid=self._append(con,command.action_id,status,{'status_after':status,'reason':reason,'command_sha256':command_sha256,'run_generation':run_generation,'authority_generation':authority_generation,'prepared_ref':pref});con.commit()
            except sqlite3.IntegrityError as exc:con.rollback();raise DefinitiveExecutionLedgerRejected('DUPLICATE_ACTION_ID_OR_SEMANTIC_KEY') from exc
            except Exception:con.rollback();raise
        return pref,eid
    def record_rejected(self,command,run_generation,authority_generation,reason):return self._insert(command,run_generation,authority_generation,'REJECTED_NOT_SENT',reason)
    def prepare(self,command,run_generation,authority_generation):
        return self._insert(command,run_generation,authority_generation,'PREPARED','PREPARED_DURABLE',require_no_unresolved=True)
    def _transition(self,action_id,allowed,new_status,event,reason,*,attempt_id=None,send_state=None,evidence_add=(),obligations=None):
        with self._db() as con:
            con.execute('BEGIN IMMEDIATE')
            try:
                row=con.execute('SELECT status,attempt_id,send_state,evidence_json,obligations_json FROM actions WHERE action_id=?',(action_id,)).fetchone()
                if row is None:raise DefinitiveExecutionLedgerRejected('UNKNOWN_ACTION')
                if row[0] not in allowed:raise DefinitiveExecutionLedgerRejected(f'ILLEGAL_EXECUTION_TRANSITION:{row[0]}:{event}')
                ev=list(json.loads(row[3]));ev.extend(x for x in evidence_add if x not in ev);obs=list(json.loads(row[4])) if obligations is None else list(obligations)
                aid=row[1] if attempt_id is None else attempt_id;ss=row[2] if send_state is None else send_state
                event_id=self._append(con,action_id,event,{'status_before':row[0],'status_after':new_status,'reason':reason,'attempt_id':aid,'send_state':ss,'evidence_ids':ev,'obligations':obs})
                if event_id not in ev:ev.append(event_id)
                con.execute('UPDATE actions SET status=?,attempt_id=?,send_state=?,evidence_json=?,obligations_json=?,reason=? WHERE action_id=?',(new_status,aid,ss,_json(ev),_json(obs),reason,action_id));con.commit()
            except Exception:con.rollback();raise
        return self.get(action_id)
    def cancel_pre_send(self,action_id,reason):return self._transition(action_id,{'PREPARED'},'REJECTED_NOT_SENT','CANCELLED_BEFORE_SEND',reason,send_state='NOT_SENT',obligations=())
    def mark_send_started(self,action_id,attempt_id):return self._transition(action_id,{'PREPARED'},'SEND_STARTED','SEND_STARTED','EXTERNAL_BOUNDARY_ENTERED',attempt_id=attempt_id,send_state='SEND_STARTED')
    def _transition_with_resolved_passthrough(self,action_id,allowed,new_status,event,reason,*,resolved=frozenset(),resolved_event=None,attempt_id=None,send_state=None,evidence_add=(),obligations=None):
        """Atomically decide whether to transition or preserve a raced-ahead outcome.

        Driver return and Canonical outcome reconciliation run on different call
        paths.  Reading with ``get()`` and then opening a second transaction leaves
        a TOCTOU window where an authoritative outcome can settle the action between
        those operations.  The status decision and any mutation therefore share one
        ``BEGIN IMMEDIATE`` transaction.
        """
        with self._db() as con:
            con.execute('BEGIN IMMEDIATE')
            try:
                row=con.execute('SELECT status,attempt_id,send_state,evidence_json,obligations_json FROM actions WHERE action_id=?',(action_id,)).fetchone()
                if row is None:raise DefinitiveExecutionLedgerRejected('UNKNOWN_ACTION')
                if row[0] in resolved:
                    if resolved_event is not None:
                        self._append(con,action_id,resolved_event,{'status_before':row[0],'status_after':row[0],'reason':reason,'attempt_id':row[1],'send_state':row[2]})
                    con.commit()
                    return self.get(action_id)
                if row[0] not in allowed:raise DefinitiveExecutionLedgerRejected(f'ILLEGAL_EXECUTION_TRANSITION:{row[0]}:{event}')
                ev=list(json.loads(row[3]));ev.extend(x for x in evidence_add if x not in ev);obs=list(json.loads(row[4])) if obligations is None else list(obligations)
                aid=row[1] if attempt_id is None else attempt_id;ss=row[2] if send_state is None else send_state
                event_id=self._append(con,action_id,event,{'status_before':row[0],'status_after':new_status,'reason':reason,'attempt_id':aid,'send_state':ss,'evidence_ids':ev,'obligations':obs})
                if event_id not in ev:ev.append(event_id)
                con.execute('UPDATE actions SET status=?,attempt_id=?,send_state=?,evidence_json=?,obligations_json=?,reason=? WHERE action_id=?',(new_status,aid,ss,_json(ev),_json(obs),reason,action_id));con.commit()
            except Exception:con.rollback();raise
        return self.get(action_id)
    def mark_not_sent(self,action_id,reason):
        # An outcome may have raced ahead of a synchronous driver return.  Never
        # erase stronger authoritative evidence; preserve it and journal the
        # contradictory/late driver observation for diagnosis.
        return self._transition_with_resolved_passthrough(action_id,{'SEND_STARTED'},'REJECTED_NOT_SENT','DRIVER_PROVED_NOT_SENT',reason,
            resolved=self.TERMINAL|{'CONFIRMED_UNSETTLED'},resolved_event='DRIVER_NOT_SENT_RETURNED_AFTER_OUTCOME',send_state='NOT_SENT',obligations=())
    def mark_sent(self,action_id,reason='DRIVER_ACCEPTED_SEND'):
        # Outcome can race ahead of the synchronous driver return; decide and
        # mutate atomically so the durable result and submit() result cannot split.
        return self._transition_with_resolved_passthrough(action_id,{'SEND_STARTED'},'PENDING','DRIVER_ACCEPTED_SEND',reason,
            resolved=self.TERMINAL|{'CONFIRMED_UNSETTLED'},resolved_event='DRIVER_RETURNED_AFTER_OUTCOME',send_state='SENT')
    def mark_uncertain(self,action_id,reason):
        return self._transition_with_resolved_passthrough(action_id,{'SEND_STARTED','PENDING','CONFIRMED_UNSETTLED','UNCERTAIN'},'UNCERTAIN','SEND_UNCERTAIN',reason,
            resolved=self.TERMINAL,send_state='MAY_HAVE_SENT')
    def apply_outcome(self,action_id,status,evidence:ExecutionOutcomeEvidence,reason,obligations):
        if status not in ('PENDING','CONFIRMED_UNSETTLED','SETTLED_SUCCESS','PROVEN_FAILURE','UNCERTAIN'):raise DefinitiveExecutionLedgerRejected('INVALID_OUTCOME_STATUS')
        return self._transition_with_resolved_passthrough(action_id,{'SEND_STARTED','PENDING','UNCERTAIN','CONFIRMED_UNSETTLED'},status,'AUTHORITATIVE_OUTCOME',reason,
            resolved=self.TERMINAL,evidence_add=(evidence.evidence_id,),obligations=obligations)
    def mark_terminal_unresolved(self,action_id,reason):
        return self._transition_with_resolved_passthrough(action_id,{'SEND_STARTED','PENDING','UNCERTAIN','CONFIRMED_UNSETTLED'},'TERMINAL_UNRESOLVED','TERMINAL_UNRESOLVED',reason,
            resolved=self.TERMINAL,send_state='MAY_HAVE_SENT')
    def get_command(self,action_id):
        with self._db() as con:
            row=con.execute('SELECT command_json FROM actions WHERE action_id=?',(action_id,)).fetchone()
        if row is None:raise DefinitiveExecutionLedgerRejected('UNKNOWN_ACTION')
        return command_from_dict(json.loads(row[0]))
    def get(self,action_id):
        with self._db() as con:
            row=con.execute('SELECT action_id,action_key,status,attempt_id,send_state,run_generation,authority_generation,evidence_json,obligations_json,reason FROM actions WHERE action_id=?',(action_id,)).fetchone()
        if row is None:raise DefinitiveExecutionLedgerRejected('UNKNOWN_ACTION')
        return ExecutionLedgerAction(row[0],row[1],row[2],row[3],row[4],row[5],row[6],tuple(json.loads(row[7])),tuple(json.loads(row[8])),row[9])
    def unresolved(self):
        with self._db() as con:ids=[r[0] for r in con.execute("SELECT action_id FROM actions WHERE status IN ('PREPARED','SEND_STARTED','PENDING','CONFIRMED_UNSETTLED','UNCERTAIN') ORDER BY rowid")]
        return tuple(self.get(x) for x in ids)
    def recover_after_restart(self):
        changed=[]
        for a in self.unresolved():
            if a.status=='PREPARED':changed.append(self.cancel_pre_send(a.action_id,'RESTART_BEFORE_SEND_PROVEN_NOT_SENT'))
            elif a.status=='SEND_STARTED':changed.append(self.mark_uncertain(a.action_id,'RESTART_AFTER_SEND_STARTED_MAY_HAVE_SENT'))
        return tuple(changed)
    def audit(self):
        """Verify the hash chain and every safety-relevant actions projection field."""
        with self._db() as con:
            rows=con.execute(
                'SELECT seq,action_id,event_type,payload,previous_hash,record_hash FROM events ORDER BY seq'
            ).fetchall()
            actions=con.execute(
                'SELECT action_id,action_key,run_id,account_id,client_instance_id,fight_epoch,turn_epoch,'
                'status,command_json,run_generation,authority_generation,attempt_id,send_state,prepared_ref,'
                'evidence_json,obligations_json,reason FROM actions'
            ).fetchall()

        prev='GENESIS';expected_seq=1;per_action={};first={}
        for seq,aid,event,payload,previous_hash,record_hash in rows:
            if (seq!=expected_seq or previous_hash!=prev or
                    record_hash!=_hash(seq,aid,event,payload,prev)):
                raise DefinitiveExecutionLedgerError('EXECUTION_EVENT_CHAIN_CORRUPTED')
            try:obj=json.loads(payload)
            except Exception as exc:
                raise DefinitiveExecutionLedgerError('EXECUTION_EVENT_PAYLOAD_CORRUPTED') from exc
            if not isinstance(obj,dict):
                raise DefinitiveExecutionLedgerError('EXECUTION_EVENT_PAYLOAD_CORRUPTED')
            first.setdefault(aid,obj)
            per_action.setdefault(aid,[]).append((seq,event,obj))
            prev=record_hash;expected_seq+=1

        action_ids={row[0] for row in actions}
        if action_ids!=set(per_action):
            raise DefinitiveExecutionLedgerError('EXECUTION_ACTION_EVENT_SET_MISMATCH')

        for row in actions:
            (aid,action_key,run_id,account_id,client_instance_id,fight_epoch,turn_epoch,
             status,command_json,run_generation,authority_generation,attempt_id,send_state,
             prepared_ref,evidence_json,obligations_json,reason)=row
            try:
                command=command_from_dict(json.loads(command_json))
                stored_evidence=list(json.loads(evidence_json))
                stored_obligations=list(json.loads(obligations_json))
            except Exception as exc:
                raise DefinitiveExecutionLedgerError('EXECUTION_ACTION_PROJECTION_CORRUPTED') from exc

            immutable=(aid,action_key,run_id,account_id,client_instance_id,fight_epoch,turn_epoch)
            expected_immutable=(command.action_id,command.action_key,command.run_id,command.account_id,
                                command.client_instance_id,command.fight_epoch,command.turn_epoch)
            if immutable!=expected_immutable:
                raise DefinitiveExecutionLedgerError('EXECUTION_IMMUTABLE_SCOPE_PROJECTION_CORRUPTED')

            meta=first.get(aid,{})
            cmd_hash=sha256(command_json.encode()).hexdigest()
            if (meta.get('command_sha256')!=cmd_hash or
                    meta.get('run_generation')!=run_generation or
                    meta.get('authority_generation')!=authority_generation or
                    meta.get('prepared_ref')!=prepared_ref):
                raise DefinitiveExecutionLedgerError('EXECUTION_IMMUTABLE_PROJECTION_CORRUPTED')

            events=per_action[aid]
            first_seq,first_event,first_payload=events[0]
            if (first_event not in ('PREPARED','REJECTED_NOT_SENT') or
                    first_payload.get('status_after')!=first_event):
                raise DefinitiveExecutionLedgerError('EXECUTION_INITIAL_EVENT_INVALID')
            projected_status=first_payload['status_after']
            projected_attempt=None
            projected_send_state='NOT_SENT'
            projected_evidence=[]
            projected_obligations=list(command.expected_outcome_proofs)
            projected_reason=first_payload.get('reason')

            for seq,event,obj in events[1:]:
                if obj.get('status_before')!=projected_status:
                    raise DefinitiveExecutionLedgerError('EXECUTION_EVENT_STATUS_CAUSALITY_INVALID')
                mutating=('evidence_ids' in obj or 'obligations' in obj)
                if mutating:
                    if not ('evidence_ids' in obj and 'obligations' in obj and
                            'status_after' in obj and 'send_state' in obj and
                            'attempt_id' in obj and 'reason' in obj):
                        raise DefinitiveExecutionLedgerError('EXECUTION_EVENT_PROJECTION_INCOMPLETE')
                    projected_status=obj['status_after']
                    projected_attempt=obj['attempt_id']
                    projected_send_state=obj['send_state']
                    projected_evidence=list(obj['evidence_ids'])
                    event_id=f'exec-event-{seq}'
                    if event_id not in projected_evidence:
                        projected_evidence.append(event_id)
                    projected_obligations=list(obj['obligations'])
                    projected_reason=obj['reason']
                else:
                    # Resolved driver-return journal events are append-only evidence,
                    # not projection mutations.  They must agree with current truth.
                    if (obj.get('status_after')!=projected_status or
                            obj.get('attempt_id')!=projected_attempt or
                            obj.get('send_state')!=projected_send_state):
                        raise DefinitiveExecutionLedgerError('EXECUTION_PASSTHROUGH_EVENT_CONTRADICTS_PROJECTION')

            if status!=projected_status:
                raise DefinitiveExecutionLedgerError('EXECUTION_PROJECTION_MISMATCH')
            if (attempt_id!=projected_attempt or send_state!=projected_send_state or
                    stored_evidence!=projected_evidence or
                    stored_obligations!=projected_obligations or reason!=projected_reason):
                raise DefinitiveExecutionLedgerError('EXECUTION_MUTABLE_PROJECTION_CORRUPTED')

        return tuple(self.get(aid) for aid in sorted(action_ids))
