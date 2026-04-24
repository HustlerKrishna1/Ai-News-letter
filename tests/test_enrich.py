"""Tests for full-text extraction."""
from __future__ import annotations

from modules.enrich import extract_text


SAMPLE = """
<!DOCTYPE html>
<html><head><title>Demo</title>
<script>var nav = "junk ignore this";</script>
<style>.x{color:red}</style>
</head><body>
  <nav><p>Short boilerplate nav link</p></nav>
  <header><p>Header boilerplate not article text really</p></header>
  <main>
    <p>This is the first real body paragraph and it is definitely long enough to
    pass the minimum character threshold we have configured for paragraph
    density so it should be picked up by the extractor without trouble.</p>
    <p>Short.</p>
    <p>A second substantial paragraph with more than sixty characters of actual
    content to prove that the extractor concatenates multiple body paragraphs
    in document order rather than dropping everything after the first match.</p>
  </main>
  <footer><p>Footer boilerplate ignore this short paragraph</p></footer>
</body></html>
"""


def test_extract_text_pulls_main_body_paragraphs():
    out = extract_text(SAMPLE, min_para_chars=60)
    assert "first real body paragraph" in out
    assert "second substantial paragraph" in out
    # boilerplate excluded
    assert "boilerplate" not in out
    assert "junk ignore this" not in out  # script body excluded


def test_extract_text_handles_empty_input():
    assert extract_text("") == ""


def test_extract_text_respects_max_chars():
    long_para = "<html><body><p>" + ("word " * 2000) + "</p></body></html>"
    out = extract_text(long_para, max_chars=500)
    assert len(out) <= 500
