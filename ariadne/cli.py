"""ariadne <target> "question" — understand how a piece of software works, on a token budget."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .budget import PROMPT_OVERHEAD, condense, cost_usd, estimate_tokens, parse_budget, render
from .extract import extract, kind_of
from .llm import DEFAULT_MODELS, ask, count_tokens_exact


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ariadne", description=__doc__)
    ap.add_argument("target", help="pasta local, arquivo/binário ou URL (http/https)")
    ap.add_argument("question", help='pergunta, ex.: "como funciona o login?"')
    ap.add_argument("--budget", default="20k", help="teto de tokens de entrada (padrão 20k)")
    ap.add_argument("--max-output", type=int, default=4000, help="teto de tokens de saída")
    ap.add_argument("--provider", choices=["anthropic", "gemini", "ollama"], default="anthropic")
    ap.add_argument("--model", help="modelo (padrão: claude-sonnet-5-5 na Anthropic)")
    ap.add_argument("--dry-run", action="store_true", help="não chama modelo: mostra contexto e estimativa")
    ap.add_argument("--version", action="version", version=f"ariadne-thread {__version__}")
    a = ap.parse_args(argv)

    try:
        budget = parse_budget(a.budget)
        kind = kind_of(a.target)
    except (ValueError, FileNotFoundError) as e:
        ap.error(str(e))
    model = a.model or DEFAULT_MODELS[a.provider]

    log(f">> alvo: {a.target} ({kind}) — extraindo localmente (0 tokens)…")
    try:
        chunks = extract(a.target)
    except OSError as e:  # network/IO errors on the target itself
        log(f"erro ao ler o alvo: {e}")
        return 1
    raw = sum(estimate_tokens(c.text) for c in chunks)
    kept, dropped = condense(chunks, budget, a.question)
    context = render(kept)
    est_in = estimate_tokens(context) + estimate_tokens(a.question) + PROMPT_OVERHEAD

    log(f"   evidência bruta: ≈{raw:,} tokens em {len(chunks)} trechos")
    log(f"   após condensar: ≈{est_in:,} tokens com o prompt, {len(kept)} trechos ({dropped} descartados) — budget {budget:,}")
    worst = cost_usd(model, est_in, a.max_output)
    if worst is not None:
        log(f"   custo máximo estimado ({model}): ≈US$ {worst:.4f} (entrada + até {a.max_output} de saída)")

    if a.dry_run:
        print(f"# Contexto condensado (dry-run)\n\nPergunta: {a.question}\n\n{context}")
        log("   dry-run: nenhum modelo foi chamado.")
        return 0

    if a.provider == "anthropic":
        exact = count_tokens_exact(model, context, a.question)
        if exact:
            log(f"   contagem exata (count_tokens): {exact:,} tokens de entrada")
    log(f"   chamando {a.provider}/{model}…")
    try:
        report, tin, tout = ask(a.provider, model, context, a.question, a.max_output)
    except Exception as e:  # noqa: BLE001 - show provider/auth errors plainly
        log(f"erro do provedor: {e}")
        return 2
    print(report)
    real = cost_usd(model, tin, tout)
    log(f">> uso real: {tin:,} entrada + {tout:,} saída"
        + (f" = US$ {real:.4f}" if real is not None else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
