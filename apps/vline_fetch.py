"""Download the Victorian GTFS Schedule bundle and pull out the Regional Train feed.

No AppDaemon imports, so it can be tested on its own.
"""
import io
import os
import zipfile

import requests


def extract_regional(zf, folder="1"):
    """Return the bytes of a zip holding one feed of the bundle (folder "1" = Regional Train, "2" = Metro Train)."""
    names = zf.namelist()
    inner = next((n for n in names
                  if n.split("/")[0] == folder and n.lower().endswith(".zip")), None)
    if inner:
        return zf.read(inner)
    files = [n for n in names if n.split("/")[0] == folder and n.lower().endswith(".txt")]
    if not files:
        raise RuntimeError(f"The bundle has no folder '{folder}'")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
        for n in files:
            out.writestr(n.split("/")[-1], zf.read(n))
    return buf.getvalue()


def download_regional(url, tmp_dir, meta=None, headers=None, timeout=(15, 300), folder="1"):
    """Download the bundle (streamed to disk) and return (regional_zip_bytes, new_meta).

    Returns (None, meta) if the server says nothing changed (HTTP 304).
    Raises on any failure; callers keep using their saved copy.
    """
    meta = meta or {}
    req_headers = dict(headers or {})
    if meta.get("etag"):
        req_headers["If-None-Match"] = meta["etag"]
    if meta.get("last_modified"):
        req_headers["If-Modified-Since"] = meta["last_modified"]

    with requests.get(url, headers=req_headers, stream=True, timeout=timeout) as r:
        if r.status_code == 304:
            return None, meta
        if r.status_code in (401, 403):
            raise PermissionError(
                f"HTTP {r.status_code}: the download appears to need a login or API key")
        r.raise_for_status()
        part = os.path.join(tmp_dir, "gtfs_download.zip.part")
        try:
            with open(part, "wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
            try:
                with zipfile.ZipFile(part) as zf:
                    data = extract_regional(zf, folder)
            except zipfile.BadZipFile:
                raise RuntimeError("The download was not a zip file "
                                   "(possibly a login or error page)") from None
        finally:
            try:
                os.remove(part)
            except OSError:
                pass
        new_meta = {k: v for k, v in {
            "etag": r.headers.get("ETag"),
            "last_modified": r.headers.get("Last-Modified"),
        }.items() if v}
    return data, new_meta
