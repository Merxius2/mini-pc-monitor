import unittest

from src.qr import qr_png_bytes
from src.samba import smb_connect_url


class TestSambaConnectUrl(unittest.TestCase):
    def test_unc_to_smb_url(self):
        self.assertEqual(smb_connect_url("//192.168.1.30/storage"), "smb://192.168.1.30/storage")

    def test_passthrough_smb(self):
        self.assertEqual(smb_connect_url("smb://host/share"), "smb://host/share")

    def test_windows_unc(self):
        self.assertEqual(smb_connect_url("\\\\192.168.1.30\\storage"), "smb://192.168.1.30/storage")


class TestQrPng(unittest.TestCase):
    def test_png_magic(self):
        data = qr_png_bytes("smb://192.168.1.30/storage")
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
