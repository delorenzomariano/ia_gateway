import pytest

from ia_gateway.chat.validation import sanitize_llm_text
from ia_gateway.llm.base import LLMInvalidResponseError


def test_removes_control_characters_but_keeps_newlines_and_tabs():
    raw = "Hola\x00\x07 mundo\n\tlinea\x1b[31m"
    assert sanitize_llm_text(raw) == "Hola mundo\n\tlinea[31m"


def test_strips_surrounding_whitespace():
    assert sanitize_llm_text("\n  hola  \n") == "hola"


def test_empty_text_is_invalid():
    with pytest.raises(LLMInvalidResponseError):
        sanitize_llm_text(" \x00 \n")


def test_empty_text_is_allowed_when_there_were_tool_calls():
    assert sanitize_llm_text("", had_tool_calls=True) == ""
