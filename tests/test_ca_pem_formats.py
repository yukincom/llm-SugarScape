import os
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import patch

from tls_security import checked_ca_file, configured_context, SecurityEnvironmentError


class OpenSSLPEMFormatsTests(unittest.TestCase):
    def test_x509_certificate_label_preserves_normal_trust(self):
        with tempfile.TemporaryDirectory() as directory:
            ca = Path(directory) / 'x509.pem'
            ca.write_bytes(checked_ca_file().read_bytes().replace(b'-----BEGIN CERTIFICATE-----', b'-----BEGIN X509 CERTIFICATE-----')
                           .replace(b'-----END CERTIFICATE-----', b'-----END X509 CERTIFICATE-----'))
            reference = ssl.create_default_context(cafile=str(ca))
            with patch.dict(os.environ, {'SSL_CERT_FILE': str(ca), 'SSL_CERT_DIR': ''}):
                self.assertEqual(set(configured_context().get_ca_certs(binary_form=True)),
                                 set(reference.get_ca_certs(binary_form=True)))

    def test_x509_label_does_not_hide_rejected_root(self):
        with tempfile.TemporaryDirectory() as directory:
            ca = Path(directory) / 'g3.pem'
            source = Path(__file__).parent / 'fixtures/emsign-ecc-root-g3.pem'
            ca.write_bytes(source.read_bytes().replace(b'-----BEGIN CERTIFICATE-----', b'-----BEGIN X509 CERTIFICATE-----')
                           .replace(b'-----END CERTIFICATE-----', b'-----END X509 CERTIFICATE-----'))
            with patch.dict(os.environ, {'SSL_CERT_FILE': str(ca), 'SSL_CERT_DIR': ''}):
                with self.assertRaisesRegex(SecurityEnvironmentError, 'emSign'):
                    configured_context()
