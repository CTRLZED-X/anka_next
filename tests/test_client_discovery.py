"""P3 pure deterministic identity-policy regression and failure-injection tests."""
import unittest
from anka_contracts.client import WindowObservation, WindowScan, CharacterEvidence
from anka_client.discovery import bind_accounts, generation_id
from anka_client.api import ClientInspection

T=55_000_000_000

def w(hwnd=100,pid=300,created=1000,title='Curseni - Dofus',exe='Dofus.exe',size=(1280,649),minimized=False):
    return WindowObservation(hwnd,pid,created,exe,title,*size,96,minimized)

def s(*wins, errors=()):
    return WindowScan(T,tuple(wins),errors)

def e(name='Curseni',breed='CRA',hwnd=100,pid=300,created=1000,source='LIVE_PROTOCOL',at=T-10):
    return CharacterEvidence(source,name,breed,hwnd,pid,created,at)

class FakeInventory:
    def __init__(self, snapshot):self.snapshot=snapshot
    def scan(self):return self.snapshot

class FakeIdentities:
    def __init__(self,*items):self.items=items
    def snapshot(self):return self.items

class TestClientMatching(unittest.TestCase):
    def test_no_identity_never_claims_certified(self):
        b=bind_accounts(('Curseni',),s(w()))[0]
        self.assertEqual((b.state,b.reason),('PENDING','NO_AUTHORITATIVE_CHARACTER_EVIDENCE'))
        self.assertFalse(b.input_certified)
    def test_verified_exact_generation_class_uses_independent_evidence(self):
        b=bind_accounts(('Curseni',),s(w()),(e(),))[0]
        self.assertEqual((b.state,b.breed,b.evidence_source),('IDENTITY_MATCHED','CRA','LIVE_PROTOCOL'))
        self.assertFalse(b.input_certified)
    def test_binding_without_title_with_independent_evidence(self):
        b=bind_accounts(('Curseni',),s(w(title='Dofus 3.7 Release')),(e(),))[0]
        self.assertEqual(b.state,'IDENTITY_MATCHED')
    def test_two_accounts_distinct_windows(self):
        windows=s(w(),w(101,301,1001,'Sosoking - Dofus'))
        evidence=(e(),e('Sosoking','ENUTROF',101,301,1001))
        matches=bind_accounts(('Curseni','Sosoking'),windows,evidence)
        self.assertEqual([x.state for x in matches],['IDENTITY_MATCHED']*2)
        self.assertEqual([x.breed for x in matches],['CRA','ENUTROF'])
    def test_process_generation_change_blocks_old_identity(self):
        b=bind_accounts(('Curseni',),s(w(created=1002)),(e(),))[0]
        self.assertEqual((b.state,b.reason),('BLOCKED','PROCESS_GENERATION_CHANGED'))
    def test_duplicate_window_title_is_ambiguous(self):
        b=bind_accounts(('Curseni',),s(w(),w(102,302,1002)))[0]
        self.assertEqual(b.reason,'AMBIGUOUS_WINDOWS')
    def test_untrusted_process_image_not_accepted(self):
        b=bind_accounts(('Curseni',),s(w(exe='notepad.exe')),(e(),))[0]
        self.assertEqual(b.reason,'UNTRUSTED_PROCESS_IMAGE')
    def test_trusted_path_basename_not_substring(self):
        b=bind_accounts(('Curseni',),s(w(exe=r'C:\\game\\notdofus.exe')))[0]
        self.assertEqual(b.reason,'UNTRUSTED_PROCESS_IMAGE')
    def test_partial_inventory_fails_closed(self):
        b=bind_accounts(('Curseni',),s(w(),errors=('WINDOW_INSPECTION_FAILED',)),(e(),))[0]
        self.assertEqual(b.reason,'INCOMPLETE_WINDOW_INVENTORY')
    def test_title_substring_does_not_match(self):
        b=bind_accounts(('Enu',),s(w(title='Menu - Dofus')))[0]
        self.assertEqual(b.reason,'NO_CANDIDATE_WINDOW')
    def test_wrong_character_evidence_never_binds(self):
        b=bind_accounts(('Curseni',),s(w()),(e(name='Other'),))[0]
        self.assertEqual(b.state,'PENDING')
    def test_wrong_source_blocks(self):
        b=bind_accounts(('Curseni',),s(w()),(e(source='TITLE'),))[0]
        self.assertEqual(b.reason,'UNTRUSTED_EVIDENCE_SOURCE')
    def test_stale_identity_blocks(self):
        b=bind_accounts(('Curseni',),s(w()),(e(at=T-4_000_000_000),))[0]
        self.assertEqual(b.reason,'STALE_OR_FUTURE_IDENTITY_EVIDENCE')
    def test_future_identity_blocks(self):
        b=bind_accounts(('Curseni',),s(w()),(e(at=T+1),))[0]
        self.assertEqual(b.reason,'STALE_OR_FUTURE_IDENTITY_EVIDENCE')
    def test_unknown_breed_blocks(self):
        b=bind_accounts(('Curseni',),s(w()),(e(breed='Feca'),))[0]
        self.assertEqual(b.reason,'UNSUPPORTED_BREED')
    def test_ambiguous_evidence_blocks(self):
        b=bind_accounts(('Curseni',),s(w()),(e(),e(source='UNITY_BRIDGE'),))[0]
        self.assertEqual(b.reason,'AMBIGUOUS_CHARACTER_EVIDENCE')
    def test_minimized_window_blocks(self):
        b=bind_accounts(('Curseni',),s(w(minimized=True)),(e(),))[0]
        self.assertEqual(b.reason,'WINDOW_MINIMIZED')
    def test_duplicate_hwnd_blocks_everyone(self):
        b=bind_accounts(('Curseni','Sosoking'),s(w(),w(title='Sosoking - Dofus')))
        self.assertTrue(all(x.reason=='DUPLICATE_HWND_IN_SCAN' for x in b))
    def test_same_client_shared_by_two_names_blocks(self):
        b=bind_accounts(('Curseni','Sosoking'),s(w(title='Curseni Sosoking - Dofus')))
        self.assertTrue(all(x.reason=='SHARED_WINDOW_ACROSS_ACCOUNTS' for x in b))
    def test_malformed_geometry(self):
        b=bind_accounts(('Curseni',),s(w(size=(0,649))))[0]
        self.assertEqual(b.reason,'INVALID_WINDOW_GEOMETRY_OR_GENERATION')
    def test_pid_reuse_changes_generation_fingerprint(self):
        self.assertNotEqual(generation_id(w()),generation_id(w(created=1002)))
    def test_duplicate_config_names_rejected(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE_CONFIGURED_CHARACTER'):
            bind_accounts(('Curseni','curseni'),s(w()))
    def test_client_facade_cannot_authorize_input(self):
        inspection=ClientInspection(FakeInventory(s(w())),FakeIdentities(e())).inspect(('Curseni',))
        self.assertFalse(inspection['physical_input_permitted'])
        self.assertFalse(inspection['bindings'][0]['input_certified'])
        self.assertEqual(inspection['bindings'][0]['breed'],'CRA')
    def test_client_facade_does_not_invoke_input(self):
        inspection=ClientInspection(FakeInventory(s(w()))).inspect(('Curseni',))
        self.assertEqual(inspection['bindings'][0]['state'],'PENDING')
        self.assertFalse(inspection['live_character_provider'])

if __name__=='__main__':unittest.main()
