"""Where comments are attached, and where they are written back."""
import textwrap

from pyast_json import json_to_source, read_comments, source_to_json


def encode(source):
    return source_to_json(textwrap.dedent(source).lstrip("\n"))


def test_comment_text_is_exact():
    data = encode("x = 1  #   spaced   text\n#!bang\n#\ny = 2\n")
    assert data["body"][0]["comments"] == ["   spaced   text"]
    assert data["body"][1]["comments"] == ["!bang", ""]


def test_read_comments_lines():
    assert read_comments("a = 1  # one\n\n# three\ns = '# not a comment'\n") == [
        (1, " one"), (3, " three")]


def test_header_comments_belong_to_compound_statement():
    data = encode("""
        @dec  # on decorator
        def f(a,  # on parameter
              b):  # after colon
            pass
        """)
    assert data["body"][0]["_type"] == "FunctionDef"
    assert data["body"][0]["comments"] == [" on decorator", " on parameter", " after colon"]


def test_body_comment_stays_in_body():
    data = encode("""
        def f():
            # first in body
            return 1
        """)
    func = data["body"][0]
    assert "comments" not in func
    assert func["body"][0]["comments"] == [" first in body"]
    assert json_to_source(data) == "def f():\n    # first in body\n    return 1\n"


def test_comment_inside_multiline_statement():
    data = encode("""
        x = [1,  # one
             2]  # two
        """)
    assert data["body"][0]["comments"] == [" one", " two"]


def test_comment_after_block_goes_to_next_statement():
    data = encode("""
        if a:
            b()
            # end of block
        c()
        """)
    assert data["body"][1]["comments"] == [" end of block"]


def test_trailing_comments_on_module():
    data = encode("x = 1\n# last\n#  really last\n")
    assert data["comments"] == [" last", "  really last"]
    assert json_to_source(data) == "x = 1\n# last\n#  really last\n"


def test_comments_only_module():
    data = encode("# only\n")
    assert data == {"_type": "Module", "body": [], "comments": [" only"]}
    assert json_to_source(data) == "# only\n"


def test_shebang_and_cookie_stay_on_first_lines():
    source = "#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n\"\"\"Doc.\"\"\"\nimport os\n"
    out = json_to_source(source_to_json(source))
    assert out.splitlines()[:2] == ["#!/usr/bin/env python3", "# -*- coding: utf-8 -*-"]


def test_blank_line_goes_above_comment_before_def():
    out = json_to_source(encode("""
        x = 1
        # about f
        def f():
            pass
        """))
    assert out == "x = 1\n\n# about f\ndef f():\n    pass\n"


def test_comment_indentation_follows_statement():
    out = json_to_source(encode("""
        class C:
            def m(self):
                if x:
                    # deep
                    pass
        """))
    assert "            # deep\n            pass\n" in out


def test_comments_on_elif():
    source = "if a:\n    pass\n# before elif\nelif b:\n    pass\n"
    out = json_to_source(source_to_json(source))
    assert "# before elif" in out
    assert compile(out, "<test>", "exec")
