"""Cheap local extraction (zero tokens): turn a folder, binary or URL into Chunks."""

from __future__ import annotations

import collections
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

from .budget import Chunk

SKIP_DIRS = {".git", "node_modules", "dist", "build", "target", ".venv", "venv",
             "__pycache__", ".next", ".idea", ".vscode", "vendor", ".tox", ".mypy_cache"}
MANIFESTS = {"package.json", "pyproject.toml", "setup.py", "go.mod", "Cargo.toml",
             "pom.xml", "build.gradle", "Gemfile", "composer.json", "Dockerfile",
             "docker-compose.yml", "Makefile", "requirements.txt"}
CODE_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".rb",
            ".php", ".c", ".h", ".cpp", ".cs", ".swift", ".scala", ".sh", ".sql",
            ".yaml", ".yml", ".toml", ".json", ".md"}
SYMBOL_RE = re.compile(
    r"^[ \t]*(?:export\s+)?(?:async\s+)?(?:pub\s+)?"
    r"(?:def|class|function|func|fn|interface|type|struct|enum|const\s+\w+\s*=\s*\(|"
    r"public|private|protected)\b.*",
    re.M,
)
MAX_FILE_BYTES = 200_000
PIECE_LINES = 60
UA = "ariadne-thread/0.1 (+https://github.com/ogatalars/ariadne-thread)"


def kind_of(target: str) -> str:
    if re.match(r"https?://", target):
        return "url"
    p = Path(target)
    if p.is_dir():
        return "folder"
    if p.is_file():
        return "binary" if is_binary(p) else "file"
    raise FileNotFoundError(f"alvo não encontrado: {target}")


def is_binary(p: Path) -> bool:
    with open(p, "rb") as f:
        return b"\0" in f.read(8192)


def extract(target: str) -> list[Chunk]:
    k = kind_of(target)
    if k == "url":
        return extract_url(target)
    if k == "folder":
        return extract_folder(Path(target))
    if k == "binary":
        return extract_binary(Path(target))
    p = Path(target)
    return [Chunk(p.name, p.read_text(errors="replace"), 2.0)]


# ---------- folders ----------

def extract_folder(root: Path) -> list[Chunk]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        files += [Path(dirpath) / f for f in sorted(filenames)]
    rel = lambda p: p.relative_to(root).as_posix()  # noqa: E731

    langs = collections.Counter(p.suffix or p.name for p in files)
    overview = (f"{len(files)} arquivos. Extensões mais comuns: "
                + ", ".join(f"{e} ({n})" for e, n in langs.most_common(10))
                + "\n\nÁrvore (até 200 entradas):\n"
                + "\n".join(rel(p) for p in files[:200]))
    chunks = [Chunk("[visão geral]", overview, 3.0)]

    for p in files:
        if p.suffix not in CODE_EXT and p.name not in MANIFESTS:
            continue
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
            text = p.read_text(errors="replace")
        except OSError:
            continue
        name = rel(p)
        # tests/fixtures/examples are evidence too, but rarely the answer
        w = 0.5 if re.search(r"(^|/)(tests?|spec|fixtures?|examples?|__tests__)/", name) else 1.0
        if p.name.lower().startswith("readme") or p.name in MANIFESTS:
            chunks.append(Chunk(name, text[:6000], 2.5 * w))
            continue
        symbols = outline(text)
        if symbols:
            chunks.append(Chunk(f"{name} (símbolos)", symbols, 1.5 * w))
        chunks += [Chunk(src, piece, w) for src, piece in pieces(name, text)]
    return chunks


def pieces(name: str, text: str, lines_per: int = PIECE_LINES) -> list[tuple[str, str]]:
    """Split a file into line ranges so each piece is ranked alone and cited as path:La-Lb."""
    lines = text.splitlines()
    return [(f"{name}:L{i + 1}-L{min(i + lines_per, len(lines))}", "\n".join(lines[i:i + lines_per]))
            for i in range(0, len(lines), lines_per)]


def outline(text: str) -> str:
    """Lines that declare symbols, prefixed with their line number (evidence pointer)."""
    out = []
    for m in SYMBOL_RE.finditer(text):
        line_no = text.count("\n", 0, m.start()) + 1
        out.append(f"L{line_no}: {m.group(0).strip()[:160]}")
    return "\n".join(out[:120])


# ---------- binaries ----------

def run(cmd: list[str], limit: int = 400_000) -> str:
    """Run an optional tool; empty string if it is missing or fails (graceful degrade)."""
    if not shutil.which(cmd[0]):
        return ""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, errors="replace")
        return r.stdout[:limit]
    except (OSError, subprocess.TimeoutExpired):
        return ""


def py_strings(data: bytes, min_len: int = 6) -> list[tuple[int, str]]:
    """Printable ASCII runs with their byte offset (stand-in for `strings -t x`)."""
    return [(m.start(), m.group().decode()) for m in re.finditer(rb"[\x20-\x7e]{%d,}" % min_len, data)]


INTERESTING = re.compile(r"https?://|/api/|\.so|\.dll|error|fail|token|config|usage|"
                         r"version|key|http|json|sql|select |insert |%s|%d", re.I)


def extract_binary(p: Path) -> list[Chunk]:
    data = p.read_bytes()
    chunks = []
    info = run(["file", "-bL", str(p)]) or f"{len(data)} bytes (comando `file` indisponível)"
    chunks.append(Chunk(f"{p.name} [tipo]", f"{info.strip()}\nTamanho: {len(data)} bytes", 3.0))

    libs = run(["objdump", "-p", str(p)])
    needed = "\n".join(l.strip() for l in libs.splitlines() if "NEEDED" in l or "DLL Name" in l)
    if needed:
        chunks.append(Chunk(f"{p.name} [bibliotecas]", needed, 2.5))
    syms = run(["nm", "-D", "--defined-only", str(p)]) or run(["nm", str(p)])
    if syms:
        names = sorted({l.split()[-1] for l in syms.splitlines() if l.strip()})
        chunks.append(Chunk(f"{p.name} [símbolos exportados]", "\n".join(names[:400]), 2.0))
    imports = run(["nm", "-D", "--undefined-only", str(p)])
    if imports:
        names = sorted({l.split()[-1] for l in imports.splitlines() if l.strip()})
        chunks.append(Chunk(f"{p.name} [funções importadas]", "\n".join(names[:400]), 2.0))

    seen, hot, rest = set(), [], []
    for off, s in py_strings(data):
        if s in seen:
            continue
        seen.add(s)
        (hot if INTERESTING.search(s) else rest).append(f"0x{off:x}: {s[:200]}")
    if hot:
        chunks.append(Chunk(f"{p.name} [strings relevantes]", "\n".join(hot[:600]), 1.8))
    for i in range(0, min(len(rest), 3000), 300):  # small chunks so the budget can rank them
        chunks.append(Chunk(f"{p.name} [strings {i}-{i + 300}]", "\n".join(rest[i:i + 300]), 0.6))
    return chunks


# ---------- URLs ----------

def fetch(url: str, limit: int = 2_000_000) -> tuple[dict, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        return dict(r.headers), r.read(limit).decode(errors="replace")


ENDPOINT_RE = re.compile(r"""["'`](/(?:api|v\d|graphql|rest)[\w\-./{}:]*|https?://[\w\-.]+(?:/[\w\-./]*)?)["'`]""")


def extract_url(url: str, max_scripts: int = 6) -> list[Chunk]:
    headers, html = fetch(url)
    keep = {k: v for k, v in headers.items()
            if k.lower() in {"server", "x-powered-by", "content-type", "content-security-policy",
                             "set-cookie", "via", "x-frame-options", "strict-transport-security",
                             "cache-control", "x-generator"}}
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    metas = re.findall(r"<meta[^>]+(?:name|property)=[\"']([^\"']+)[\"'][^>]+content=[\"']([^\"']*)", html, re.I)
    scripts = re.findall(r"<script[^>]+src=[\"']([^\"']+)", html, re.I)
    page = (f"Título: {title.group(1).strip() if title else '-'}\n"
            + "Headers:\n" + "\n".join(f"  {k}: {v[:300]}" for k, v in keep.items())
            + "\nMeta:\n" + "\n".join(f"  {k}: {v[:200]}" for k, v in metas[:30])
            + "\nScripts:\n" + "\n".join(f"  {s}" for s in scripts))
    chunks = [Chunk(url, page, 3.0)]
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()
    if text:
        chunks.append(Chunk(f"{url} [texto visível]", text[:6000], 1.5))
    inline = re.findall(r"<script(?![^>]+src)[^>]*>(.*?)</script>", html, re.S | re.I)
    if inline:
        chunks.append(Chunk(f"{url} [scripts inline]", "\n".join(inline)[:5000], 1.2))

    for src in scripts[:max_scripts]:
        js_url = urllib.parse.urljoin(url, src)
        try:
            _, js = fetch(js_url)
        except Exception as e:  # noqa: BLE001 - a broken script must not stop the run
            chunks.append(Chunk(js_url, f"(falha ao baixar: {e})", 0.3))
            continue
        chunks += js_chunks(js_url, js)
    return chunks


def js_chunks(js_url: str, js: str) -> list[Chunk]:
    out = []
    sm = re.search(r"sourceMappingURL=(\S+)", js)
    endpoints = sorted(set(ENDPOINT_RE.findall(js)))
    summary = (f"{len(js)} chars. Source map: "
               + (urllib.parse.urljoin(js_url, sm.group(1)) if sm else "não encontrado")
               + "\nEndpoints/URLs citados:\n" + "\n".join(endpoints[:200]))
    out.append(Chunk(f"{js_url} [resumo]", summary, 2.0))
    if sm and not sm.group(1).startswith("data:"):
        try:
            _, raw = fetch(urllib.parse.urljoin(js_url, sm.group(1)))
            files = re.findall(r'"([^"]+\.(?:tsx?|jsx?|vue|svelte))"', raw)
            out.append(Chunk(f"{js_url} [arquivos originais do source map]",
                             "\n".join(sorted(set(files))[:300]), 2.2))
        except Exception:  # noqa: BLE001
            pass
    for i in range(0, min(len(js), 60_000), 6_000):
        out.append(Chunk(f"{js_url} @ chars {i}-{i + 6000}", js[i:i + 6000], 0.5))
    return out
