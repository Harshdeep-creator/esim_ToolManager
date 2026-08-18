"""Download + extract portable tool archives (Windows-friendly, no admin)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from urllib.error import URLError
from urllib.request import Request, urlopen

from esim_toolmanager import __version__
from esim_toolmanager.utils.logger import get_logger

logger = get_logger("archive")

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 "
    f"esim-toolmanager/{__version__}"
)

_MAGIC = {
    ".7z": b"7z\xbc\xaf'\x1c",
    ".zip": b"PK",
}


def archive_urls_from_spec(spec: Dict) -> List[str]:
    """Primary URL plus optional mirrors, de-duplicated, order preserved."""
    urls: List[str] = []
    for item in [spec.get("url"), *(spec.get("urls") or [])]:
        if item and str(item) not in urls:
            urls.append(str(item))
    return urls


def is_valid_archive(path: Path) -> bool:
    """True if *path* looks like a real .7z/.zip, not an HTML error page."""
    if not path.exists() or not path.is_file():
        return False
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size < 1024:
        return False
    magic = _MAGIC.get(path.suffix.lower())
    try:
        with path.open("rb") as fh:
            head = fh.read(8)
    except OSError:
        return False
    if head.lstrip().startswith(b"<") or head.startswith(b"<!") or b"<html" in head.lower():
        return False
    if magic:
        return head.startswith(magic)
    return True


def download_url(url: str, destination: Path, timeout: int = 300) -> Path:
    """Download a file, following redirects (SourceForge-friendly)."""
    return download_first_url([url], destination, timeout=timeout)


def download_first_url(
    urls: Sequence[str], destination: Path, timeout: int = 300
) -> Path:
    """Try each URL until a valid archive is stored at *destination*."""
    cleaned = [u for u in urls if u]
    if not cleaned:
        raise URLError("No download URLs provided")

    destination.parent.mkdir(parents=True, exist_ok=True)
    if is_valid_archive(destination):
        logger.info("Using cached archive: %s", destination)
        return destination
    if destination.exists():
        logger.warning("Removing invalid cached file: %s", destination)
        destination.unlink(missing_ok=True)

    errors: List[str] = []
    for url in cleaned:
        logger.info("Downloading archive: %s", url)
        try:
            _download_one(url, destination, timeout=timeout)
            if is_valid_archive(destination):
                logger.info(
                    "Saved %s (%s bytes)", destination, destination.stat().st_size
                )
                return destination
            err = f"{url}: downloaded file is not a valid archive (HTML/truncated)"
            logger.warning(err)
            errors.append(err)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Download failed for %s: %s", url, exc)
            errors.append(f"{url}: {exc}")
        destination.unlink(missing_ok=True)
        part = destination.with_name(destination.name + ".part")
        part.unlink(missing_ok=True)

    raise URLError("All archive URLs failed: " + " | ".join(errors[:4]))


def _download_one(url: str, destination: Path, timeout: int) -> None:
    tmp = destination.with_name(destination.name + ".part")
    tmp.unlink(missing_ok=True)
    urllib_exc: Optional[Exception] = None
    try:
        _urllib_download(url, tmp, timeout)
        tmp.replace(destination)
        return
    except Exception as exc:  # noqa: BLE001
        urllib_exc = exc
        logger.warning("urllib download failed (%s); trying curl fallback", exc)
        tmp.unlink(missing_ok=True)

    curl = shutil.which("curl") or shutil.which("curl.exe")
    if not curl:
        raise URLError(
            f"Download failed and curl is unavailable: {url} ({urllib_exc})"
        )
    _curl_download(curl, url, tmp, timeout)
    tmp.replace(destination)


def _urllib_download(url: str, destination: Path, timeout: int) -> None:
    req = Request(
        url,
        headers={
            "User-Agent": BROWSER_UA,
            "Accept": "*/*",
        },
    )
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310
        with destination.open("wb") as fh:
            while True:
                chunk = resp.read(1024 * 64)
                if not chunk:
                    break
                fh.write(chunk)


def _curl_download(curl: str, url: str, destination: Path, timeout: int) -> None:
    cmd = [
        curl,
        "-fL",
        "--retry",
        "3",
        "--retry-delay",
        "2",
        "--connect-timeout",
        "30",
        "-A",
        BROWSER_UA,
        "-o",
        str(destination),
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0 or not destination.exists() or destination.stat().st_size < 1000:
        raise URLError(
            f"curl download failed (code {result.returncode}): "
            f"{(result.stderr or result.stdout or '')[:300]}"
        )


def extract_archive(archive_path: Path, dest_dir: Path) -> Path:
    """Extract .zip or .7z into dest_dir; return dest_dir."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix = archive_path.suffix.lower()
    if suffix == ".zip":
        import zipfile

        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(dest_dir)
        return dest_dir
    if suffix == ".7z":
        try:
            import py7zr
        except ImportError as exc:
            raise RuntimeError(
                "Extracting .7z requires py7zr. Install with: python -m pip install py7zr"
            ) from exc
        with py7zr.SevenZipFile(archive_path, mode="r") as zf:
            zf.extractall(path=dest_dir)
        return dest_dir
    raise RuntimeError(f"Unsupported archive type: {archive_path.suffix}")


def find_under(root: Path, relative: str) -> Optional[Path]:
    """Resolve a relative path, or search for the basename under root."""
    direct = root / relative
    if direct.exists():
        return direct
    name = Path(relative).name
    for path in root.rglob(name):
        if path.is_file():
            return path
    return None


def cleanup_dir(path: Path) -> None:
    if path.exists() and path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
