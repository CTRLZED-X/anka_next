"""P53 historical character identity and process/flow topology falsification."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
import unittest

from anka_app.ingress_readiness import historical_character_process_topology
from anka_capture.windows_flows import TcpEndpoint
from anka_contracts.client import WindowObservation, WindowScan
from anka_contracts.historical_identity import HistoricalIdentityScope
from anka_contracts.protocol import WireMessage
from anka_protocol.adapters.historical_identity import HistoricalIdentityDecoder, BUILD


def var(n):
    if n < 0:n=(1<<64)+n
    out=bytearray()
    while n>=128:
        out.append((n&127)|128);n>>=7
    out.append(n);return bytes(out)

def vint(field,n): return var(field<<3)+var(n)
def blob(field,b): return var((field<<3)|2)+var(len(b))+b

def entity(actor,cell,name=None):
    out=vint(1,actor)+blob(2,vint(3,cell))
    if name is not None:
        identity=blob(1,blob(3,blob(5,name.encode('utf8'))))
        out+=blob(3,identity)
    return out

def jnj(map_id,*entities):
    return b''.join(blob(3,e) for e in entities)+vint(10,map_id)

TIME=10**10
K1=('192.0.2.1',45670,'198.51.100.7',40400)
K2=('192.0.2.1',45671,'198.51.100.7',40400)

def window(pid,hwnd=None,title='Dofus'):
    return WindowObservation(hwnd or pid+1000,pid,pid+9000,'Dofus.exe',title,1280,649,96,False)

def host_fixture():
    wins=(window(101),window(102))
    before=WindowScan(TIME,wins);after=WindowScan(TIME+1000,wins)
    tcp=(TcpEndpoint(*K1,101,5),TcpEndpoint(*K2,102,5))
    return before,after,tcp,tcp,{'flow-a':K1,'flow-b':K2}


class P53HistoricalIdentityTests(unittest.TestCase):
    def setUp(self):
        self.decoder=HistoricalIdentityDecoder(requested_build=BUILD)
        self.scope=HistoricalIdentityScope(sha256(b'flow-a').hexdigest(),3,BUILD,'Curseni')

    def msg(self,name='jnj',body=None,flow='flow-a',generation=3,direction='server_to_client',packet=1,index=0):
        if body is None:body=jnj(777,entity(41,301,'Curseni'))
        return WireMessage(direction,name,body,packet,flow,generation,index)

    def decode(self,**kw):
        return self.decoder.decode(self.msg(**kw),scope=self.scope)

    def test_jnj_exact_name_produces_historical_identity_only(self):
        r=self.decode()
        self.assertEqual(r.status,'OBSERVATIONS_ONLY')
        o=r.observations[0]
        self.assertEqual((o.character_name,o.actor_id,o.cell_id,o.map_id),('Curseni',41,301,777))
        self.assertEqual(o.authority,'HISTORICAL_RESEARCH_ONLY')
        self.assertFalse(o.current_client_certified)
        self.assertEqual(o.canonical_commits,0)
        self.assertFalse(o.physical_input_sent)

    def test_guild_suffix_form_matches_but_records_configured_name_only(self):
        r=self.decode(body=jnj(777,entity(41,301,'Curseni-[Guild]')))
        self.assertEqual(r.status,'OBSERVATIONS_ONLY')
        self.assertEqual(r.observations[0].character_name,'Curseni')

    def test_case_insensitive_exact_match(self):
        self.assertEqual(self.decode(body=jnj(777,entity(41,301,'cUrSeNi'))).status,'OBSERVATIONS_ONLY')

    def test_substring_or_wrong_suffix_does_not_match(self):
        for value in ('SuperCurseni','CurseniX','Curseni-[Guild','Curseni-Other','Other'):
            with self.subTest(value=value):
                self.assertEqual(self.decode(body=jnj(777,entity(41,301,value))).status,'NO_MATCH')

    def test_non_player_or_nameless_entity_is_ignored(self):
        r=self.decode(body=jnj(777,entity(-90,200,None),entity(41,301,'Curseni')))
        self.assertEqual(r.status,'OBSERVATIONS_ONLY')
        self.assertEqual(r.observations[0].actor_id,41)

    def test_two_matching_entities_are_ambiguous(self):
        r=self.decode(body=jnj(777,entity(41,301,'Curseni'),entity(42,302,'Curseni-[Guild]')))
        self.assertEqual((r.status,r.failure_code),('QUARANTINED','P53_CHARACTER_IDENTITY_AMBIGUOUS'))

    def test_jns_code_path_is_explicitly_not_identity_capability(self):
        r=self.decode(name='jns',body=blob(1,entity(41,301,'Curseni')))
        self.assertEqual((r.status,r.failure_code),('CAPABILITY_UNDECLARED','P53_JNS_LOCAL_ACTOR_NOT_REGISTRY_DECLARED'))
        self.assertFalse(r.current_client_certified)

    def test_jns_does_not_parse_malformed_payload_into_identity(self):
        r=self.decode(name='jns',body=b'\xff')
        self.assertEqual(r.status,'CAPABILITY_UNDECLARED')
        self.assertFalse(r.observations)

    def test_wrong_build_never_decodes(self):
        d=HistoricalIdentityDecoder(requested_build='Dofus 9.9.9.9')
        self.assertEqual(d.decode(self.msg(),scope=self.scope).status,'BUILD_MISMATCH')

    def test_wrong_flow_generation_or_missing_scope_is_unverified(self):
        for msg,scope in ((self.msg(flow='wrong'),self.scope),(self.msg(generation=4),self.scope),(self.msg(),None)):
            with self.subTest(msg=msg,scope=scope):
                self.assertEqual(self.decoder.decode(msg,scope=scope).status,'SCOPE_UNVERIFIED')

    def test_client_direction_quarantined(self):
        r=self.decode(direction='client_to_server')
        self.assertEqual((r.status,r.failure_code),('QUARANTINED','P53_UNTRUSTED_DIRECTION'))

    def test_unknown_wire_no_mapping(self):
        self.assertEqual(self.decode(name='abc').status,'NO_MAPPING')

    def test_missing_or_duplicate_map_id_quarantined(self):
        for body in (blob(3,entity(41,301,'Curseni')),jnj(777,entity(41,301,'Curseni'))+vint(10,778)):
            with self.subTest(body=body):
                self.assertEqual(self.decode(body=body).status,'QUARANTINED')

    def test_missing_actor_or_pose_does_not_create_identity(self):
        missing_actor=blob(2,vint(3,301))+blob(3,blob(1,blob(3,blob(5,b'Curseni'))))
        missing_pose=vint(1,41)+blob(3,blob(1,blob(3,blob(5,b'Curseni'))))
        for raw in (missing_actor,missing_pose):
            with self.subTest(raw=raw):
                self.assertEqual(self.decode(body=jnj(777,raw)).status,'QUARANTINED')

    def test_invalid_utf8_name_is_ignored_not_guessed(self):
        raw=vint(1,41)+blob(2,vint(3,301))+blob(3,blob(1,blob(3,blob(5,b'\xff'))))
        self.assertEqual(self.decode(body=jnj(777,raw)).status,'NO_MATCH')

    def test_zero_actor_or_invalid_map_rejected(self):
        for body in (jnj(777,entity(0,301,'Curseni')),jnj(0,entity(41,301,'Curseni'))):
            with self.subTest(body=body):
                self.assertEqual(self.decode(body=body).status,'QUARANTINED')

    def test_topology_composes_two_historical_names_with_two_stable_processes(self):
        args=host_fixture()
        cra=self.decode().observations[0]
        enu_scope=HistoricalIdentityScope(sha256(b'flow-b').hexdigest(),3,BUILD,'Sosoking')
        enu=self.decoder.decode(self.msg(body=jnj(777,entity(42,302,'Sosoking')),flow='flow-b'),scope=enu_scope).observations[0]
        r=historical_character_process_topology(*args,{'flow-a':cra,'flow-b':enu},expected_character_names=('Curseni','Sosoking'))
        self.assertEqual((r['status'],r['matched_process_character_candidates'],r['distinct_candidate_processes']),
                         ('HISTORICAL_CANDIDATES_ONLY',2,2))
        self.assertTrue(r['historical_build_verified'])
        self.assertTrue(r['historical_identity_only'])
        self.assertEqual(r['independent_current_character_witnesses'],0)
        self.assertFalse(r['account_binding_verified'])
        self.assertFalse(r['current_build_certified'])
        self.assertFalse(r['actionable'])

    def test_duplicate_character_on_two_flows_blocks(self):
        args=host_fixture();a=self.decode().observations[0]
        scope2=HistoricalIdentityScope(sha256(b'flow-b').hexdigest(),3,BUILD,'Curseni')
        b=self.decoder.decode(self.msg(body=jnj(777,entity(42,302,'Curseni')),flow='flow-b'),scope=scope2).observations[0]
        r=historical_character_process_topology(*args,{'flow-a':a,'flow-b':b},expected_character_names=('Curseni','Sosoking'))
        self.assertEqual((r['status'],r['duplicate_character_claims']),('BLOCKED_AMBIGUOUS',1))

    def test_two_names_on_same_process_blocks(self):
        b,a,bt,at,keys=host_fixture()
        shared=(TcpEndpoint(*K1,101,5),TcpEndpoint(*K2,101,5))
        cra=self.decode().observations[0]
        scope2=HistoricalIdentityScope(sha256(b'flow-b').hexdigest(),3,BUILD,'Sosoking')
        enu=self.decoder.decode(self.msg(body=jnj(777,entity(42,302,'Sosoking')),flow='flow-b'),scope=scope2).observations[0]
        r=historical_character_process_topology(b,a,shared,shared,keys,{'flow-a':cra,'flow-b':enu},expected_character_names=('Curseni','Sosoking'))
        self.assertEqual((r['status'],r['shared_process_character_conflicts']),('BLOCKED_AMBIGUOUS',1))

    def test_witness_flow_digest_must_match_private_flow_token(self):
        args=host_fixture();a=self.decode().observations[0]
        r=historical_character_process_topology(*args,{'flow-b':a},expected_character_names=('Curseni','Sosoking'))
        self.assertEqual((r['status'],r['invalid_identity_witnesses']),('BLOCKED_AMBIGUOUS',1))

    def test_unexpected_character_witness_blocks(self):
        args=host_fixture()
        scope=HistoricalIdentityScope(sha256(b'flow-a').hexdigest(),3,BUILD,'SomeoneElse')
        obs=self.decoder.decode(self.msg(body=jnj(777,entity(41,301,'SomeoneElse'))),scope=scope).observations[0]
        r=historical_character_process_topology(*args,{'flow-a':obs},expected_character_names=('Curseni','Sosoking'))
        self.assertEqual((r['status'],r['unexpected_character_witnesses']),('BLOCKED_AMBIGUOUS',1))

    def test_missing_second_identity_is_partial(self):
        args=host_fixture();a=self.decode().observations[0]
        r=historical_character_process_topology(*args,{'flow-a':a},expected_character_names=('Curseni','Sosoking'))
        self.assertEqual((r['status'],r['missing_character_witnesses']),('PARTIAL_CANDIDATES',1))

    def test_host_owner_disappearing_makes_identity_partial_not_verified(self):
        b,a,bt,at,keys=host_fixture();cra=self.decode().observations[0]
        r=historical_character_process_topology(b,a,bt,at[1:],keys,{'flow-a':cra},expected_character_names=('Curseni',))
        self.assertEqual(r['status'],'PARTIAL_CANDIDATES')
        self.assertGreaterEqual(r['unowned_identity_witnesses'],1)
        self.assertFalse(r['account_binding_verified'])

    def test_duplicate_socket_selectors_block_before_identity_composition(self):
        b,a,bt,at,keys=host_fixture();cra=self.decode().observations[0]
        r=historical_character_process_topology(b,a,bt,at,{'flow-a':K1,'flow-b':K1},{'flow-a':cra},expected_character_names=('Curseni',))
        self.assertEqual((r['status'],r['reason']),('BLOCKED_AMBIGUOUS','P53_DUPLICATE_SOCKET_SELECTORS'))

    def test_private_identity_and_host_details_never_escape_topology_report(self):
        args=host_fixture();cra=self.decode().observations[0]
        r=historical_character_process_topology(*args,{'flow-a':cra},expected_character_names=('Curseni','Sosoking'))
        text=json.dumps(r)
        for secret in ('Curseni','Sosoking','flow-a','192.0.2.1','198.51.100.7','45670','101','Private'):
            with self.subTest(secret=secret):self.assertNotIn(secret,text)

    def test_invalid_expected_names_fail_closed(self):
        args=host_fixture()
        for names in ((),('Curseni','curseni'),('x',),(' Curseni',),('a'*41,),['Curseni']):
            with self.subTest(names=names):
                self.assertEqual(historical_character_process_topology(*args,{},expected_character_names=names)['status'],'UNAVAILABLE')

    def test_forged_non_observation_witness_is_rejected(self):
        args=host_fixture()
        r=historical_character_process_topology(*args,{'flow-a':'fake'},expected_character_names=('Curseni',))
        self.assertEqual((r['status'],r['invalid_identity_witnesses']),('BLOCKED_AMBIGUOUS',1))

if __name__=='__main__': unittest.main()
