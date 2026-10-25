"""Q9 full CRA+ENU zero-OS-input systemic scenario.

This is a verification composition, not a live runtime.  It intentionally uses
synthetic protocol evidence and synthetic Client attestations while exercising the
real Canonical writer/State projector, Coordination, Decision, Workflow, Kernel
static readiness, Execution ledger/arbiter and fake input driver.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Iterable

from anka_app.adapters.kernel_queries import GameKernelQueriesAdapter
from anka_app.action_authority import CompositeActionAuthority
from anka_canonical.writer import CanonicalWriter, ExactReleaseAdmissionPolicy
from anka_contracts.canonical import CanonicalCandidate
from anka_contracts.coordination import MemberPartyObservation, PartyRosterMember
from anka_contracts.decision import DecisionFrame
from anka_contracts.evidence import EvidencePointer
from anka_contracts.execution import ExecutionClientAttestation, ExecutionCoordinationPermit, ExecutionOutcomeEvidence, ExecutionStateView
from anka_contracts.mechanics import MechanicsResult
from anka_contracts.protocol import CandidateCanonicalBatch, DecoderCheckpointRef, WireEnvelopeRef
from anka_contracts.workflow import MissionConfigSpec, WorkflowSignal
from anka_coordination.coordinator import PartyCoordinatorService
from anka_decision.planner import DeterministicPlanner
from anka_decision.policies import load_legacy_profiles
from anka_execution.arbiter import HostInputArbiter
from anka_execution.definitive_ledger import DefinitiveExecutionLedger
from anka_execution.drivers.fake_input import FakePhysicalInputDriver
from anka_execution.service import DefinitiveExecutionService, _target_fingerprint
from anka_game_kernel import GameKernel, ExternalGameDataConfig, load_bundled_spell_mechanics_pack
from anka_live_state.projector import StateProjector
from anka_observability.api import LocalDiagnostics
from anka_workflow.compiler import compile_mission
from anka_workflow.engine import MissionWorkflow
from anka_workflow.integration import WorkflowTurnController

Q9_ADAPTER='adapter-q9-synthetic-zero-input-r1'
Q9_BUILD='SYNTHETIC-Q9-NOT-A-LIVE-CLIENT'
FIGHT_ID='fight-q9-1'
FIGHT_MAP=200
WORLD_MAP=100
PARTY='party-q9'
RUN='run-q9'
CRA=('acct-cra','client-cra',41,9,'cra',32426,3)
ENU=('acct-enu','client-enu',42,3,'enu',13338,3)


def _h(text:str)->str:return sha256(text.encode()).hexdigest()

@dataclass(frozen=True, slots=True)
class Q9Result:
    status:str
    final_phase:str
    attempts:int
    wins:int
    driver_calls:int
    physical_input_count:int
    canonical_events:int
    execution_actions:int
    coordination_party_generation:int
    diagnostics_dropped:int

class SyntheticCanonicalFeed:
    def __init__(self,path:Path,observer=None):
        self.observer=observer
        self.writer=CanonicalWriter(path,projector=StateProjector(),admission_policy=ExactReleaseAdmissionPolicy(((Q9_ADAPTER,Q9_BUILD),)))
        self._seq={CRA[0]:0,ENU[0]:0}
        self._clients={CRA[0]:CRA[1],ENU[0]:ENU[1]}
        self._conn={CRA[0]:'conn-q9-cra',ENU[0]:'conn-q9-enu'}
    def close(self):self.writer.close()
    def snapshot(self,account):return self.writer.snapshot(account)
    def push(self,account:str,specs:Iterable[tuple[str,dict,int|None,int|None,int|None]]):
        self._seq[account]+=1;n=self._seq[account];client=self._clients[account];conn=self._conn[account]
        wire=WireEnvelopeRef('capture-q9-synthetic',conn,1,n,'server_to_client','COMPLETE',_h(f'{account}:wire:{n}'))
        cp=DecoderCheckpointRef(Q9_ADAPTER,Q9_BUILD,conn,1,n,_h(f'{account}:checkpoint:{n}'))
        candidates=[]
        for i,(kind,payload,world_epoch,fight_epoch,turn_epoch) in enumerate(specs):
            tag=f'{account}:{n}:{i}:{kind}';ev=EvidencePointer('evidence-'+_h(tag)[:32],'OBSERVED_EXTERNAL','anka_protocol','q9-synthetic:'+_h(tag),_h(tag),'Q9_SYNTHETIC_ZERO_INPUT')
            candidates.append(CanonicalCandidate('candidate-'+_h(tag)[:32],kind,account,client,(ev,),tuple((k,str(v).lower() if isinstance(v,bool) else str(v)) for k,v in payload.items()),world_epoch,fight_epoch,turn_epoch))
        batch=CandidateCanonicalBatch(f'batch-q9-{account[5:]}-{n}',Q9_ADAPTER,Q9_BUILD,conn,1,(wire,),tuple(candidates),'SEMANTIC_CANDIDATES',cp)
        span='span-'+_h(batch.batch_id)[:24]
        if self.observer is not None:
            self.observer.record('protocol.batch_decoded',owner_system='anka_protocol',boundary='protocol.decode',account_id=account,span_id=span,protocol_build=Q9_BUILD,evidence_class='OBSERVED_EXTERNAL',payload={'batch_span_id':batch.batch_id,'decode_health':batch.decode_health,'candidate_count':len(batch.candidates),'semantic_kinds':[x.semantic_kind for x in batch.candidates]})
            for c in batch.candidates:
                if c.semantic_kind=='READY_OBSERVED':
                    payload=dict(c.payload)
                    self.observer.record('protocol.ready_observed',owner_system='anka_protocol',boundary='protocol.ready_observation',account_id=account,span_id=span,fight_epoch=c.fight_epoch,turn_epoch=c.turn_epoch,protocol_build=Q9_BUILD,evidence_class='OBSERVED_EXTERNAL',payload={'batch_span_id':batch.batch_id,'candidate_id':c.candidate_id,'actor_id':payload.get('actor_id'),'ready':payload.get('ready')})
        receipt=self.writer.commit_candidate_batch(batch)
        if receipt.status not in ('COMMITTED','IDEMPOTENT_DUPLICATE'):raise RuntimeError('Q9_CANONICAL_COMMIT_FAILED')
        snap=self.writer.snapshot(account)
        if self.observer is not None:
            self.observer.record('canonical.batch_committed',owner_system='anka_canonical',boundary='canonical.commit',account_id=account,span_id=span,canonical_cursor=receipt.last_cursor,evidence_class='AUTHORITY_COMMITTED',payload={'batch_span_id':batch.batch_id,'status':receipt.status,'event_count':receipt.event_count,'first_cursor':receipt.first_cursor,'last_cursor':receipt.last_cursor})
            for c in batch.candidates:
                if c.semantic_kind=='READY_OBSERVED':
                    payload=dict(c.payload)
                    self.observer.record('canonical.ready_committed',owner_system='anka_canonical',boundary='canonical.ready_commit',account_id=account,span_id=span,fight_epoch=c.fight_epoch,turn_epoch=c.turn_epoch,canonical_cursor=receipt.last_cursor,evidence_class='AUTHORITY_COMMITTED',payload={'batch_span_id':batch.batch_id,'candidate_id':c.candidate_id,'actor_id':payload.get('actor_id'),'ready':payload.get('ready')})
            if snap is not None:
                actors=[]
                for actor in snap.actors:
                    actors.append({'actor_id':actor.actor_id,'cell':actor.cell.value if actor.cell.status=='KNOWN' else None,'cell_status':actor.cell.status,'hp':actor.hp.value if actor.hp.status=='KNOWN' else None,'hp_status':actor.hp.status,'ap':actor.ap.value if actor.ap.status=='KNOWN' else None,'ap_status':actor.ap.status,'mp':actor.mp.value if actor.mp.status=='KNOWN' else None,'mp_status':actor.mp.status,'ready':actor.ready.value if actor.ready.status=='KNOWN' else None,'ready_status':actor.ready.status})
                self.observer.record('live_state.snapshot_published',owner_system='anka_live_state',boundary='live_state.post_commit_projection',account_id=account,span_id=span,fight_epoch=snap.fight_epoch if snap.fight_epoch>0 else None,turn_epoch=snap.turn_epoch,canonical_cursor=snap.canonical_cursor,canonical_revision=snap.snapshot_revision,evidence_class='AUTHORITY_COMMITTED',payload={'batch_span_id':batch.batch_id,'snapshot_id':snap.snapshot_id,'semantic_sha256':snap.semantic_sha256,'fight_phase':snap.fight_phase.value if snap.fight_phase.status=='KNOWN' else None,'turn_owner':snap.turn_owner.value if snap.turn_owner.status=='KNOWN' else None,'actors':actors})
        return snap

class ScenarioMechanics:
    """Q9 synthetic live-context oracle with real Kernel static-data check."""
    def __init__(self,static:GameKernelQueriesAdapter):self.static=static
    def validate_plan(self,frame,plan):
        if plan.kind=='CAST':
            target=dict(plan.semantic_target)
            ready=self.static.spell_grade_readiness(int(target['spell_id']),int(target['grade']))
            if ready.status!='LEGAL':return ready
        return MechanicsResult('LEGAL','',{'scope':'Q9_SYNTHETIC_LIVE_CONTEXT_ONLY'})
    def validate_action(self,command,state):
        if command.kind=='CAST':
            target=dict(command.semantic_target)
            ready=self.static.spell_grade_readiness(int(target['spell_id']),int(target['grade']))
            if ready.status!='LEGAL':return ready
        return MechanicsResult('LEGAL','',{'scope':'Q9_SYNTHETIC_LIVE_CONTEXT_ONLY'})

class ScenarioStatePort:
    def __init__(self,feed:SyntheticCanonicalFeed):self.feed=feed
    def current_for_action(self,command):
        snap=self.feed.snapshot(command.account_id)
        actor=next((a for a in snap.actors if a.actor_id==command.actor_id),None)
        proofs=[]
        if actor is not None:
            if command.authority_scope=='TURN':
                proofs=[('ap',actor.ap.status),('actor_cell',actor.cell.status),('loadout','KNOWN')]
            else:
                proofs=[('actor_cell',actor.cell.status)]
        owner=snap.turn_owner.value if snap.turn_owner.status=='KNOWN' else None
        return ExecutionStateView(snap.snapshot_id,snap.semantic_sha256,snap.account_id,snap.client_instance_id,snap.fight_epoch,snap.turn_epoch,snap.canonical_cursor,command.actor_id,owner,'HEALTHY',tuple(proofs),False)

class ScenarioClientPort:
    def __init__(self):self.generation={CRA[0]:1,ENU[0]:1}
    def attest_for_action(self,command):
        idx=1 if command.account_id==CRA[0] else 2
        gen=self.generation[command.account_id]
        return ExecutionClientAttestation(
            'clientatt-q9-'+command.account_id[5:],command.account_id,command.client_instance_id,Q9_BUILD,
            100+idx,1000+idx,200+idx,gen,1,1,1,300+idx,400+idx,
            True,True,True,True,True,True,True,_target_fingerprint(command),('q9-client-proof-'+command.account_id,))

class ScenarioExecutionCoordinationPort:
    def __init__(self,coord:PartyCoordinatorService):self.coord=coord
    def permit_for_action(self,command):
        p=self.coord.action_permit(command.party_id,command.account_id,command.authority_scope)
        evidence=p.evidence_ids or ((f'q9-permit-{p.scope.lower()}-{p.party_generation}-{p.permit_generation}',) if p.allowed else ())
        return ExecutionCoordinationPermit(p.party_id,p.account_id,p.fight_epoch,p.turn_epoch,p.party_generation,p.permit_generation,p.allowed,p.reason,evidence,p.scope)

class ZeroInputQ9Scenario:
    def __init__(self,root:Path,*,driver_scenario:str='sent'):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.observer=LocalDiagnostics(self.root/'diagnostics',run_id=RUN,invocation_id='inv-q9')
        self.feed=SyntheticCanonicalFeed(self.root/'canonical.sqlite3',observer=self.observer)
        roster=(PartyRosterMember(CRA[0],CRA[1],CRA[2],'leader'),PartyRosterMember(ENU[0],ENU[1],ENU[2],'follower'))
        self.coord=PartyCoordinatorService(PARTY,roster,party_generation=1,observer=self.observer)
        cfg_hash=_h('q9-mission-config')
        cfg=MissionConfigSpec('sufokia_direction_cycle',1,8,1,2,False,True,cfg_hash)
        plan=compile_mission(cfg,self.root.parents[0]/'assets/workflow/routes.json' if (self.root.parents[0]/'assets/workflow/routes.json').exists() else Path(__file__).resolve().parents[2]/'assets/workflow/routes.json',watchdog_budget_ticks=5,recovery_budget=2)
        self.workflow=MissionWorkflow(RUN,plan,observer=self.observer)
        base=Path(__file__).resolve().parents[2]/'assets/game_data'
        kernel=GameKernel.start(ExternalGameDataConfig(base/'Static',base/'Mapuse','3.6.10.10','3.6.10.10','q9-zero-input','3.6.10.10'),spell_mechanics=load_bundled_spell_mechanics_pack())
        self.mechanics=ScenarioMechanics(GameKernelQueriesAdapter(kernel))
        policies=load_legacy_profiles(Path(__file__).resolve().parents[2]/'assets/decision/legacy_r5198_spell_priorities.json')
        self.planner=DeterministicPlanner(self.mechanics,policies,observer=self.observer)
        self.authority=CompositeActionAuthority(self.coord,self.workflow,observer=self.observer)
        self.driver=FakePhysicalInputDriver(driver_scenario)
        self.ledger=DefinitiveExecutionLedger(self.root/'execution.sqlite3')
        self.execution=DefinitiveExecutionService(run_id=RUN,run_generation=1,ledger=self.ledger,arbiter=HostInputArbiter(),state_reader=ScenarioStatePort(self.feed),client=ScenarioClientPort(),mechanics=self.mechanics,coordination=self.authority,driver=self.driver,clock_ns=lambda:100,observer=self.observer)
        self.execution.arm(authority_generation=1)
        self.controller=WorkflowTurnController(self.planner,self.execution,self.coord,observer=self.observer,authority=self.authority)
        self.tick=0
    def close(self):
        self.feed.close();self.observer.finish('CLOSED')
    def _signal(self,kind,*,fight_epoch=None,result=None,action_id=None,action_status=None,encounter_id=None,encounter_map_id=None):
        self.tick+=1
        s=WorkflowSignal(f'wfsig-q9-{self.tick}-{kind.lower()}',kind,self.tick,(f'q9-evidence-{self.tick}',),fight_epoch,result,action_id,action_status,encounter_id,encounter_map_id)
        out=self.workflow.apply(s)
        if out.status=='REJECTED':raise RuntimeError('Q9_WORKFLOW_REJECTED:'+out.reason)
        return out
    def _bootstrap_world_account(self,acct):
        account,_,actor,*_=acct
        return self.feed.push(account,(
            ('WORLD_MAP_OBSERVED',{'map_id':WORLD_MAP},1,None,None),
            ('ACTOR_SEEN',{'actor_id':actor},None,None,None),
            ('ACTOR_CELL_OBSERVED',{'actor_id':actor,'cell_id':10 if actor==CRA[2] else 11},None,None,None),
        ))

    def _fight_start_specs(self,acct):
        account,_,actor,*_=acct;other=ENU[2] if actor==CRA[2] else CRA[2]
        return (
            ('FIGHT_STARTED',{'fight_id':FIGHT_ID,'map_id':FIGHT_MAP},None,1,None),
            ('ACTOR_SEEN',{'actor_id':actor},None,1,None),('ACTOR_SEEN',{'actor_id':other},None,1,None),
            ('ACTOR_RESOURCE_ABSOLUTE',{'actor_id':actor,'resource':'AP','value':11},None,1,None),
            ('ACTOR_RESOURCE_ABSOLUTE',{'actor_id':actor,'resource':'MP','value':6},None,1,None),
            ('ACTOR_CELL_OBSERVED',{'actor_id':actor,'cell_id':100 if actor==CRA[2] else 101},None,1,None),
            ('ACTOR_RESOURCE_ABSOLUTE',{'actor_id':other,'resource':'AP','value':11},None,1,None),
            ('ACTOR_RESOURCE_ABSOLUTE',{'actor_id':other,'resource':'MP','value':6},None,1,None),
            ('ACTOR_CELL_OBSERVED',{'actor_id':other,'cell_id':101 if actor==CRA[2] else 100},None,1,None),
        )

    def _world_frame(self,acct):
        account,client,actor,class_id,profile,spell,grade=acct;snap=self.feed.snapshot(account);a=next(x for x in snap.actors if x.actor_id==actor)
        proofs=(('world_map',snap.world_map.status),('actor_cell',a.cell.status))
        return DecisionFrame('frame-q9-'+account[5:]+'-world-'+str(snap.canonical_cursor),RUN,account,snap.fight_epoch,snap.turn_epoch,snap.snapshot_id,snap.canonical_cursor,
            'WORLD_MOVE',client,snap.semantic_sha256,'m7-r1','kernel-r5','legacy-r5198',profile,class_id,actor,None,a.cell.value,snap.world_map.value if snap.world_map.status=='KNOWN' else None,
            None,None,proofs,(),(),(20 if actor==CRA[2] else 21,),(),0,128,route_step=self.workflow.next_route_step())

    def _run_world_move(self,acct,destination_map:int):
        frame=self._world_frame(acct);dispatch=self.controller.request(PARTY,frame)
        if dispatch.status!='SUBMITTED':raise RuntimeError('Q9_WORLD_MOVE_NOT_SUBMITTED:'+dispatch.reason)
        command=self.ledger.get_command(dispatch.action_id)
        if command.kind!='WORLD_MOVE' or command.authority_scope!='WORLD':raise RuntimeError('Q9_WORLD_SCOPE_WRONG')
        self._signal('ACTION_SUBMITTED',action_id=dispatch.action_id)
        target=int(dict(command.semantic_target)['target_cell'])
        snap=self.feed.push(acct[0],((
            'WORLD_MAP_OBSERVED',{'map_id':destination_map},2,None,None),(
            'ACTOR_CELL_OBSERVED',{'actor_id':acct[2],'cell_id':target},None,None,None)))
        outcome=ExecutionOutcomeEvidence('outcome-q9-world-'+dispatch.action_id[7:],acct[0],command.client_instance_id,0,snap.turn_epoch,snap.canonical_cursor,'CONFIRMATION',('WORLD_MAP_OR_CELL_CHANGED',),True,dispatch.action_id,acct[2])
        settled=self.execution.reconcile(dispatch.action_id,outcome)
        self._signal('ACTION_OUTCOME',action_id=dispatch.action_id,action_status=settled.status)
        if settled.status!='SETTLED_SUCCESS':raise RuntimeError('Q9_WORLD_MOVE_NOT_SETTLED')
        return dispatch,settled

    def _fight_entry_frame(self,acct,encounter_id:str,encounter_map_id:int):
        account,client,actor,class_id,profile,spell,grade=acct;snap=self.feed.snapshot(account);a=next(x for x in snap.actors if x.actor_id==actor)
        proofs=(('world_map',snap.world_map.status),('actor_cell',a.cell.status),('encounter_target','KNOWN'))
        return DecisionFrame('frame-q9-'+account[5:]+'-fight-entry-'+str(snap.canonical_cursor),RUN,account,snap.fight_epoch,snap.turn_epoch,snap.snapshot_id,snap.canonical_cursor,
            'FIGHT_ENTRY',client,snap.semantic_sha256,'m7-r1','kernel-r5','legacy-r5198',profile,class_id,actor,None,a.cell.value,encounter_map_id,None,None,proofs,(),(),(),(),0,128,encounter_id=encounter_id)

    def _run_fight_entry(self,acct,encounter_id:str,encounter_map_id:int):
        frame=self._fight_entry_frame(acct,encounter_id,encounter_map_id);dispatch=self.controller.request(PARTY,frame)
        if dispatch.status!='SUBMITTED':raise RuntimeError('Q9_FIGHT_ENTRY_NOT_SUBMITTED:'+dispatch.reason)
        command=self.ledger.get_command(dispatch.action_id)
        if command.kind!='START_FIGHT' or command.authority_scope!='FIGHT_ENTRY':raise RuntimeError('Q9_FIGHT_ENTRY_SCOPE_WRONG')
        self._signal('ACTION_SUBMITTED',action_id=dispatch.action_id)
        snap=self.feed.push(acct[0],self._fight_start_specs(acct))
        outcome=ExecutionOutcomeEvidence('outcome-q9-entry-'+dispatch.action_id[7:],acct[0],command.client_instance_id,1,snap.turn_epoch,snap.canonical_cursor,'CONFIRMATION',('FIGHT_ENTRY_CONFIRMED',),True,dispatch.action_id,acct[2])
        settled=self.execution.reconcile(dispatch.action_id,outcome)
        self._signal('ACTION_OUTCOME',action_id=dispatch.action_id,action_status=settled.status)
        if settled.status!='SETTLED_SUCCESS':raise RuntimeError('Q9_FIGHT_ENTRY_NOT_SETTLED')
        return dispatch,settled

    def _coord_join_target(self,acct):
        account,client,actor,*_=acct;snap=self.feed.snapshot(account)
        obs=MemberPartyObservation(f'coordobs-{account}-{snap.canonical_cursor}-join-target',account,client,actor,snap.canonical_cursor,snap.snapshot_revision,1,0,FIGHT_ID,FIGHT_MAP,'JOIN_TARGET',None,False,False,False,'HEALTHY',(f'q9-client-join-target-{account}',),False)
        out=self.coord.observe(obs)
        if out.status=='REJECTED':raise RuntimeError('Q9_COORD_JOIN_TARGET_REJECTED:'+out.reason)
        return out

    def _join_frame(self,acct):
        account,client,actor,class_id,profile,spell,grade=acct;snap=self.feed.snapshot(account);a=next(x for x in snap.actors if x.actor_id==actor)
        proofs=(('world_map',snap.world_map.status),('actor_cell',a.cell.status),('fight_identity','KNOWN'),('join_target','KNOWN'))
        return DecisionFrame('frame-q9-'+account[5:]+'-join-'+str(snap.canonical_cursor),RUN,account,snap.fight_epoch,snap.turn_epoch,snap.snapshot_id,snap.canonical_cursor,
            'JOIN_FIGHT',client,snap.semantic_sha256,'m7-r1','kernel-r5','legacy-r5198',profile,class_id,actor,None,a.cell.value,FIGHT_MAP,None,None,proofs,(),(),(),(),0,128,
            target_fight_id=FIGHT_ID,target_fight_epoch=1)

    def _run_join(self,acct):
        frame=self._join_frame(acct);dispatch=self.controller.request(PARTY,frame)
        if dispatch.status!='SUBMITTED':raise RuntimeError('Q9_JOIN_NOT_SUBMITTED:'+dispatch.reason)
        command=self.ledger.get_command(dispatch.action_id)
        if command.kind!='JOIN_FIGHT' or command.authority_scope!='JOIN':raise RuntimeError('Q9_JOIN_SCOPE_WRONG')
        self._signal('ACTION_SUBMITTED',fight_epoch=1,action_id=dispatch.action_id)
        snap=self.feed.push(acct[0],self._fight_start_specs(acct))
        outcome=ExecutionOutcomeEvidence('outcome-q9-join-'+dispatch.action_id[7:],acct[0],command.client_instance_id,1,snap.turn_epoch,snap.canonical_cursor,'CONFIRMATION',('FIGHT_JOIN_CONFIRMED',),True,dispatch.action_id,acct[2])
        settled=self.execution.reconcile(dispatch.action_id,outcome)
        self._signal('ACTION_OUTCOME',fight_epoch=1,action_id=dispatch.action_id,action_status=settled.status)
        if settled.status!='SETTLED_SUCCESS':raise RuntimeError('Q9_JOIN_NOT_SETTLED')
        self._coord_obs(acct,'JOIN')
        return dispatch,settled

    def _bootstrap_account(self,acct):
        account,client,actor,*_=acct
        other=ENU[2] if actor==CRA[2] else CRA[2]
        specs=[
            ('WORLD_MAP_OBSERVED',{'map_id':WORLD_MAP},1,None,None),
            ('FIGHT_STARTED',{'fight_id':FIGHT_ID,'map_id':FIGHT_MAP},None,1,None),
            ('ACTOR_SEEN',{'actor_id':actor},None,1,None),('ACTOR_SEEN',{'actor_id':other},None,1,None),
            ('ACTOR_RESOURCE_ABSOLUTE',{'actor_id':actor,'resource':'AP','value':11},None,1,None),
            ('ACTOR_RESOURCE_ABSOLUTE',{'actor_id':actor,'resource':'MP','value':6},None,1,None),
            ('ACTOR_CELL_OBSERVED',{'actor_id':actor,'cell_id':100 if actor==CRA[2] else 101},None,1,None),
            ('ACTOR_RESOURCE_ABSOLUTE',{'actor_id':other,'resource':'AP','value':11},None,1,None),
            ('ACTOR_RESOURCE_ABSOLUTE',{'actor_id':other,'resource':'MP','value':6},None,1,None),
            ('ACTOR_CELL_OBSERVED',{'actor_id':other,'cell_id':101 if actor==CRA[2] else 100},None,1,None),
        ]
        return self.feed.push(account,specs)
    def _coord_obs(self,acct,stage):
        account,client,actor,*_=acct;s=self.feed.snapshot(account)
        owner=s.turn_owner.value if s.turn_owner.status=='KNOWN' else None
        joined=stage in ('JOIN','PLACEMENT','READY','TURN')
        placed=stage in ('PLACEMENT','READY','TURN')
        ready=stage in ('READY','TURN')
        ev=tuple(dict.fromkeys(s.fight_id.source_event_ids+s.fight_map.source_event_ids+s.turn_owner.source_event_ids)) or (f'q9-state-{account}-{s.canonical_cursor}',)
        obs=MemberPartyObservation(f'coordobs-{account}-{s.canonical_cursor}-{stage.lower()}',account,client,actor,s.canonical_cursor,s.snapshot_revision,s.fight_epoch,s.turn_epoch,s.fight_id.value if s.fight_id.status=='KNOWN' else None,s.fight_map.value if s.fight_map.status=='KNOWN' else None,s.fight_phase.value if s.fight_phase.status=='KNOWN' else 'UNKNOWN',owner,joined,placed,ready,'HEALTHY',ev,False)
        out=self.coord.observe(obs)
        self.observer.record('coordination.observation_applied',owner_system='anka_coordination',boundary='coordination.party',payload={'account':account,'phase':out.snapshot.phase,'reason':out.reason})
        if out.status=='REJECTED':raise RuntimeError('Q9_COORD_REJECTED:'+out.reason)
        return out
    def _refresh_cell(self,acct):
        account,_,actor,*_=acct;s=self.feed.snapshot(account);a=next(x for x in s.actors if x.actor_id==actor)
        return self.feed.push(account,(('ACTOR_CELL_OBSERVED',{'actor_id':actor,'cell_id':a.cell.value},None,1,s.turn_epoch or None),))
    def _ready(self,acct):
        account,_,actor,*_=acct
        return self.feed.push(account,(('READY_OBSERVED',{'actor_id':actor,'ready':True},None,1,None),))
    def _turn_start(self,owner:int,turn_epoch:int):
        for acct in (CRA,ENU):
            self.feed.push(acct[0],(('TURN_STARTED',{'actor_id':owner},None,1,turn_epoch),))
    def _turn_handoff(self,old:int,new:int,new_epoch:int):
        for acct in (CRA,ENU):
            self.feed.push(acct[0],(
                ('TURN_ENDED',{'actor_id':old},None,1,new_epoch-1),
                ('TURN_STARTED',{'actor_id':new},None,1,new_epoch),
            ))
            self._coord_obs(acct,'TURN')
    def _phase_frame(self,acct,goal:str):
        account,client,actor,class_id,profile,spell,grade=acct;s=self.feed.snapshot(account);a=next(x for x in s.actors if x.actor_id==actor)
        goal=goal.upper()
        if goal=='PLACEMENT':
            proofs=(('fight_phase',s.fight_phase.status),('actor_cell',a.cell.status))
            candidates=(120 if actor==CRA[2] else 121,)
        elif goal=='READY':
            proofs=(('fight_phase',s.fight_phase.status),('actor_cell',a.cell.status))
            candidates=()
        else:raise ValueError('Q9_UNSUPPORTED_PHASE_GOAL:'+goal)
        return DecisionFrame('frame-q9-'+account[5:]+'-'+goal.lower()+f'-{s.canonical_cursor}',RUN,account,s.fight_epoch,s.turn_epoch,s.snapshot_id,s.canonical_cursor,goal,client,s.semantic_sha256,'m7-r1','kernel-r5','legacy-r5198',profile,class_id,actor,s.turn_owner.value if s.turn_owner.status=='KNOWN' else None,a.cell.value,FIGHT_MAP,a.ap.value,a.mp.value,proofs,((spell,grade),),(),candidates,(),0,128)
    def _run_placement(self,acct):
        frame=self._phase_frame(acct,'PLACEMENT');dispatch=self.controller.request(PARTY,frame)
        if dispatch.status!='SUBMITTED':raise RuntimeError('Q9_PLACEMENT_NOT_SUBMITTED:'+dispatch.reason)
        command=self.ledger.get_command(dispatch.action_id)
        if command.kind!='MOVE' or command.authority_scope!='PLACEMENT':raise RuntimeError('Q9_PLACEMENT_SCOPE_WRONG')
        self._signal('ACTION_SUBMITTED',fight_epoch=1,action_id=dispatch.action_id)
        target=int(dict(command.semantic_target)['target_cell'])
        snap=self.feed.push(acct[0],(('ACTOR_CELL_OBSERVED',{'actor_id':acct[2],'cell_id':target},None,1,None),))
        outcome=ExecutionOutcomeEvidence('outcome-q9-place-'+dispatch.action_id[7:],acct[0],command.client_instance_id,1,snap.turn_epoch,snap.canonical_cursor,'CONFIRMATION',('ACTOR_CELL_CHANGED',),True,dispatch.action_id,acct[2])
        settled=self.execution.reconcile(dispatch.action_id,outcome)
        self._signal('ACTION_OUTCOME',fight_epoch=1,action_id=dispatch.action_id,action_status=settled.status)
        if settled.status!='SETTLED_SUCCESS':raise RuntimeError('Q9_PLACEMENT_NOT_SETTLED')
        self._coord_obs(acct,'PLACEMENT')
        return dispatch,settled
    def _run_ready(self,acct):
        frame=self._phase_frame(acct,'READY');dispatch=self.controller.request(PARTY,frame)
        if dispatch.status!='SUBMITTED':raise RuntimeError('Q9_READY_NOT_SUBMITTED:'+dispatch.reason)
        command=self.ledger.get_command(dispatch.action_id)
        if command.kind!='READY' or command.authority_scope!='READY':raise RuntimeError('Q9_READY_SCOPE_WRONG')
        self._signal('ACTION_SUBMITTED',fight_epoch=1,action_id=dispatch.action_id)
        snap=self.feed.push(acct[0],(('READY_OBSERVED',{'actor_id':acct[2],'ready':True},None,1,None),))
        outcome=ExecutionOutcomeEvidence('outcome-q9-ready-'+dispatch.action_id[7:],acct[0],command.client_instance_id,1,snap.turn_epoch,snap.canonical_cursor,'CONFIRMATION',('READY_OR_PHASE_CONFIRMED',),True,dispatch.action_id,acct[2])
        settled=self.execution.reconcile(dispatch.action_id,outcome)
        self._signal('ACTION_OUTCOME',fight_epoch=1,action_id=dispatch.action_id,action_status=settled.status)
        if settled.status!='SETTLED_SUCCESS':raise RuntimeError('Q9_READY_NOT_SETTLED')
        self._coord_obs(acct,'READY')
        return dispatch,settled
    def _frame(self,acct):
        account,client,actor,class_id,profile,spell,grade=acct;s=self.feed.snapshot(account);a=next(x for x in s.actors if x.actor_id==actor)
        proofs=(('fight_phase',s.fight_phase.status),('turn_owner',s.turn_owner.status),('actor_cell',a.cell.status),('ap',a.ap.status),('mp',a.mp.status),('loadout','KNOWN'),('targets','KNOWN'))
        return DecisionFrame('frame-q9-'+account[5:]+f'-{s.turn_epoch}',RUN,account,s.fight_epoch,s.turn_epoch,s.snapshot_id,s.canonical_cursor,'FIGHT_TURN',client,s.semantic_sha256,'m7-r1','kernel-r5','legacy-r5198',profile,class_id,actor,s.turn_owner.value if s.turn_owner.status=='KNOWN' else None,a.cell.value,FIGHT_MAP,a.ap.value,a.mp.value,proofs,((spell,grade),),(250 if actor==CRA[2] else 251,),(),(),0,128)
    def _run_action(self,acct):
        frame=self._frame(acct);dispatch=self.controller.request(PARTY,frame)
        if dispatch.status!='SUBMITTED':raise RuntimeError('Q9_ACTION_NOT_SUBMITTED:'+dispatch.reason)
        self._signal('ACTION_SUBMITTED',fight_epoch=1,action_id=dispatch.action_id)
        command=self.ledger.get_command(dispatch.action_id)
        # Authoritative synthetic server consequence arrives through Canonical before settlement.
        account,_,actor,*_=acct;s=self.feed.snapshot(account);a=next(x for x in s.actors if x.actor_id==actor)
        new_ap=max(0,int(a.ap.value)-1)
        snap=self.feed.push(account,(('ACTOR_RESOURCE_ABSOLUTE',{'actor_id':actor,'resource':'AP','value':new_ap},None,1,s.turn_epoch),))
        outcome=ExecutionOutcomeEvidence('outcome-q9-'+dispatch.action_id[7:],account,command.client_instance_id,1,snap.turn_epoch,snap.canonical_cursor,'CONFIRMATION',command.expected_outcome_proofs,True,dispatch.action_id,actor)
        settled=self.execution.reconcile(dispatch.action_id,outcome)
        self._signal('ACTION_OUTCOME',fight_epoch=1,action_id=dispatch.action_id,action_status=settled.status)
        return dispatch,settled
    def _run_end_turn_and_handoff(self,acct,next_acct,new_epoch:int):
        """Drive the real Decision→Execution END_TURN path, then settle only after
        both account views prove the authoritative owner transition.

        The CAST that the normal tactical policy would choose first is quarantined
        *for this frame only* so the deterministic planner reaches its semantic
        END_TURN fallback.  This is a verification fixture, not a gameplay policy.
        """
        base=self._frame(acct)
        first=self.planner.plan(base)
        if first.disposition!='PLAN' or first.plan is None or first.plan.kind!='CAST':
            raise RuntimeError('Q9_EXPECTED_CAST_BEFORE_END_TURN')
        frame=replace(base,frame_id=base.frame_id+'-end',quarantined_action_keys=(first.plan.action_key,))
        dispatch=self.controller.request(PARTY,frame)
        if dispatch.status!='SUBMITTED':raise RuntimeError('Q9_END_TURN_NOT_SUBMITTED:'+dispatch.reason)
        command=self.ledger.get_command(dispatch.action_id)
        if command.kind!='END_TURN':raise RuntimeError('Q9_PLANNER_DID_NOT_REACH_END_TURN')
        self._signal('ACTION_SUBMITTED',fight_epoch=1,action_id=dispatch.action_id)
        pending=self.ledger.get(dispatch.action_id)
        if pending.status!='PENDING':raise RuntimeError('Q9_END_TURN_NOT_PENDING_SERVER_PROOF')
        # No next-account permit exists merely because the fake driver accepted.
        if self.coord.turn_permit(PARTY,next_acct[0]).allowed:
            raise RuntimeError('Q9_NEXT_ACCOUNT_PERMITTED_BEFORE_OWNER_PROOF')
        self._turn_handoff(acct[2],next_acct[2],new_epoch)
        snap=self.feed.snapshot(acct[0])
        outcome=ExecutionOutcomeEvidence('outcome-q9-end-'+dispatch.action_id[7:],acct[0],command.client_instance_id,1,snap.turn_epoch,snap.canonical_cursor,'CONFIRMATION',('TURN_OWNER_CHANGED',),True,dispatch.action_id,acct[2])
        settled=self.execution.reconcile(dispatch.action_id,outcome)
        self._signal('ACTION_OUTCOME',fight_epoch=1,action_id=dispatch.action_id,action_status=settled.status)
        if settled.status!='SETTLED_SUCCESS':raise RuntimeError('Q9_END_TURN_NOT_SETTLED')
        if not self.coord.turn_permit(PARTY,next_acct[0]).allowed:
            raise RuntimeError('Q9_NEXT_ACCOUNT_NOT_PERMITTED_AFTER_OWNER_PROOF')
        return dispatch,settled
    def prepare_first_turn(self):
        self._signal('START');self._signal('PREFLIGHT_OK')
        for acct in (CRA,ENU):self._bootstrap_world_account(acct)
        # Both clients traverse the same Workflow-owned route step; only after
        # both authoritative world consequences are settled does the mission
        # advance its route cursor.
        for acct in (CRA,ENU):self._run_world_move(acct,WORLD_MAP+1)
        self._signal('ROUTE_STEP_PROVEN')
        encounter_id='encounter-q9-1';encounter_map_id=WORLD_MAP+1
        self._signal('ENCOUNTER_SELECTED',encounter_id=encounter_id,encounter_map_id=encounter_map_id)
        # Leader starts the selected encounter from world state.  The follower
        # remains in world state and gets a separate target-fight observation.
        self._run_fight_entry(CRA,encounter_id,encounter_map_id)
        self._signal('FIGHT_ENTRY_PROVEN',fight_epoch=1)
        self._coord_obs(CRA,'JOIN');self._coord_join_target(ENU)
        if self.coord.snapshot().join_barrier.satisfied:raise RuntimeError('Q9_JOIN_BARRIER_PREMATURE')
        self._run_join(ENU)
        if not self.coord.snapshot().join_barrier.satisfied:raise RuntimeError('Q9_JOIN_NOT_SATISFIED')
        self._signal('PARTY_JOIN_PROVEN',fight_epoch=1)
        for acct in (CRA,ENU):self._run_placement(acct)
        if not self.coord.snapshot().placement_barrier.satisfied:raise RuntimeError('Q9_PLACEMENT_NOT_SATISFIED')
        self._signal('PLACEMENT_PROVEN',fight_epoch=1)
        for acct in (CRA,ENU):self._run_ready(acct)
        if not self.coord.snapshot().ready_barrier.satisfied:raise RuntimeError('Q9_READY_NOT_SATISFIED')
        self._signal('READY_PROVEN',fight_epoch=1)
        self._turn_start(CRA[2],1)
        for acct in (CRA,ENU):self._coord_obs(acct,'TURN')
        if self.coord.snapshot().turn_owner_account_id!=CRA[0]:raise RuntimeError('Q9_CRA_OWNER_NOT_PROVEN')
        self._signal('FIRST_TURN_PROVEN',fight_epoch=1)
        return self.workflow.snapshot()

    def happy_path(self)->Q9Result:
        self.prepare_first_turn()
        d1,o1=self._run_action(CRA)
        if o1.status!='SETTLED_SUCCESS':raise RuntimeError('Q9_CRA_ACTION_NOT_SETTLED')
        dt,ot=self._run_end_turn_and_handoff(CRA,ENU,2)
        if self.coord.snapshot().turn_owner_account_id!=ENU[0]:raise RuntimeError('Q9_ENU_OWNER_NOT_PROVEN')
        d2,o2=self._run_action(ENU)
        if o2.status!='SETTLED_SUCCESS':raise RuntimeError('Q9_ENU_ACTION_NOT_SETTLED')
        for acct in (CRA,ENU):self.feed.push(acct[0],(('FIGHT_ENDED',{},None,1,None),))
        self._signal('FIGHT_ENDED',fight_epoch=1);self._signal('FIGHT_OUTCOME',fight_epoch=1,result='VICTORY')
        for acct in (CRA,ENU):self.feed.push(acct[0],(('WORLD_REENTRY',{'map_id':WORLD_MAP+1},2,None,None),))
        self._signal('WORLD_REENTRY_PROVEN',fight_epoch=1)
        snap=self.workflow.snapshot();audit=self.feed.writer.audit()
        if snap.phase!='COMPLETED' or snap.wins!=1 or snap.attempts!=1:raise RuntimeError('Q9_WORKFLOW_NOT_COMPLETED')
        if self.execution.physical_input_count!=0:raise RuntimeError('Q9_OS_INPUT_OCCURRED')
        return Q9Result('PASS',snap.phase,snap.attempts,snap.wins,self.driver.call_count,self.execution.physical_input_count,audit['events'],len(self.ledger.audit()),self.coord.party_generation,self.observer.dropped)
