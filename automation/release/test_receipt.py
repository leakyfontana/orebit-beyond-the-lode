"""Keep transport candidates public until successful canonical receipt publication."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import receipt
import pull_deploy

COMMIT = 'a' * 40
VERSION = '0.3.2'


class ReceiptPolicyTest(unittest.TestCase):
    def publication_inputs(self, directory):
        platforms, uploaded = [], []
        for platform in receipt.PLATFORMS:
            path = 'dist/' + platform + '/Orebit-' + VERSION + '.zip'
            integrity = {'sha256': 'b' * 64, 'size': 1}
            platforms.append({'platform': platform, 'artifacts': [{'path': path, **integrity}]})
            uploaded.append({'platform': platform, 'folder': {'url': 'https://drive.google.com/drive/folders/' + platform},
                             'files': [{'path': path, 'name': 'Orebit-' + VERSION + '.zip',
                                        'url': 'https://drive.google.com/file/d/' + platform,
                                        'verification': 'download-sha256', **integrity}]})
        manifest = {'schema': 1, 'commit': COMMIT, 'version': VERSION, 'platforms': platforms}
        documents = {'manifest': manifest,
                     'drive': {'schema': 1, 'commit': COMMIT, 'version': VERSION, 'platforms': uploaded},
                     'deployment': {'status': 'deployed', 'commit': COMMIT, 'version': VERSION,
                                    'site': receipt.SITE, 'public_checks': [{'status': 200}]},
                     'web-smoke': {'menu_ready': True, 'commit': COMMIT, 'url': receipt.SITE}}
        arguments = ['receipt.py']
        for name, value in documents.items():
            path = directory / (name + '.json')
            path.write_text(json.dumps(value))
            arguments.extend(['--' + name, str(path)])
        output = directory / 'publication.json'
        arguments.extend(['--output', str(output)])
        return manifest, arguments, output

    def test_hide_only_after_successful_public_receipt(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as temporary:
                manifest, arguments, output = self.publication_inputs(Path(temporary))
                events = []

                def command(arguments, **kwargs):
                    events.append(arguments[2])
                    if fail and arguments[2] == 'edit':
                        raise subprocess.CalledProcessError(1, arguments)

                with patch('sys.argv', arguments), patch.object(receipt, 'aggregate', return_value=manifest), patch.object(receipt, 'require_trusted_default_branch'), patch.object(receipt, 'validate_remote_version', return_value='v' + VERSION), patch.object(receipt, 'find_release', return_value=None), patch.object(receipt, 'release_notes', return_value={'markdown': 'Notes', 'commits': []}), patch.object(receipt.subprocess, 'run', side_effect=command), patch.object(receipt, 'hide_candidate', side_effect=lambda commit: events.append('hide')), contextlib.redirect_stdout(io.StringIO()):
                    if fail:
                        with self.assertRaises(subprocess.CalledProcessError):
                            receipt.main()
                        self.assertEqual(events, ['create', 'upload', 'edit'])
                    else:
                        receipt.main()
                        self.assertEqual(events, ['create', 'upload', 'edit', 'hide'])
                publication = json.loads(output.read_text())
                self.assertEqual(publication['kind'], 'orebit.publication')
                self.assertEqual(publication['version'], VERSION)
                self.assertEqual(publication['release_id'], COMMIT)

    def test_previous_release_is_highest_canonical_public_version(self):
        def release(tag, draft=False, prerelease=False):
            return {'tag_name': tag, 'draft': draft, 'prerelease': prerelease}

        releases = [release('v0.9.9'), release('candidate-' + COMMIT, prerelease=True),
                    release('v0.10.0'), release('v0.11.0', draft=True),
                    release('v0.12.0', prerelease=True), release('v0.13.0')]
        with patch.object(receipt, 'command', side_effect=[json.dumps(releases), '']) as command:
            receipt.release_notes(COMMIT, '0.13.0')
        self.assertEqual(command.call_args.args[4], 'v0.10.0..' + COMMIT)

    def test_refresh_preserves_historical_live_build_identity(self):
        embedded = '1.0-beta.8+' + COMMIT[:12]
        result = {'schema': 1, 'status': 'deployed', 'commit': COMMIT, 'version': embedded}
        record = {'commit': COMMIT, 'request': {'version': embedded}, 'public_result': result}
        with tempfile.TemporaryDirectory() as temporary:
            current = Path(temporary) / ('sha-' + COMMIT)
            current.mkdir()
            (current / 'build.json').write_text(json.dumps({'commit': COMMIT, 'version': embedded}))
            with patch.object(pull_deploy.helper, 'link_target', return_value=current), patch.object(pull_deploy, 'publish') as publish, patch.object(pull_deploy, 'save_record') as save:
                pull_deploy.refresh_deployment_status(record)
            publish.assert_called_once_with(record, result)
            save.assert_not_called()
            self.assertEqual(record['public_result']['status'], 'deployed')


if __name__ == '__main__':
    unittest.main()
