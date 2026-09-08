"""Installer trust boundaries; no network or executable execution."""
import hashlib
import gzip
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import omaproxy as bridge


class Response(io.BytesIO):
    def __init__(self, data, length=None):
        super().__init__(data)
        self.headers = {} if length is None else {'Content-Length': length}
        self.read_sizes = []

    def read(self, size=-1):
        assert size > 0, 'Unbounded read is forbidden'
        self.read_sizes.append(size)
        return super().read(size)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def archive(self, replacement=None, extra=None, omit=None):
        path = self.root / 'release.tar.gz'
        with tarfile.open(path, 'w:gz', format=tarfile.USTAR_FORMAT) as bundle:
            for name in sorted(bridge.RELEASE_MEMBERS):
                if name == omit:
                    continue
                member = tarfile.TarInfo(name)
                data = b'fake executable' if name == 'cli-proxy-api' else b'document'
                member.size = len(data)
                if name == 'cli-proxy-api' and replacement:
                    replacement(member)
                bundle.addfile(member, io.BytesIO(data) if member.isreg() else None)
            if extra:
                member = tarfile.TarInfo(extra)
                member.size = 1
                bundle.addfile(member, io.BytesIO(b'x'))
        return path

    def test_download_exact_limit_and_bounded_reads(self):
        response = Response(b'abcd', '4')
        with patch.object(bridge.urllib.request, 'urlopen', return_value=response):
            self.assertEqual(bridge.download('https://example.com/archive', 4), b'abcd')
        self.assertTrue(all(0 < size <= 5 for size in response.read_sizes))

    def test_download_rejects_oversize_even_without_honest_length(self):
        for length in [None, '2']:
            with self.subTest(length=length):
                response = Response(b'abcde', length)
                with patch.object(bridge.urllib.request, 'urlopen', return_value=response):
                    with self.assertRaisesRegex(ValueError, 'size limit'):
                        bridge.download('https://example.com/archive', 4)

    def test_download_rejects_declared_oversize_before_read(self):
        response = Response(b'abcd', '5')
        with patch.object(bridge.urllib.request, 'urlopen', return_value=response):
            with self.assertRaises(ValueError):
                bridge.download('https://example.com/archive', 4)
        self.assertEqual(response.read_sizes, [])

    def test_download_rejects_truncated_or_invalid_length(self):
        for length in ['4', '-1', 'invalid']:
            with self.subTest(length=length), patch.object(bridge.urllib.request, 'urlopen', return_value=Response(b'ab', length)):
                with self.assertRaises(ValueError):
                    bridge.download('https://example.com/archive', 4)

    def test_replaced_checksum_and_archive_cannot_replace_installed_binary(self):
        bad_archive = b'replaced release'
        digest = hashlib.sha256(bad_archive).hexdigest()
        checksums = f'{digest}  CLIProxyAPI_7.2.154_linux_amd64.tar.gz\n'.encode()
        target = self.root / 'cli-proxy-api'
        target.write_bytes(b'existing installation')
        with patch.object(bridge, 'DATA', self.root), patch.object(bridge.platform, 'machine', return_value='x86_64'), \
                patch.object(bridge, 'download', side_effect=[checksums, bad_archive]) as download, \
                patch.object(bridge, 'extract_binary') as extract:
            with self.assertRaisesRegex(ValueError, 'pinned digest'):
                bridge.install_binary()
        self.assertEqual(download.call_count, 1)
        extract.assert_not_called()
        self.assertEqual(target.read_bytes(), b'existing installation')

    def test_valid_archive_extracts_only_executable(self):
        destination = self.root / 'binary'
        bridge.extract_binary(self.archive(), destination)
        self.assertEqual(destination.read_bytes(), b'fake executable')
        self.assertEqual(destination.stat().st_mode & 0o777, 0o700)
        self.assertEqual({p.name for p in self.root.iterdir()}, {'binary', 'release.tar.gz'})

    def test_archive_rejects_unexpected_path_duplicate_or_missing_file(self):
        for name in ['../cli-proxy-api', '/cli-proxy-api', 'subdir/cli-proxy-api', './cli-proxy-api']:
            with self.subTest(name=name):
                archive = self.archive(replacement=lambda m: setattr(m, 'name', name))
                with self.assertRaises(ValueError):
                    bridge.extract_binary(archive, self.root / 'binary')
        for options in [{'extra': 'cli-proxy-api'}, {'extra': 'unexpected'}, {'omit': 'cli-proxy-api'}]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                bridge.extract_binary(self.archive(**options), self.root / 'binary')

    def test_archive_rejects_nonregular_executable(self):
        for kind in [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE]:
            def replace(member):
                member.type = kind
                member.size = 0
                member.linkname = '/tmp/target'
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                bridge.extract_binary(self.archive(replacement=replace), self.root / 'binary')

    def test_archive_rejects_declared_oversize_before_extraction(self):
        archive = self.archive()
        with patch.object(bridge, 'BINARY_MAX_BYTES', 5), \
                patch.object(tarfile.TarFile, 'extractfile') as extract:
            with self.assertRaisesRegex(ValueError, 'size limit'):
                bridge.extract_binary(archive, self.root / 'binary')
        extract.assert_not_called()
        self.assertFalse((self.root / 'binary').exists())

    def test_total_decompression_is_bounded_before_tar_parsing(self):
        archive = self.archive()
        with patch.object(bridge, 'EXPANDED_ARCHIVE_MAX_BYTES', 100), patch.object(bridge, '_extract_reviewed_tar') as parse:
            with self.assertRaisesRegex(ValueError, 'Expanded archive exceeds'):
                bridge.extract_binary(archive, self.root / 'binary')
        parse.assert_not_called()

    def test_archive_rejects_raw_extension_headers(self):
        for kind in [tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK, tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_SPARSE]:
            archive = self.archive()
            raw = gzip.decompress(archive.read_bytes())
            member = tarfile.TarInfo('././@LongLink')
            member.type = kind
            payload = b'cli-proxy-api\0' + bytes(256 * 1024)
            member.size = len(payload)
            archive.write_bytes(gzip.compress(member.tobuf(format=tarfile.GNU_FORMAT) + payload + bytes((-len(payload)) % 512) + raw))
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'Unexpected archive member'):
                bridge.extract_binary(archive, self.root / 'binary')

    def test_archive_checks_actual_extracted_size(self):
        archive = self.archive()
        with tarfile.open(archive) as bundle:
            offset = bundle.getmember('cli-proxy-api').offset_data
        raw = gzip.decompress(archive.read_bytes())
        for oversized in [False, True]:
            class BrokenStream(io.BytesIO):
                def read(self, size=-1):
                    if self.tell() == offset:
                        return b'x' * (size + 1) if oversized else b''
                    return super().read(size)
            with self.subTest(oversized=oversized), self.assertRaisesRegex(ValueError, 'length mismatch|size limit'):
                bridge._extract_reviewed_tar(BrokenStream(raw), self.root / 'binary')



if __name__ == '__main__':
    unittest.main()
