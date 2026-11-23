"""One LLM call per question. Bring your own key: Anthropic (default), Gemini or Ollama."""

from __future__ import annotations

import json
import os
import urllib.request

SYSTEM = """You explain how software works, using ONLY the evidence given (file tree, \
symbols, source excerpts, binary strings/imports, HTTP headers, JS bundles).
Write a concise Markdown report in the same language as the question, with these sections:
1. What it is (2-3 lines)
2. How it works (answer the question step by step)
3. Evidence (bullet list; every claim points to a source exactly as labeled in the \
context: path, path:Lnn, binary@0xOFFSET or URL)
4. Confidence (high/medium/low, and why)
5. Gaps (what the evidence does not show, and which file/offset/URL to look at next)
Never invent file names, functions or endpoints that are not in the evidence."""

# Providers whose server-side refusal fallback is supported (see Anthropic docs).
FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5",
                   "claude-fable-5-1", "claude-fable-5-2"}

DEFAULT_MODELS = {"anthropic": "claude-sonnet-5-5", "gemini": "gemini-2.5-flash",
                  "ollama": "llama3.1"}


def user_prompt(context: str, question: str) -> str:
    return f"<evidence>\n{context}\n</evidence>\n\nQuestion: {question}"


def count_tokens_exact(model: str, context: str, question: str) -> int | None:
    """Exact input count from Anthropic's count_tokens endpoint (free); None if unavailable."""
    try:
        import anthropic

        r = anthropic.Anthropic().messages.count_tokens(
            model=model, system=SYSTEM,
            messages=[{"role": "user", "content": user_prompt(context, question)}],
        )
        return r.input_tokens
    except Exception:  # noqa: BLE001 - estimate stays as fallback
        return None


def ask(provider: str, model: str, context: str, question: str, max_output: int) -> tuple[str, int, int]:
    """Returns (markdown, input_tokens, output_tokens)."""
    prompt = user_prompt(context, question)
    if provider == "anthropic":
        return _anthropic(model, prompt, max_output)
    if provider == "gemini":
        return _gemini(model, prompt, max_output)
    if provider == "ollama":
        return _ollama(model, prompt, max_output)
    raise ValueError(f"provider desconhecido: {provider}")


def _anthropic(model: str, prompt: str, max_output: int) -> tuple[str, int, int]:
    import anthropic

    client = anthropic.Anthropic()
    kwargs = dict(model=model, max_tokens=max_output, system=SYSTEM,
                  messages=[{"role": "user", "content": prompt}])
    if model in FALLBACK_MODELS:
        # On a safety decline the API retries on a fallback model inside the same call.
        r = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"],
                                        fallbacks="default", **kwargs)
    else:
        r = client.messages.create(**kwargs)
    if r.stop_reason == "refusal":
        raise RuntimeError("o modelo recusou a pergunta (stop_reason=refusal)")
    text = "".join(b.text for b in r.content if b.type == "text")
    if r.stop_reason == "max_tokens":
        text += "\n\n_(resposta cortada: aumente --max-output)_"
    return text, r.usage.input_tokens, r.usage.output_tokens


def _post(url: str, body: dict, headers: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)


def _gemini(model: str, prompt: str, max_output: int) -> tuple[str, int, int]:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("defina GEMINI_API_KEY")
    r = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
              {"systemInstruction": {"parts": [{"text": SYSTEM}]},
               "contents": [{"role": "user", "parts": [{"text": prompt}]}],
               "generationConfig": {"maxOutputTokens": max_output}},
              {"x-goog-api-key": key})
    parts = r["candidates"][0]["content"]["parts"]
    u = r.get("usageMetadata", {})
    return "".join(p.get("text", "") for p in parts), u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0)


def _ollama(model: str, prompt: str, max_output: int) -> tuple[str, int, int]:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    r = _post(f"{host}/api/chat",
              {"model": model, "stream": False, "options": {"num_predict": max_output},
               "messages": [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": prompt}]}, {})
    return r["message"]["content"], r.get("prompt_eval_count", 0), r.get("eval_count", 0)
