"""Pure file-processing logic: no AWS calls, fully unit-testable."""

import hashlib

__all__ = ["process_file_content"]


def process_file_content(data: bytes) -> dict:
    """Compute size, line count, word count and SHA-256 of file bytes.

    * ``size_bytes``: length of the raw bytes.
    * ``line_count``: number of text lines (``str.splitlines`` semantics, so a
      trailing newline does not add an extra line; empty file -> 0).
    * ``word_count``: whitespace-separated tokens (``str.split`` semantics).
    * ``sha256``: hex digest of the raw bytes.

    Decoding is UTF-8 with ``errors="replace"`` so arbitrary bytes never crash
    the worker; undecodable bytes become U+FFFD and still count towards size.
    """
    sha256 = hashlib.sha256(data).hexdigest()
    text = data.decode("utf-8", errors="replace")
    return {
        "size_bytes": len(data),
        "line_count": len(text.splitlines()),
        "word_count": len(text.split()),
        "sha256": sha256,
    }
