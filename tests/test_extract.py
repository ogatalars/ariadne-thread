import functools
import http.server
import shutil
import threading
from pathlib import Path

import pytest

from ariadne import extract as ex
from ariadne.cli import main

FIX = Path(__file__).parent / "fixtures"


def test_kind_of(tmp_path):
    assert ex.kind_of("https://example.com") == "url"
    assert ex.kind_of(str(FIX / "sample_app")) == "folder"
    b = tmp_path / "x.bin"
    b.write_bytes(b"\x7fELF\0\0hello world")
    assert ex.kind_of(str(b)) == "binary"
    with pytest.raises(FileNotFoundError):
        ex.kind_of(str(tmp_path / "missing"))


def test_folder_extraction():
    chunks = ex.extract_folder(FIX / "sample_app")
    by_src = {c.source: c for c in chunks}
    assert "[visão geral]" in by_src and "src/auth.js" in by_src["[visão geral]"].text
    assert "README.md" in by_src and "package.json" in by_src
    outline = by_src["src/auth.js (símbolos)"].text
    assert "L3: function hashPassword" in outline
    assert "L7: async function login" in outline


def test_py_strings_offsets():
    data = b"\0\0abcdefgh\0\x01api_key=1234\0zz"
    assert ex.py_strings(data) == [(2, "abcdefgh"), (12, "api_key=1234")]


def test_binary_extraction_fake(tmp_path):
    b = tmp_path / "tool.bin"
    b.write_bytes(b"\0" * 16 + b"https://api.example.com/v1/login\0" + b"just some text\0")
    srcs = {c.source: c.text for c in ex.extract_binary(b)}
    assert "0x10: https://api.example.com/v1/login" in srcs["tool.bin [strings relevantes]"]


def test_binary_degrades_without_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(ex.shutil, "which", lambda _: None)
    b = tmp_path / "t.bin"
    b.write_bytes(b"\0config_path=/etc/x\0")
    srcs = {c.source: c.text for c in ex.extract_binary(b)}
    assert "indisponível" in srcs["t.bin [tipo]"]
    assert "config_path" in srcs["t.bin [strings relevantes]"]


@pytest.mark.skipif(not (shutil.which("nm") and Path("/bin/ls").exists()), reason="needs nm and /bin/ls")
def test_real_binary_imports():
    srcs = {c.source: c.text for c in ex.extract_binary(Path("/bin/ls"))}
    assert "ELF" in srcs["ls [tipo]"]
    assert any("importadas" in s or "bibliotecas" in s for s in srcs)


@pytest.fixture
def site():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(FIX / "site"))
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/"
    srv.shutdown()


def test_url_extraction(site):
    srcs = {c.source: c.text for c in ex.extract_url(site)}
    page = srcs[site]
    assert "Demo Shop" in page and "DemoKit 2.0" in page and "/static/app.js" in page
    js = site + "static/app.js"
    assert "/api/v1/checkout" in srcs[f"{js} [resumo]"]
    assert "app.js.map" in srcs[f"{js} [resumo]"]
    assert "../src/checkout.tsx" in srcs[f"{js} [arquivos originais do source map]"]
    assert "FLAGS" in srcs[f"{site} [scripts inline]"]


def test_cli_dry_run(capsys):
    rc = main([str(FIX / "sample_app"), "how does login work?", "--dry-run", "--budget", "4k"])
    out, err = capsys.readouterr()
    assert rc == 0
    assert "### src/auth.js:L1-L" in out
    assert "nenhum modelo foi chamado" in err and "US$" in err


def test_pieces_line_ranges():
    text = "\n".join(f"line{i}" for i in range(1, 131))
    got = ex.pieces("a.py", text, 60)
    assert [s for s, _ in got] == ["a.py:L1-L60", "a.py:L61-L120", "a.py:L121-L130"]
    assert got[1][1].startswith("line61")
