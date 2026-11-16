"""Unit tests for the pure processing function (no AWS needed)."""

import hashlib

from app.processing import process_file_content


def test_empty_file():
    assert process_file_content(b"") == {
        "size_bytes": 0,
        "line_count": 0,
        "word_count": 0,
        "sha256": hashlib.sha256(b"").hexdigest(),
    }


def test_single_line_without_newline():
    result = process_file_content(b"hello world")
    assert result["size_bytes"] == 11
    assert result["line_count"] == 1
    assert result["word_count"] == 2
    assert result["sha256"] == hashlib.sha256(b"hello world").hexdigest()


def test_multiline_with_trailing_newline():
    data = b"one two\nthree four five\nsix\n"
    result = process_file_content(data)
    assert result["size_bytes"] == len(data)
    assert result["line_count"] == 3  # trailing newline adds no extra line
    assert result["word_count"] == 6


def test_blank_lines_count_as_lines_but_not_words():
    result = process_file_content(b"a\n\nb\n")
    assert result["line_count"] == 3
    assert result["word_count"] == 2


def test_crlf_line_endings():
    result = process_file_content(b"a\r\nb\r\n")
    assert result["line_count"] == 2
    assert result["word_count"] == 2


def test_unicode_content():
    data = "héllo wörld\n日本語 テスト\n".encode("utf-8")
    result = process_file_content(data)
    assert result["size_bytes"] == len(data)
    assert result["line_count"] == 2
    assert result["word_count"] == 4


def test_largeish_file():
    data = ("the quick brown fox jumps over the lazy dog\n" * 5000).encode()
    assert len(data) > 200_000
    result = process_file_content(data)
    assert result["size_bytes"] == len(data)
    assert result["line_count"] == 5000
    assert result["word_count"] == 9 * 5000
    assert result["sha256"] == hashlib.sha256(data).hexdigest()


def test_binary_bytes_never_crash():
    data = bytes(range(256)) * 100
    result = process_file_content(data)
    assert result["size_bytes"] == len(data)
    assert result["sha256"] == hashlib.sha256(data).hexdigest()
    assert result["line_count"] >= 0
    assert result["word_count"] >= 0


def test_whitespace_only():
    result = process_file_content(b"   \n\t\n")
    assert result["line_count"] == 2
    assert result["word_count"] == 0
