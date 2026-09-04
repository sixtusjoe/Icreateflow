"""Message template rendering and validation. No database, no browser."""
from __future__ import annotations

import pytest

from services.outreach import templates as tpl


def test_extract_variables_in_order_without_duplicates():
    body = "Hi {{username}}, about {{offer}} — {{username}}?"
    assert tpl.extract_variables(body) == ["username", "offer"]


def test_render_substitutes_every_placeholder():
    body = "Hello {{username}}, we came across your content about {{offer}}."
    out = tpl.render(body, {"username": "alice", "offer": "our beta"})
    assert out == "Hello alice, we came across your content about our beta."


def test_render_tolerates_whitespace_inside_braces():
    assert tpl.render("Hi {{ username }}", {"username": "bob"}) == "Hi bob"


def test_render_refuses_a_missing_variable():
    with pytest.raises(tpl.TemplateError, match="offer"):
        tpl.render("Hi {{username}} about {{offer}}", {"username": "alice"})


def test_render_treats_a_blank_value_as_missing():
    # Half-rendered greetings ("Hello ,") must never reach a real person.
    with pytest.raises(tpl.TemplateError):
        tpl.render("Hello {{username}}", {"username": "   "})


def test_validate_rejects_empty_and_malformed_templates():
    with pytest.raises(tpl.TemplateError):
        tpl.validate_template("   ")
    with pytest.raises(tpl.TemplateError, match="Malformed"):
        tpl.validate_template("Hi {{user-name}}")
    with pytest.raises(tpl.TemplateError, match="Malformed"):
        tpl.validate_template("Hi {{username}")


def test_validate_rejects_unknown_variables_when_a_whitelist_is_given():
    with pytest.raises(tpl.TemplateError, match="offer"):
        tpl.validate_template("Hi {{username}} re {{offer}}", known_variables=[])
    # Built-ins are always known.
    assert tpl.validate_template("Hi {{username}}", known_variables=[]) == ["username"]


def test_render_strips_control_and_bidi_characters():
    out = tpl.render("Hi {{username}}", {"username": "al‮ice\x07"})
    assert out == "Hi alice"


def test_render_rejects_an_over_long_message():
    long_body = "x" * (tpl.MAX_RENDERED_LENGTH + 10)
    with pytest.raises(tpl.TemplateError, match="over the"):
        tpl.render(long_body, {})


def test_template_syntax_cannot_reach_python():
    """Not a template engine: only {{name}} means anything, and a name is
    just a dictionary key — never an expression, an import or an attribute."""
    # Other engines' syntax is inert literal text.
    assert tpl.render("{%raw%} ${danger} {{ok}}", {"ok": "fine"}) == "{%raw%} ${danger} fine"
    # A dangerous-looking name is only a name, and one with no value fails
    # closed rather than evaluating anything.
    with pytest.raises(tpl.TemplateError, match="__import__"):
        tpl.render("{{__import__}}", {})
    assert tpl.render("{{__import__}}", {"__import__": "literal"}) == "literal"
    # Attribute and call syntax is not a placeholder at all.
    with pytest.raises(tpl.TemplateError, match="Malformed"):
        tpl.validate_template("{{os.system('rm -rf /')}}")


def test_build_variables_builtins_win_over_campaign_vars():
    target = {"username": "alice", "profile_url": "https://www.tiktok.com/@alice"}
    campaign = {
        "name": "Q3 push",
        "template_vars": '{"offer": "our beta", "username": "attacker"}',
    }
    values = tpl.build_variables(target, campaign, {"name": "Sender 1"})
    assert values["username"] == "alice"
    assert values["offer"] == "our beta"
    assert values["campaign_name"] == "Q3 push"
    assert values["account_name"] == "Sender 1"


def test_parse_vars_survives_junk():
    assert tpl.parse_vars(None) == {}
    assert tpl.parse_vars("not json") == {}
    assert tpl.parse_vars('["a"]') == {}
    assert tpl.parse_vars('{"offer": "x", "bad name": "y"}') == {"offer": "x"}


def test_dump_and_parse_round_trip():
    raw = tpl.dump_vars({"offer": "our beta", "9bad": "dropped"})
    assert tpl.parse_vars(raw) == {"offer": "our beta"}


def test_preview_fills_unknown_variables_with_placeholders():
    out = tpl.preview("Hi {{username}} about {{offer}}")
    assert out == "Hi creator_handle about <offer>"
