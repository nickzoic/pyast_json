import json
import subprocess
import sys

import pyast_json
from pyast_json.cli import main

SOURCE = "# comment\nimport os  # why\n\ndef f(x):\n    '''Doc.'''\n    return x\n"


def test_encode_decode_files(tmp_path):
    src = tmp_path / "mod.py"
    src.write_text(SOURCE, encoding="utf-8")
    js, out = tmp_path / "mod.json", tmp_path / "out.py"
    assert main(["encode", str(src), "-o", str(js)]) == 0
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data == pyast_json.source_to_json(SOURCE)
    assert main(["decode", str(js), "-o", str(out), "--check"]) == 0
    assert out.read_text(encoding="utf-8") == pyast_json.json_to_source(data)


def test_validate_flags(tmp_path, jsonschema):
    src = tmp_path / "mod.py"
    src.write_text(SOURCE, encoding="utf-8")
    js = tmp_path / "mod.json"
    assert main(["encode", str(src), "-o", str(js), "--validate", "--indent", "0"]) == 0
    assert main(["decode", str(js), "-o", str(tmp_path / "o.py"), "--validate"]) == 0
    js.write_text('{"_type": "Module", "body": [{"_type": "Bogus"}]}', encoding="utf-8")
    assert main(["decode", str(js), "--validate"]) == 1


def test_schema_command(tmp_path):
    target = tmp_path / "schema.json"
    assert main(["schema", "-o", str(target)]) == 0
    assert json.loads(target.read_text(encoding="utf-8")) == pyast_json.load_schema()


def test_coding_cookie_controls_output_encoding(tmp_path):
    src = tmp_path / "latin.py"
    src.write_bytes("# -*- coding: latin-1 -*-\ns = 'caf\xe9'\n".encode("latin-1"))
    js, out = tmp_path / "latin.json", tmp_path / "out.py"
    assert main(["encode", str(src), "-o", str(js)]) == 0
    assert main(["decode", str(js), "-o", str(out)]) == 0
    raw = out.read_bytes()
    assert "caf\xe9".encode("latin-1") in raw
    namespace = {}
    exec(compile(raw, str(out), "exec"), namespace)
    assert namespace["s"] == "caf\xe9"


def test_errors_give_exit_status_1(tmp_path, capsys):
    bad_py = tmp_path / "bad.py"
    bad_py.write_text("def (:\n", encoding="utf-8")
    assert main(["encode", str(bad_py)]) == 1
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("not json", encoding="utf-8")
    assert main(["decode", str(bad_json)]) == 1
    assert main(["decode", str(tmp_path / "missing.json")]) == 1
    assert "pyast-json: error:" in capsys.readouterr().err


def test_python_dash_m_with_pipes():
    encoded = subprocess.run([sys.executable, "-m", "pyast_json", "encode", "-"],
                             input=SOURCE.encode(), capture_output=True, check=True).stdout
    decoded = subprocess.run([sys.executable, "-m", "pyast_json", "decode", "-"],
                             input=encoded, capture_output=True, check=True).stdout
    assert decoded.decode("utf-8") == pyast_json.json_to_source(json.loads(encoded))
