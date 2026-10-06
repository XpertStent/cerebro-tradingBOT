import ast
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ApiKeySettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        source = Path(__file__).resolve().parents[1] / 'app/services/settings.py'
        module = ast.parse(source.read_text())
        # Load the real settings service against a temporary database, without
        # initializing the application's /data singleton during test import.
        module.body = [node for node in module.body if not (
            isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == 'settings'
                for target in node.targets
            )
        )]
        self.namespace = {}
        exec(compile(module, str(source), 'exec'), self.namespace)
        self.namespace['DB_PATH'] = Path(self.directory.name) / 'settings.db'
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.service = self.namespace['SettingsService']()

    def public_items(self):
        return {item['key']: item for item in self.service.public_snapshot()['settings']}

    def test_api_section_contains_only_the_three_credentials(self):
        snapshot = self.service.public_snapshot()
        self.assertIn('API KEYS', snapshot['sections'])
        keys = [item for item in snapshot['settings'] if item['section'] == 'API KEYS']
        self.assertEqual({item['key'] for item in keys}, {
            'openai.api_key', 'alpaca.api_key', 'alpaca.secret_key',
        })
        self.assertTrue(all(item['type'] == 'secret' for item in keys))
        self.assertTrue(all(item['section'] == 'API KEYS' for item in snapshot['settings'] if item['type'] == 'secret'))

    def test_saved_keys_persist_and_never_appear_in_public_responses(self):
        credentials = {
            'openai.api_key': 'synthetic-openai-credential',
            'alpaca.api_key': 'synthetic-alpaca-key',
            'alpaca.secret_key': 'synthetic-alpaca-secret',
        }
        response = self.service.update_many(credentials)
        restarted = self.namespace['SettingsService']()
        for key, value in credentials.items():
            self.assertEqual(restarted.get(key), value)
            self.assertNotIn(value, json.dumps(response))
            public = self.public_items()[key]
            self.assertTrue(public['configured'])
            self.assertIsNone(public['value'])

    def test_moving_openai_does_not_change_its_lookup_or_model_reset(self):
        # An existing deployment has this same database key already saved.
        self.service.update_many({'openai.api_key': 'synthetic-existing-key'})
        self.service.reset('AI & Models')
        self.assertEqual(self.service.get('openai.api_key'), 'synthetic-existing-key')
        self.assertTrue(self.public_items()['openai.api_key']['configured'])

    def test_blank_fields_keep_keys_and_api_reset_clears_only_saved_credentials(self):
        self.service.update_many({
            'alpaca.api_key': 'synthetic-key',
            'alpaca.secret_key': 'synthetic-secret',
            'ai.research.model': 'synthetic-model',
        })
        self.service.update_many({'alpaca.api_key': '  ', 'alpaca.secret_key': ''})
        self.assertEqual(self.service.get('alpaca.api_key'), 'synthetic-key')
        self.assertEqual(self.service.get('alpaca.secret_key'), 'synthetic-secret')
        self.service.reset('API KEYS')
        self.assertFalse(self.public_items()['alpaca.api_key']['configured'])
        self.assertEqual(self.service.get('ai.research.model'), 'synthetic-model')

    def test_openai_environment_fallback_is_still_masked(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-env-key'}):
            self.assertEqual(self.service.get('openai.api_key'), 'synthetic-env-key')
            self.assertNotIn('synthetic-env-key', json.dumps(self.service.public_snapshot()))

    def test_invalid_keys_have_generic_errors_and_no_partial_save(self):
        for invalid in ['synthetic\x16bad', 'synthetic key', 'synthetic\nbad', 'synthetic\u200bbad', True, {'key': 'synthetic'}]:
            with self.assertRaises(ValueError) as caught:
                self.service.update_many({'alpaca.api_key': 'synthetic-good', 'alpaca.secret_key': invalid})
            self.assertNotIn('synthetic', str(caught.exception))
            self.assertIsNone(self.service.get('alpaca.api_key'))


if __name__ == '__main__': unittest.main()
