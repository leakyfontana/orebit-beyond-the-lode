"""Exercise public version boundaries without GitHub, Drive or VPS mutations."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import version_policy as policy

COMMIT = 'a' * 40
OTHER = 'b' * 40


class VersionPolicyTest(unittest.TestCase):
    def test_plain_sub_one_versions(self):
        for version in ('0.0.0', '0.3.2', '0.10.100'):
            with self.subTest(version=version):
                self.assertEqual(policy.version_tuple(version), tuple(map(int, version.split('.'))))
        for version in ('1.0.0', '0.3', 'v0.3.2', '0.03.2', '0.3.02',
                        '0.3.2-beta.1', '0.3.2+abcdef123456', '0.3.2\n', '', None):
            with self.subTest(version=version), self.assertRaises(ValueError):
                policy.version_tuple(version)

    def test_identity_keeps_commit_separate(self):
        policy.valid_identity(COMMIT, '0.3.2')
        for commit in ('a' * 12, 'A' * 40, None):
            with self.subTest(commit=commit), self.assertRaises(ValueError):
                policy.valid_identity(commit, '0.3.2')

    def test_numeric_order_not_lexical_or_release_feed_order(self):
        tags = {'v0.9.9': OTHER, 'v0.3.1': OTHER, 'v0.10.0': OTHER}
        self.assertEqual(policy.validate_version('0.10.1', COMMIT, tags), 'v0.10.1')
        for version in ('0.3.2', '0.9.10'):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, 'greater'):
                policy.validate_version(version, COMMIT, tags)

    def test_duplicate_never_belongs_to_another_commit(self):
        for allow_existing in (False, True):
            with self.subTest(allow_existing=allow_existing), self.assertRaisesRegex(ValueError, 'already exists'):
                policy.validate_version('0.3.2', COMMIT, {'v0.3.2': OTHER}, allow_existing)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            policy.validate_version('0.3.2', COMMIT, {'v0.3.2': COMMIT})
        self.assertEqual(policy.validate_version('0.3.2', COMMIT, {'v0.3.2': COMMIT}, True), 'v0.3.2')

    def test_retry_does_not_downgrade_newer_release(self):
        with self.assertRaisesRegex(ValueError, 'greater'):
            policy.validate_version('0.3.2', COMMIT, {'v0.3.2': COMMIT, 'v0.3.3': OTHER}, True)
        with self.assertRaisesRegex(ValueError, 'greater'):
            policy.validate_version('0.99.99', COMMIT, {'v1.0.0': OTHER})

    def test_annotated_tags_use_peeled_commit(self):
        for output in (
            f'{OTHER}\trefs/tags/v0.3.2\n{COMMIT}\trefs/tags/v0.3.2^{{}}\n',
            f'{COMMIT}\trefs/tags/v0.3.2^{{}}\n{OTHER}\trefs/tags/v0.3.2\n',
        ):
            with self.subTest(output=output):
                tags = policy.public_tags(output)
                self.assertEqual(tags, {'v0.3.2': COMMIT})
                policy.validate_version('0.3.2', COMMIT, tags, True)

    def test_transport_tags_are_not_public_versions(self):
        output = f'{COMMIT}\trefs/tags/candidate-{COMMIT}\n{OTHER}\trefs/tags/v0.3.1\n'
        self.assertEqual(policy.public_tags(output), {'v0.3.1': OTHER})

    def test_cli_accepts_unique_and_rejects_duplicate_and_prerelease(self):
        cases = [('0.3.2', False, {}), ('0.3.2', True, {'v0.3.2': OTHER}),
                 ('0.3.2-beta', True, {})]
        for version, rejected, tags in cases:
            output = ''.join(f'{commit}\trefs/tags/{tag}\n' for tag, commit in tags.items())
            with self.subTest(version=version, tags=tags), patch('sys.argv', ['version_policy.py', '--sha', COMMIT, '--version', version]), patch.object(policy.subprocess, 'check_output', return_value=output), contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()):
                if rejected:
                    with self.assertRaises(SystemExit) as error:
                        policy.main()
                    self.assertEqual(error.exception.code, 1)
                else:
                    policy.main()
                    self.assertEqual(json.loads(stdout.getvalue())['tag'], 'v0.3.2')

    def test_source_platform_versions_must_agree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'godot').mkdir()
            presets = root / 'godot/export_presets.cfg'
            presets.write_text('[preset.1.options]\nversion/name="0.3.2"\n[preset.3.options]\napplication/short_version="0.3.2"\n')
            with patch.object(policy, 'ROOT', root):
                self.assertEqual(policy.source_version(), '0.3.2')
                presets.write_text(presets.read_text().replace('short_version="0.3.2"', 'short_version="0.3.1"'))
                with self.assertRaisesRegex(ValueError, 'differ'):
                    policy.source_version()


if __name__ == '__main__':
    unittest.main()
