"""Archive download validation and mirror fallback tests (offline)."""

from pathlib import Path
from urllib.error import URLError

import pytest

from esim_toolmanager.core.archive_install import (
    archive_urls_from_spec,
    download_first_url,
    is_valid_archive,
)


SEVEN_Z_BYTES = b"7z\xbc\xaf'\x1c" + b"\x00" * 2048
HTML_BYTES = b"<!DOCTYPE html><html>sourceforge interstitial</html>" + b" " * 2048


class _FakeResp:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            chunk = self._data[self._pos :]
            self._pos = len(self._data)
            return chunk
        chunk = self._data[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *args) -> bool:
        return False


def test_is_valid_archive_rejects_html(tmp_path: Path):
    html = tmp_path / "ngspice-46_64.7z"
    html.write_bytes(HTML_BYTES)
    assert is_valid_archive(html) is False
    tiny = tmp_path / "tiny.7z"
    tiny.write_bytes(b"7z")
    assert is_valid_archive(tiny) is False
    good = tmp_path / "good.7z"
    good.write_bytes(SEVEN_Z_BYTES)
    assert is_valid_archive(good) is True


def test_archive_urls_from_spec_dedupes():
    urls = archive_urls_from_spec(
        {
            "url": "https://example.com/a.7z",
            "urls": [
                "https://example.com/a.7z",
                "https://example.com/b.7z",
            ],
        }
    )
    assert urls == ["https://example.com/a.7z", "https://example.com/b.7z"]


def test_download_skips_html_and_uses_next_url(tmp_path: Path, monkeypatch):
    dest = tmp_path / "ngspice-46_64.7z"
    payloads = [HTML_BYTES, SEVEN_Z_BYTES]
    calls = {"n": 0}

    def fake_urlopen(req, timeout=0):  # noqa: ARG001
        idx = min(calls["n"], len(payloads) - 1)
        calls["n"] += 1
        return _FakeResp(payloads[idx])

    monkeypatch.setattr("esim_toolmanager.core.archive_install.urlopen", fake_urlopen)
    monkeypatch.setattr("esim_toolmanager.core.archive_install.shutil.which", lambda *_a, **_k: None)

    result = download_first_url(
        ["https://example.com/interstitial", "https://example.com/real.7z"],
        dest,
    )
    assert result == dest
    assert is_valid_archive(dest)
    assert calls["n"] == 2


def test_download_rejects_cached_html(tmp_path: Path, monkeypatch):
    dest = tmp_path / "ngspice-46_64.7z"
    dest.write_bytes(HTML_BYTES)

    def fake_urlopen(req, timeout=0):  # noqa: ARG001
        return _FakeResp(SEVEN_Z_BYTES)

    monkeypatch.setattr("esim_toolmanager.core.archive_install.urlopen", fake_urlopen)
    monkeypatch.setattr("esim_toolmanager.core.archive_install.shutil.which", lambda *_a, **_k: None)

    download_first_url(["https://example.com/real.7z"], dest)
    assert is_valid_archive(dest)


def test_download_all_urls_fail(tmp_path: Path, monkeypatch):
    dest = tmp_path / "ngspice-46_64.7z"

    def fake_urlopen(req, timeout=0):  # noqa: ARG001
        raise URLError("blocked")

    monkeypatch.setattr("esim_toolmanager.core.archive_install.urlopen", fake_urlopen)
    monkeypatch.setattr("esim_toolmanager.core.archive_install.shutil.which", lambda *_a, **_k: None)

    with pytest.raises(URLError, match="All archive URLs failed"):
        download_first_url(["https://example.com/a.7z"], dest)
    assert not dest.exists()
