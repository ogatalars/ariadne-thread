# Ariadne

> O fio que leva para fora do labirinto: entenda como um software funciona perguntando a um LLM, gastando o mínimo de tokens.

```
ariadne <alvo> "como funciona X?"
```

O `<alvo>` pode ser uma **pasta local**, um **binário/arquivo** ou a **URL** de uma página/app web. A Ariadne extrai evidências localmente (custo zero), condensa tudo até caber num **orçamento de tokens**, mostra a estimativa de custo **antes** e o uso real **depois** de uma única chamada ao modelo, e devolve um relatório em Markdown com ponteiros de evidência (`arquivo:Lnn`, `binário 0xOFFSET`, URL) e nível de confiança.

[![ci](https://github.com/ogatalars/ariadne-thread/actions/workflows/ci.yml/badge.svg)](https://github.com/ogatalars/ariadne-thread/actions/workflows/ci.yml)

## Quickstart (30 segundos)

Precisa só do [uv](https://docs.astral.sh/uv/). Nada é publicado no PyPI: roda direto do GitHub.

```bash
# 1. Demo grátis: não chama modelo nenhum, mostra o contexto e a estimativa
uvx --from git+https://github.com/ogatalars/ariadne-thread ariadne . "como funciona o login?" --dry-run

# 2. De verdade, com a sua chave (Claude é o padrão)
export ANTHROPIC_API_KEY=...
uvx --from git+https://github.com/ogatalars/ariadne-thread ariadne ./meu-projeto "como funciona o checkout?" --budget 20k
```

Outros alvos e provedores:

```bash
ariadne /usr/bin/curl "como ele negocia TLS?" --budget 10k        # binário
ariadne https://exemplo.com "que APIs o front chama?" --dry-run    # página web
ariadne . "onde fica o cache?" --provider gemini --model gemini-2.5-flash   # GEMINI_API_KEY
ariadne . "onde fica o cache?" --provider ollama --model llama3.1           # local, sem custo
```

| Flag | Padrão | O que faz |
|---|---|---|
| `--budget` | `20k` | Teto de tokens de **entrada** (aceita `8000`, `20k`, `1m`) |
| `--max-output` | `4000` | Teto de tokens de **saída** |
| `--provider` | `anthropic` | `anthropic`, `gemini` ou `ollama` |
| `--model` | `claude-sonnet-5-5` | Qualquer modelo do provedor |
| `--dry-run` | desligado | Não chama modelo: imprime o contexto condensado e a estimativa |

O relatório sai no stdout (dá para `> relatorio.md`); estimativas e uso vão para o stderr.

## Exemplo de dry-run

```text
$ ariadne tests/fixtures/sample_app "como funciona o login?" --dry-run --budget 2k
>> alvo: tests/fixtures/sample_app (folder) — extraindo localmente (0 tokens)…
   evidência bruta: ≈303 tokens em 7 trechos
   após condensar: ≈953 tokens com o prompt, 7 trechos (0 descartados) — budget 2,000
   custo máximo estimado (claude-sonnet-5-5): ≈US$ 0.0419 (entrada + até 4000 de saída)
   dry-run: nenhum modelo foi chamado.
# Contexto condensado (dry-run)

Pergunta: como funciona o login?

### README.md
# Sample App
A tiny shop API. Login issues a session token checked by the auth middleware.

### [visão geral]
4 arquivos. Extensões mais comuns: .js (2), .md (1), .json (1)
...

### src/auth.js (símbolos)
L3: function hashPassword(password, salt) {
L7: async function login(req, res) {

### src/auth.js:L1-L15
const crypto = require("crypto");
...
```

Rodando na própria Ariadne com `--budget 6k`: ≈9k tokens de evidência bruta viram ≈6k, e os trechos que sobram são justamente `budget.py`, `cli.py` e `llm.py`.

## Como o orçamento de tokens funciona

1. **Extração local, 0 tokens.** Nenhum modelo é chamado nesta fase.
   - **Pasta:** árvore de arquivos e estatística de extensões, README e manifests (`package.json`, `pyproject.toml`, `go.mod`…), um *outline* de símbolos por arquivo (linhas com `def`/`class`/`function`/`func`… e o número da linha) e o código em pedaços de 60 linhas (`arquivo:L61-L120`). Ignora `node_modules`, `.git`, `dist` etc.
   - **Binário:** `file` (tipo), `objdump -p` (bibliotecas), `nm` (símbolos exportados e funções importadas) e strings imprimíveis com o offset (`0x1a2b: ...`), separando as "interessantes" (URLs, erros, config, SQL). Se alguma ferramenta não existir, segue sem ela (as strings são extraídas em Python puro).
   - **URL:** headers HTTP relevantes (`server`, `x-powered-by`, CSP…), título, metas, texto visível, scripts inline e até 6 bundles JS: endpoints citados (`/api/...`), `sourceMappingURL` e, se o source map for público, a lista de arquivos originais.
2. **Ranqueamento.** Cada trecho tem um peso prévio (visão geral e README > outline > código; testes e fixtures valem metade) multiplicado pela relevância para a pergunta (quantas palavras da pergunta aparecem no caminho e no texto, em escala logarítmica para um arquivo repetitivo não dominar).
3. **Condensação gulosa.** Do melhor para o pior, entra o trecho inteiro se couber; o primeiro que não cabe é cortado no espaço restante; o resto é descartado. Uma reserva fixa cobre o prompt de sistema e a pergunta.
4. **Estimativa antes, uso real depois.** A estimativa offline usa ~3,5 caracteres por token (conservadora para código). Antes da chamada real ao Claude, a Ariadne pede a contagem exata ao endpoint gratuito `count_tokens`. Depois imprime os tokens reais devolvidos pela API e o custo em US$ (tabela em `ariadne/budget.py`).
5. **Uma chamada só.** Um prompt pede: o que é, como funciona, evidências (sempre citando os rótulos do contexto), confiança e lacunas. Nada de loop de agente gastando tokens explorando.

## Ética

A Ariadne serve para entender software que você **tem permissão** de analisar: o seu código, open source, binários que você pode inspecionar por licença, sites que você pode acessar. Não tem nem vai ter recurso para burlar DRM, licenças ou proteção anticópia, nem para atacar sistemas de terceiros. Respeite os termos de uso de cada site.

## Desenvolvimento

```bash
uv run --group dev pytest -q
```

Os testes cobrem o orçamento (parse, estimativa, ranqueamento, corte) e os extratores com fixtures (pasta de exemplo, binário falso, binário real `/bin/ls`, site servido localmente com bundle e source map). O CI roda no GitHub Actions sem nenhuma chave de API.

## Créditos

Inspirado no [REA — Reverse Engineer Anything](https://github.com/morluto/rea), um servidor MCP completo para engenharia reversa de binários, apps e comportamento em runtime. A Ariadne é outro projeto, com código próprio e outra proposta: menos poder, mais simplicidade e controle explícito de tokens. Se você precisa de análise profunda e interativa, use o REA.

---

## English

**Ariadne** helps you understand how a piece of software works by asking an LLM, while spending as few tokens as possible. Point it at a local folder, a binary or a URL: it extracts evidence locally for free (file tree, symbols, line-ranged code, binary strings/imports with offsets, HTTP headers, JS bundles and source maps), ranks and condenses it to fit `--budget`, prints a cost estimate, makes **one** model call and prints the real usage and cost. `--dry-run` shows the condensed context without calling any model.

```bash
uvx --from git+https://github.com/ogatalars/ariadne-thread ariadne . "how does auth work?" --dry-run
```

Bring your own key: Anthropic Claude (default `claude-sonnet-5-5`), Gemini (`GEMINI_API_KEY`) or a local Ollama model. Only analyze software you are allowed to analyze; there are no DRM-bypass or cracking features. Inspired by [REA](https://github.com/morluto/rea). MIT license.
