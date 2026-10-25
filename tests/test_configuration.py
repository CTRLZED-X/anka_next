import json
import tempfile
import unittest
from pathlib import Path
from anka_app.configuration import ConfigurationError,load_user_config

class TestConfiguration(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'user.json'
        self.obj={'schema_version':1,'players':[{'name':'Curseni','role':'leader'},{'name':'Sosoking','role':'follower'}],
                  'mission':{'route_id':'sufokia_direction_cycle','min_monsters':6,'max_monsters':8,'target_wins':5,'max_attempts':10,'stop_on_loss':True,'stop_on_unknown':True}}
    def write(self,obj=None):self.path.write_text(json.dumps(obj or self.obj),encoding='utf8')
    def test_valid(self):
        self.write(); conf=load_user_config(self.path)
        self.assertEqual(conf.mission.min_monsters,6)
        self.assertEqual(len(conf.sha256),64)
        self.assertEqual(conf.players[0].name,'Curseni')
    def test_duplicate_json_key_nested_rejected(self):
        self.path.write_text('{"schema_version":1,"players":[],"mission":{"min_monsters":1,"min_monsters":2}}')
        with self.assertRaisesRegex(ConfigurationError,'DUPLICATE_JSON_KEY'):load_user_config(self.path)
    def test_min_exceeds_max(self):
        self.obj['mission']['min_monsters']=8;self.obj['mission']['max_monsters']=1;self.write()
        with self.assertRaisesRegex(ConfigurationError,'INVALID_MONSTER_RANGE'):load_user_config(self.path)
    def test_unknown_setting(self):
        self.obj['protocol_version']='unsupported';self.write()
        with self.assertRaisesRegex(ConfigurationError,'UNKNOWN_KEYS'):load_user_config(self.path)
    def test_duplicate_name_casefold(self):
        self.obj['players'][1]['name']='curseni';self.write()
        with self.assertRaisesRegex(ConfigurationError,'DUPLICATE_PLAYER'):load_user_config(self.path)
    def test_requires_exactly_one_leader(self):
        self.obj['players'][1]['role']='leader';self.write()
        with self.assertRaisesRegex(ConfigurationError,'REQUIRES_EXACTLY_ONE_LEADER'):load_user_config(self.path)
    def test_boolean_integer_confusion(self):
        self.obj['mission']['max_attempts']=True;self.write()
        with self.assertRaisesRegex(ConfigurationError,'INVALID_INTEGER'):load_user_config(self.path)
    def test_mandatory_explicit_safety(self):
        del self.obj['mission']['stop_on_unknown'];self.write()
        with self.assertRaisesRegex(ConfigurationError,'MISSING_EXPLICIT_SAFETY_POLICY'):load_user_config(self.path)
    def test_target_wins_less_than_max_attempts(self):
        self.obj['mission']['target_wins']=11;self.write()
        with self.assertRaisesRegex(ConfigurationError,'WINS_EXCEED_ATTEMPTS'):load_user_config(self.path)
    def test_unknown_role_no_class_guess(self):
        self.obj['players'][1]['role']='enutrof';self.write()
        with self.assertRaisesRegex(ConfigurationError,'INVALID_ROLE'):load_user_config(self.path)
