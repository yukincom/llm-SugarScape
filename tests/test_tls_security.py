import asyncio
import hashlib
from importlib import metadata
import io
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import aiohttp
from aiohttp import web

from llm_api import TLS_CONTEXT, ServerConnectionError, chat_completion_request, ensure_server_reachable
from tls_security import (MIN_CERTIFI, REJECTED_ROOT_SHA256, SecurityEnvironmentError,
                          checked_ca_file, configured_context, context_from_ca, require_version, security_report)
from tools import bootstrap_environment
from tools.verify_desktop import bundle_ca_paths, refresh_bundle_ca

REJECTED_CA = Path(__file__).parent / 'fixtures/emsign-ecc-root-g3.pem'


class TrustPolicyTests(unittest.TestCase):
    def test_minimum_versions_and_missing_installers_fail_closed(self):
        for version in ('2026.7.22', '2026.10.18', '2026.10.19rc1', 'unknown'):
            with self.subTest(version=version), patch('tls_security.metadata.version', return_value=version):
                with self.assertRaises(SecurityEnvironmentError):
                    require_version('certifi', MIN_CERTIFI)
        with patch('tls_security.metadata.version', return_value=MIN_CERTIFI):
            self.assertEqual(require_version('certifi', MIN_CERTIFI), MIN_CERTIFI)
        with patch('tls_security.metadata.version', return_value=MIN_CERTIFI + '.post1'):
            self.assertEqual(require_version('certifi', MIN_CERTIFI), MIN_CERTIFI + '.post1')
        with patch('tls_security.metadata.version', side_effect=metadata.PackageNotFoundError):
            self.assertIsNone(require_version('pip', '26.2.2', optional=True))
            with self.assertRaises(SecurityEnvironmentError):
                require_version('certifi', MIN_CERTIFI)
        with patch('tls_security.metadata.version', return_value='26.2.1'):
            with self.assertRaises(SecurityEnvironmentError):
                require_version('pip', '26.2.2', optional=True)

    def test_compromised_root_and_missing_bundle_are_rejected(self):
        with self.assertRaises(SecurityEnvironmentError):
            context_from_ca(REJECTED_CA)
        with patch('certifi.where', return_value='/missing/sugarscape-ca.pem'):
            with self.assertRaises(SecurityEnvironmentError):
                checked_ca_file()

    def test_stale_explicit_ca_is_rejected_instead_of_ignored(self):
        with patch.dict(os.environ, {'SSL_CERT_FILE': str(REJECTED_CA),
                                    'SSL_CERT_DIR': ''}):
            with self.assertRaisesRegex(SecurityEnvironmentError, 'emSign'):
                configured_context()
        context = configured_context()
        roots = {hashlib.sha256(root).hexdigest() for root in context.get_ca_certs(binary_form=True)}
        self.assertNotIn(REJECTED_ROOT_SHA256, roots)
        self.assertGreater(len(roots), 100)
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertFalse(security_report()['rejected_root_present'])

    def test_compromised_root_cannot_hide_in_lazy_capath(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '12345678.0').write_bytes(REJECTED_CA.read_bytes())
            with patch.dict(os.environ, {'SSL_CERT_FILE': str(checked_ca_file()), 'SSL_CERT_DIR': str(root)}):
                with self.assertRaisesRegex(SecurityEnvironmentError, 'emSign'):
                    configured_context()

    def test_ca_comments_need_not_be_ascii(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'commented.pem'
            path.write_bytes('# 社内CAの説明\n'.encode() + checked_ca_file().read_bytes())
            with patch.dict(os.environ, {'SSL_CERT_FILE': str(path), 'SSL_CERT_DIR': ''}):
                self.assertEqual(len(configured_context().get_ca_certs()),
                                 len(context_from_ca(checked_ca_file()).get_ca_certs()))

    def test_new_build_replaces_host_ca_and_clears_extra_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / 'Test.app'
            extra = app / 'Contents/Resources/openssl.ca/certs'
            extra.mkdir(parents=True)
            (extra / 'stale.pem').write_bytes(REJECTED_CA.read_bytes())
            refresh_bundle_ca(app)
            self.assertEqual(list(extra.iterdir()), [])
            self.assertEqual((extra.parent / 'cert.pem').read_bytes(), checked_ca_file().read_bytes())

    def test_bundle_verification_uses_the_actual_bootstrap_and_rejects_other_paths(self):
        boot = '''def _setup_openssl():
    import os
    resourcepath = os.environ["RESOURCEPATH"]
    os.environ["SSL_CERT_FILE"] = os.path.join(resourcepath, "openssl.ca", "cert.pem")
    os.environ["SSL_CERT_DIR"] = os.path.join(resourcepath, "openssl.ca", "certs")
_setup_openssl()
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '__boot__.py').write_text(boot)
            self.assertEqual(bundle_ca_paths(root)['SSL_CERT_FILE'], root / 'openssl.ca/cert.pem')
            for old, new in (('cert.pem', 'legacy.pem'), ('"certs"', '"legacy-certs"')):
                (root / '__boot__.py').write_text(boot.replace(old, new))
                with self.assertRaises(ValueError):
                    bundle_ca_paths(root)

    def test_bootstrap_rejects_unauthenticated_wheel_before_executing_pip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'pyvenv.cfg').write_text('test fixture')
            with patch.object(bootstrap_environment, 'urlopen', return_value=io.BytesIO(b'wrong wheel')), \
                    patch.object(bootstrap_environment.subprocess, 'run') as execute:
                with self.assertRaisesRegex(RuntimeError, 'SHA-256 mismatch'):
                    bootstrap_environment.install_environment(root)
                execute.assert_not_called()

    def test_bootstrap_authenticates_then_installs_offline_before_resolving(self):
        payload = b'authenticated test wheel'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'pyvenv.cfg').write_text('test fixture')
            with patch.object(bootstrap_environment, 'urlopen', return_value=io.BytesIO(payload)), \
                    patch.object(bootstrap_environment, 'PIP_SHA256', hashlib.sha256(payload).hexdigest()), \
                    patch.object(bootstrap_environment.subprocess, 'run') as execute:
                bootstrap_environment.install_environment(root, desktop=True)
            bootstrap, install, check, verify, native = execute.call_args_list
            self.assertIn('--no-index', bootstrap.args[0])
            self.assertIn('--no-deps', bootstrap.args[0])
            self.assertIn('--force-reinstall', bootstrap.args[0])
            self.assertIn('--use-deprecated=legacy-certs', install.args[0])
            self.assertTrue(install.args[0][-1].endswith('requirements-desktop.txt'))
            self.assertTrue(native.args[0][-1].endswith('tools/build_native.py'))
            for call in execute.call_args_list:
                self.assertNotIn('REQUESTS_CA_BUNDLE', call.kwargs['env'])
                self.assertNotIn('--trusted-host', call.args[0])


class TLSHandshakeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        directory = Path(self.temporary.name)
        config = directory / 'openssl.cnf'
        config.write_text('[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n'
                          '[dn]\nCN=localhost\n[ext]\nsubjectAltName=DNS:localhost\n'
                          'basicConstraints=critical,CA:TRUE\nkeyUsage=critical,digitalSignature,keyCertSign\n')
        self.cert = directory / 'server.pem'
        key = directory / 'server.key'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                        '-keyout', str(key), '-out', str(self.cert), '-config', str(config)],
                       check=True, capture_output=True)
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(self.cert, key)
        self.received = []

        async def completion(request):
            self.received.append(request.method)
            if request.method == 'HEAD':
                return web.Response(status=405)
            return web.json_response({'choices': [{'message': {'content': 'local TLS test'}}]})

        app = web.Application()
        app.router.add_route('*', '/v1/chat/completions', completion)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.addAsyncCleanup(self.runner.cleanup)
        site = web.TCPSite(self.runner, '127.0.0.1', 0, ssl_context=server_context)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]

    async def test_custom_ca_file_and_hashed_directory_preserve_https(self):
        directory = Path(self.temporary.name) / 'ca-directory'
        directory.mkdir()
        digest = subprocess.run(['openssl', 'x509', '-hash', '-noout', '-in', str(self.cert)],
                                check=True, capture_output=True, text=True).stdout.strip()
        (directory / f'{digest}.0').symlink_to(self.cert)
        empty = Path(self.temporary.name) / 'empty-ca-directory'
        empty.mkdir()
        for settings in ({'SSL_CERT_FILE': str(self.cert), 'SSL_CERT_DIR': ''},
                         {'SSL_CERT_FILE': '', 'SSL_CERT_DIR': str(directory)},
                         {'SSL_CERT_FILE': '', 'SSL_CERT_DIR': os.pathsep.join(map(str, (empty, directory)))}):
            with self.subTest(settings=settings), patch.dict(os.environ, settings):
                context = configured_context()
                self.assertEqual(len(context.get_ca_certs()), 1)
                with patch('llm_api.TLS_CONTEXT', context):
                    async with aiohttp.ClientSession() as session:
                        await ensure_server_reachable(session, base_url=f'https://localhost:{self.port}/v1', timeout=2)
                        async with chat_completion_request(session, base_url=f'https://localhost:{self.port}/v1',
                                                           model='test', messages=[]) as response:
                            self.assertEqual(response.status, 200)
        self.assertEqual(self.received, ['HEAD', 'POST'] * 3)

    async def test_custom_ca_server_auth_rejection_is_preserved(self):
        rejected = Path(self.temporary.name) / 'rejected-server-auth.pem'
        subprocess.run(['openssl', 'x509', '-in', str(self.cert), '-addreject', 'serverAuth',
                        '-trustout', '-out', str(rejected)], check=True, capture_output=True)
        with patch.dict(os.environ, {'SSL_CERT_FILE': str(rejected), 'SSL_CERT_DIR': ''}):
            context = configured_context()
        with patch('llm_api.TLS_CONTEXT', context):
            async with aiohttp.ClientSession() as session:
                with self.assertRaises(aiohttp.ClientConnectorCertificateError):
                    async with chat_completion_request(session, base_url=f'https://localhost:{self.port}/v1',
                                                       model='test', messages=[]):
                        self.fail('A CA explicitly rejected for serverAuth must remain rejected')
        self.assertEqual(self.received, [])

    async def test_local_http_uses_the_same_api_without_tls_changes(self):
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        async with aiohttp.ClientSession() as session:
            await ensure_server_reachable(session, base_url=f'http://127.0.0.1:{port}/v1', timeout=2)
            async with chat_completion_request(session, base_url=f'http://127.0.0.1:{port}/v1',
                                               model='test', messages=[]) as response:
                self.assertEqual(response.status, 200)
        self.assertEqual(self.received, ['HEAD', 'POST'])

    async def test_verified_https_works_and_unknown_ca_never_falls_back(self):
        url = f'https://localhost:{self.port}/v1'
        trusted_test_context = context_from_ca(self.cert)
        async with aiohttp.ClientSession() as session:
            with patch('llm_api.TLS_CONTEXT', trusted_test_context):
                await ensure_server_reachable(session, base_url=url, timeout=2)
                async with chat_completion_request(session, base_url=url, model='test', messages=[]) as response:
                    self.assertEqual((await response.json())['choices'][0]['message']['content'], 'local TLS test')
            self.assertEqual(self.received, ['HEAD', 'POST'])
            with self.assertRaises(ServerConnectionError):
                await ensure_server_reachable(session, base_url=url, timeout=2)
            with self.assertRaises(aiohttp.ClientConnectorCertificateError):
                async with chat_completion_request(session, base_url=url, model='test', messages=[]):
                    self.fail('Unknown CA must not pass')
            self.assertEqual(self.received, ['HEAD', 'POST'])

    async def test_hostname_mismatch_is_rejected_even_with_trusted_test_ca(self):
        with patch('llm_api.TLS_CONTEXT', context_from_ca(self.cert)):
            async with aiohttp.ClientSession() as session:
                with self.assertRaises(aiohttp.ClientConnectorCertificateError):
                    async with chat_completion_request(session, base_url=f'https://127.0.0.1:{self.port}/v1',
                                                       model='test', messages=[]):
                        self.fail('Hostname mismatch must not pass')
        self.assertEqual(self.received, [])


if __name__ == '__main__':
    unittest.main()
