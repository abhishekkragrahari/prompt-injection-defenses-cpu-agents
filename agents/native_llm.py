"""In-process AgentDojo LLM element that uses each model's native tool-call format.

Why this exists: AgentDojo's built-in LocalLLM forces one prompted
`<function=...>` format on every model, calls an HTTP server, and draws a fresh
random seed per request. In Stage 1 that format produced malformed calls from
Phi-4-mini. This element instead:
  * renders prompts with the chat template embedded in each GGUF file,
  * parses the model's native tool-call syntax,
  * runs llama.cpp in-process with a fixed seed and greedy decoding,
  * records per-call latency, token counts and parse failures in `extra_args`.

Format sources (see docs in each dialect):
  Qwen3  - template embedded in the GGUF (tokenizer.chat_template).
  Phi-4-mini - template embedded in the GGUF plus the model card's
    "Tool-enabled function-calling format". Microsoft does not document how
    tool *results* are returned; we use the dedicated <|tool_response|> token
    (verified empirically in Stage 2 to yield correct final answers).
"""

from __future__ import annotations

import datetime
import json
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

import jinja2
from pydantic import ValidationError
from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement
from agentdojo.functions_runtime import EmptyEnv, Env, Function, FunctionCall, FunctionsRuntime
from agentdojo.types import ChatAssistantMessage, ChatMessage, get_text_content_as_str, text_content_block_from_string


FIXED_TEMPLATE_DATE = datetime.date(2026, 9, 27)


def _tojson(value) -> str:
    # HF templates expect json.dumps semantics (no HTML escaping), unlike jinja2's builtin.
    return json.dumps(value, ensure_ascii=False)


def _compile(template: str) -> jinja2.Template:
    # HF's `{% generation %}` tag only marks assistant spans for training; it has no rendering effect.
    template = re.sub(r"{%-?\s*(end)?generation\s*-?%}", "", template)
    env = jinja2.Environment(loader=jinja2.BaseLoader(), trim_blocks=True, lstrip_blocks=True)
    env.filters["tojson"] = _tojson
    # Some templates (e.g. SmolLM3) insert "today's date"; fix it so prompts are identical across runs.
    env.globals["strftime_now"] = lambda fmt: FIXED_TEMPLATE_DATE.strftime(fmt)
    return env.from_string(template)


def _make_call(obj) -> FunctionCall:
    """Build a FunctionCall from a {"name", "arguments"} object. Arguments may be a dict or, following the
    OpenAI API convention that some models reproduce, a JSON-encoded string."""
    args = obj.get("arguments") or {}
    if isinstance(args, str):
        args = json.loads(args) if args.strip() else {}
    return FunctionCall(function=obj["name"], args=args)


def _content(message: ChatMessage) -> str:
    content = message.get("content")
    return "" if content is None else get_text_content_as_str(content)


@dataclass
class ParseResult:
    content: str
    calls: list[FunctionCall]
    parse_error: str | None = None


@dataclass
class Dialect:
    """Converts AgentDojo messages to a model prompt and parses model output."""

    template: jinja2.Template
    stop: list[str] = field(default_factory=list)

    def render(self, messages: Sequence[ChatMessage], tools: Sequence[Function]) -> str:
        raise NotImplementedError

    def parse(self, text: str) -> ParseResult:
        raise NotImplementedError


class HermesDialect(Dialect):
    """Hermes-style format shared by Qwen3, Granite 4.0 and SmolLM3: tools listed in the system turn,
    calls as <tool_call>{"name","arguments"}</tool_call>, results rendered by the model's own template."""

    tools_var = "tools"
    template_kwargs: dict = {}
    inline_tool_calls = False  # True when the template ignores `tool_calls` and expects them in the content
    _call_re = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)

    def render(self, messages, tools):
        tool_specs = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                        "parameters": t.parameters.model_json_schema()}}
                      for t in tools]
        msgs = []
        for m in messages:
            if m["role"] == "assistant":
                calls = [{"name": c.function, "arguments": dict(c.args)} for c in (m.get("tool_calls") or [])]
                content = _content(m)
                if self.inline_tool_calls and calls:
                    blocks = [f"<tool_call>\n{_tojson(c)}\n</tool_call>" for c in calls]
                    content = "\n".join(([content] if content else []) + blocks)
                    calls = []
                msgs.append({"role": "assistant", "content": content, "tool_calls": calls})
            elif m["role"] == "tool":
                msgs.append({"role": "tool", "content": _tool_result_text(m)})
            else:
                msgs.append({"role": m["role"], "content": _content(m)})
        return self.template.render(messages=msgs, add_generation_prompt=True,
                                    **{self.tools_var: tool_specs or None}, **self.template_kwargs)

    def parse(self, text):
        calls, errors = [], []
        for raw in self._call_re.findall(text):
            try:
                calls.append(_make_call(json.loads(raw)))
            except (json.JSONDecodeError, KeyError, TypeError, AttributeError, ValidationError) as e:
                errors.append(f"{type(e).__name__}: {raw[:200]}")
        if "<tool_call>" in text and not calls and not errors:
            errors.append("unterminated <tool_call>")
        content = self._call_re.sub("", text).strip()
        return ParseResult(content, calls, "; ".join(errors) or None)


class QwenDialect(HermesDialect):
    """Qwen3-Instruct-2507 (non-thinking only)."""


class GraniteDialect(HermesDialect):
    """IBM Granite 4.0."""


class SmolLM3Dialect(HermesDialect):
    """SmolLM3: tools passed as `xml_tools`; thinking disabled to match the non-thinking Qwen3 instruct model."""

    tools_var = "xml_tools"
    template_kwargs = {"enable_thinking": False}
    inline_tool_calls = True


class PhiDialect(Dialect):
    """Phi-4-mini: tools as JSON inside <|tool|>..<|/tool|> in the system turn; calls as a JSON list
    [{"name","arguments"}]; results returned in a <|tool_response|> turn."""

    def render(self, messages, tools):
        tool_specs = [{"name": t.name, "description": t.description,
                       "parameters": t.parameters.model_json_schema().get("properties", {})} for t in tools]
        msgs = []
        for m in messages:
            if m["role"] == "system":
                msg = {"role": "system", "content": _content(m)}
                if tool_specs:
                    msg["tools"] = json.dumps(tool_specs, ensure_ascii=False)
                msgs.append(msg)
            elif m["role"] == "assistant":
                calls = m.get("tool_calls") or []
                text = _content(m)
                if calls:
                    text = json.dumps([{"name": c.function, "arguments": dict(c.args)} for c in calls],
                                      ensure_ascii=False)
                msgs.append({"role": "assistant", "content": text})
            elif m["role"] == "tool":
                msgs.append({"role": "tool_response", "content": _tool_result_text(m)})
            else:
                msgs.append({"role": m["role"], "content": _content(m)})
        return self.template.render(messages=msgs, add_generation_prompt=True, eos_token="")

    def parse(self, text):
        stripped = text.replace("<|tool_call|>", "").replace("<|/tool_call|>", "").strip()
        start = stripped.find("[")
        if start == -1 or not re.match(r"\[\s*\{\s*\"name\"", stripped[start:]):
            return ParseResult(text.strip(), [])
        try:
            obj, end = json.JSONDecoder().raw_decode(stripped[start:])
            calls = [_make_call(c) for c in obj]
            content = (stripped[:start] + stripped[start + end:]).strip()
            return ParseResult(content, calls)
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError, ValidationError) as e:
            return ParseResult(text.strip(), [], f"{type(e).__name__}: {stripped[start:start + 200]}")


DIALECTS = {"qwen3": (QwenDialect, ["<|im_end|>"]), "phi4-mini": (PhiDialect, ["<|end|>"]),
            "granite4": (GraniteDialect, ["<|end_of_text|>"]), "smollm3": (SmolLM3Dialect, ["<|im_end|>"])}


def _tool_result_text(m: ChatMessage) -> str:
    if m.get("error"):
        return json.dumps({"error": m["error"]})
    text = _content(m)
    return "Success" if text == "None" else text


class NativeLlamaCppLLM(BasePipelineElement):
    """AgentDojo pipeline element backed by an in-process llama.cpp model."""

    def __init__(self, llama, dialect_name: str, seed: int = 0, temperature: float = 0.0,
                 max_tokens: int = 1024, name: str | None = None):
        cls, stop = DIALECTS[dialect_name]
        template = llama.metadata["tokenizer.chat_template"]
        self.dialect: Dialect = cls(template=_compile(template), stop=stop)
        self.llama = llama
        self.seed = seed
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.name = name or dialect_name
        self.call_log: list[dict] = []  # one record per model call; read by the experiment runner

    def reset_episode(self) -> None:
        """Clear the KV cache and the call log so no state carries across episodes."""
        self.llama.reset()
        self.call_log = []

    def complete(self, messages: Sequence[ChatMessage], tools: Sequence[Function], purpose: str = "agent"):
        """Render `messages` with `tools` in the native format, generate greedily, log the call, return text."""
        prompt = self.dialect.render(messages, list(tools))
        t0 = time.perf_counter()
        out = self.llama.create_completion(prompt, max_tokens=self.max_tokens, temperature=self.temperature,
                                           seed=self.seed, stop=self.dialect.stop)
        latency = time.perf_counter() - t0
        text = out["choices"][0]["text"]
        record = {
            "purpose": purpose,
            "latency_s": round(latency, 3),
            "prompt_tokens": out["usage"]["prompt_tokens"],
            "completion_tokens": out["usage"]["completion_tokens"],
            "finish_reason": out["choices"][0]["finish_reason"],
            "n_tool_calls": 0,
            "parse_error": None,
            "raw_output": text,
        }
        self.call_log.append(record)
        return text, record

    def query(self, query: str, runtime: FunctionsRuntime, env: Env = EmptyEnv(),
              messages: Sequence[ChatMessage] = [], extra_args: dict = {}):
        text, record = self.complete(messages, list(runtime.functions.values()))
        parsed = self.dialect.parse(text)
        record["n_tool_calls"] = len(parsed.calls)
        record["parse_error"] = parsed.parse_error
        message = ChatAssistantMessage(role="assistant", content=[text_content_block_from_string(parsed.content)],
                                       tool_calls=parsed.calls or None)
        return query, runtime, env, [*messages, message], extra_args
