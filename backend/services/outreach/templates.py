"""Message templates — `{{variable}}` substitution, validated before send.

Deliberately not a general template engine: no expressions, no filters, no
attribute access, no code paths that can reach the interpreter. A template
is a string with `{{name}}` placeholders; rendering is a whitelist lookup
and nothing else. That keeps a user-authored template from becoming an
injection vector into the worker process.

`render` refuses to produce a message with an unresolved placeholder, so a
half-rendered "Hello {{username}}" can never be sent to a real person.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable, Mapping, Optional

#: `{{ name }}` — letters, digits, underscore. Whitespace inside the braces
#: is tolerated because people type it.
PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

#: Always available, filled from the target/campaign/account row.
BUILTIN_VARIABLES = ("username", "profile_url", "campaign_name", "account_name")

MAX_BODY_LENGTH = 4000
MAX_RENDERED_LENGTH = 2000
MAX_VALUE_LENGTH = 500

#: Stripped from rendered output: C0 controls except tab/newline, plus the
#: bidi overrides that can visually disguise a message's real content.
_CONTROL_RE = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u202a-\u202e\u2066-\u2069]"
)


class TemplateError(ValueError):
    """Template is unusable — bad syntax, or a variable with no value."""


def extract_variables(body: str) -> list[str]:
    """Placeholder names in first-appearance order, deduplicated."""
    seen: list[str] = []
    for name in PLACEHOLDER_RE.findall(body or ""):
        if name not in seen:
            seen.append(name)
    return seen


def validate_template(body: str, known_variables: Optional[Iterable[str]] = None) -> list[str]:
    """Check a template body standalone. Returns its variable list.

    Raises TemplateError on an empty body, an over-long body, malformed
    braces, or (when `known_variables` is given) a placeholder that nothing
    will ever fill.
    """
    if body is None or not str(body).strip():
        raise TemplateError("Message template is empty")
    body = str(body)
    if len(body) > MAX_BODY_LENGTH:
        raise TemplateError(f"Message template exceeds {MAX_BODY_LENGTH} characters")

    # Strip the well-formed placeholders, then look for leftover braces.
    residue = PLACEHOLDER_RE.sub("", body)
    if "{{" in residue or "}}" in residue:
        raise TemplateError(
            "Malformed placeholder — use {{variable_name}} with letters, digits "
            "and underscores only"
        )

    variables = extract_variables(body)
    if known_variables is not None:
        known = set(known_variables) | set(BUILTIN_VARIABLES)
        missing = [v for v in variables if v not in known]
        if missing:
            raise TemplateError(
                "Template uses undefined variable(s): " + ", ".join(sorted(missing))
            )
    return variables


def _clean(value: Any) -> str:
    text = "" if value is None else str(value)
    text = _CONTROL_RE.sub("", text)
    if len(text) > MAX_VALUE_LENGTH:
        text = text[:MAX_VALUE_LENGTH]
    return text


def render(body: str, variables: Mapping[str, Any]) -> str:
    """Substitute every placeholder, or raise.

    A value that is None or blank counts as missing — sending "Hello ,"
    is worse than failing the job.
    """
    validate_template(body)
    values = {k: _clean(v) for k, v in (variables or {}).items()}

    missing = [
        name for name in extract_variables(body)
        if not values.get(name, "").strip()
    ]
    if missing:
        raise TemplateError(
            "No value for template variable(s): " + ", ".join(sorted(set(missing)))
        )

    rendered = PLACEHOLDER_RE.sub(lambda m: values[m.group(1)], body)
    rendered = _CONTROL_RE.sub("", rendered).strip()
    if not rendered:
        raise TemplateError("Rendered message is empty")
    if len(rendered) > MAX_RENDERED_LENGTH:
        raise TemplateError(
            f"Rendered message is {len(rendered)} characters, over the "
            f"{MAX_RENDERED_LENGTH} limit"
        )
    return rendered


def parse_vars(raw: Optional[str]) -> dict[str, str]:
    """Read a JSON variables blob from the DB. Junk yields {} rather than
    an exception — a malformed blob shows up as a missing-variable error at
    render time, which is the message the operator can act on."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): _clean(v) for k, v in data.items() if str(k).isidentifier()}


def dump_vars(data: Optional[Mapping[str, Any]]) -> Optional[str]:
    """Serialize a variables mapping for storage, dropping illegal names."""
    if not data:
        return None
    clean = {str(k): _clean(v) for k, v in data.items() if str(k).isidentifier()}
    return json.dumps(clean) if clean else None


def build_variables(
    target: Mapping[str, Any],
    campaign: Mapping[str, Any],
    account: Optional[Mapping[str, Any]] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, str]:
    """Assemble the render context for one job.

    Precedence, lowest first: campaign `template_vars` → caller `extra` →
    built-ins. Built-ins win so a stray `username` in the campaign vars can
    never override the actual target's handle.
    """
    values: dict[str, str] = {}
    values.update(parse_vars(campaign.get("template_vars")))
    if extra:
        values.update({str(k): _clean(v) for k, v in extra.items()})
    values.update({
        "username": _clean(target.get("username")),
        "profile_url": _clean(target.get("profile_url")),
        "campaign_name": _clean(campaign.get("name")),
        "account_name": _clean((account or {}).get("name")),
    })
    return values


def preview(body: str, campaign_vars: Optional[Mapping[str, Any]] = None) -> str:
    """Render with placeholder sample data, for the template editor."""
    sample = {
        "username": "creator_handle",
        "profile_url": "https://www.tiktok.com/@creator_handle",
        "campaign_name": "Sample campaign",
        "account_name": "Sender 1",
    }
    values = dict(campaign_vars or {})
    values.update(sample)
    for name in extract_variables(body or ""):
        values.setdefault(name, f"<{name}>")
    return render(body, values)
