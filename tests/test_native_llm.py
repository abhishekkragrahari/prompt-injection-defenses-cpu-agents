"""Unit tests for native tool-call dialects (no generation; templates read from the GGUF files)."""
from pathlib import Path

import pytest
from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime, make_function
from agentdojo.types import text_content_block_from_string
from llama_cpp import Llama

from agents.native_llm import PhiDialect, QwenDialect, _compile

ROOT = Path(__file__).resolve().parents[1]


def _template(fname):
    llm = Llama(model_path=str(ROOT / "models" / fname), vocab_only=True, verbose=False)
    return _compile(llm.metadata["tokenizer.chat_template"])


@pytest.fixture(scope="module")
def qwen():
    return QwenDialect(template=_template("Qwen3-4B-Instruct-2507-Q4_K_M.gguf"))


@pytest.fixture(scope="module")
def phi():
    return PhiDialect(template=_template("Phi-4-mini-instruct-Q4_K_M.gguf"))


def send_money(recipient: str, amount: float) -> str:
    """Send money to a recipient.

    :param recipient: IBAN of the recipient.
    :param amount: Amount to send.
    """
    return "ok"


TOOLS = list(FunctionsRuntime([make_function(send_money)]).functions.values())
CALL = FunctionCall(function="send_money", args={"recipient": "DE00", "amount": 5.0})
MESSAGES = [
    {"role": "system", "content": [text_content_block_from_string("Be helpful.")]},
    {"role": "user", "content": [text_content_block_from_string("Pay DE00 5 euros.")]},
    {"role": "assistant", "content": [text_content_block_from_string("")], "tool_calls": [CALL]},
    {"role": "tool", "content": [text_content_block_from_string("ok")], "tool_call": CALL,
     "tool_call_id": None, "error": None},
]


def test_qwen_render_contains_native_markers(qwen):
    p = qwen.render(MESSAGES, TOOLS)
    assert "<tools>" in p and '"name": "send_money"' in p
    assert '<tool_call>\n{"name": "send_money", "arguments": {"recipient": "DE00", "amount": 5.0}}' in p
    assert "<tool_response>\nok\n</tool_response>" in p
    assert p.endswith("<|im_start|>assistant\n")


def test_qwen_parse_calls_and_errors(qwen):
    r = qwen.parse('ok <tool_call>\n{"name": "send_money", "arguments": {"recipient": "X", "amount": 1}}\n</tool_call>')
    assert [c.function for c in r.calls] == ["send_money"] and r.content == "ok" and r.parse_error is None
    bad = qwen.parse("<tool_call>{not json}</tool_call>")
    assert bad.calls == [] and bad.parse_error
    assert qwen.parse("Paris.").calls == []


def test_phi_render_contains_native_markers(phi):
    p = phi.render(MESSAGES, TOOLS)
    assert p.startswith("<|system|>Be helpful.<|tool|>[") and "<|/tool|><|end|>" in p
    assert '<|assistant|>[{"name": "send_money", "arguments": {"recipient": "DE00", "amount": 5.0}}]<|end|>' in p
    assert "<|tool_response|>ok<|end|>" in p
    assert p.endswith("<|assistant|>")


def test_phi_parse_calls_and_plain_text(phi):
    r = phi.parse('[{"name": "send_money", "arguments": {"recipient": "X", "amount": 1}}]')
    assert r.calls[0].args["recipient"] == "X" and r.parse_error is None
    assert phi.parse("The capital is Paris [citation].").calls == []
    bad = phi.parse('[{"name": "send_money", "arguments": {')
    assert bad.calls == [] and bad.parse_error


def test_string_encoded_arguments_and_invalid_args(qwen, phi):
    r = qwen.parse('<tool_call>{"name": "send_money", "arguments": "{\\"recipient\\": \\"X\\", \\"amount\\": 1}"}</tool_call>')
    assert r.calls[0].args == {"recipient": "X", "amount": 1} and r.parse_error is None
    bad = qwen.parse('<tool_call>{"name": "send_money", "arguments": [1, 2]}</tool_call>')
    assert bad.calls == [] and bad.parse_error
    r2 = phi.parse('[{"name": "send_money", "arguments": "{\\"recipient\\": \\"X\\"}"}]')
    assert r2.calls[0].args == {"recipient": "X"}
