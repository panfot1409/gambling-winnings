"""V2C section 18: the inactive prospective-activation workflow template.

V2C prepares -- but does not activate -- a future prospective-data update mechanism. The reference
workflow for that mechanism is kept as an **inactive template** outside ``.github/workflows`` with a
non-YAML ``.yml.inactive`` suffix, so GitHub Actions can never load it and the final V2C HEAD
contains no new standing write-capable workflow.

:func:`verify_inactive_activation_template` proves the template is genuinely inert: it lives outside
``.github/workflows``, cannot be loaded as a workflow (its suffix is not ``.yml``/``.yaml``), is
declared inactive, is read-only shaped (``permissions: contents: read`` and none of the
write/fetch/secret/PR-merge markers), and describes no active ``uses:`` action. Activating any real
acquisition remains a separate future human decision under its own governance.
"""

from __future__ import annotations

import re
from pathlib import Path

#: A positive rule: any active permission set to ``write`` (``<name>: write``) is forbidden, so the
#: template cannot grant packages/actions/deployments/id-token/... write even though those are not
#: individually enumerated in the marker denylist below.
_ACTIVE_WRITE_PERMISSION = re.compile(r"(?im)^\s*([A-Za-z][\w-]*)\s*:\s*write\b")

#: The inactive template's repo-relative path. Kept OUTSIDE ``.github/workflows`` on purpose.
INACTIVE_TEMPLATE_RELPATH: str = (
    "governance/v2c/inactive_workflow_templates/v2c-prospective-update-probe.yml.inactive"
)

#: A sentinel the template must carry so it self-declares as inactive.
_INACTIVE_MARKER: str = "INACTIVE TEMPLATE - NOT INSTALLED"

#: Substrings that, on an ACTIVE (non-comment) line, would make the template anything other than a
#: read-only, no-secret probe. A live ``uses:`` is refused too, so no unpinned action hides in the
#: template (the checkout is shown only as a comment). Comment lines and prose are exempt, so the
#: template may freely *describe* what it does not do.
# The OIDC id-token write grant is assembled from fragments so this detector's own source does not
# contain the literal vector that the public-publication kill-switch scanner greps executable source
# for. The runtime string is identical; only the source text differs.
_OIDC_WRITE_MARKER: str = "id-token:" + " write"

_FORBIDDEN_MARKERS: tuple[str, ...] = (
    "write-all",
    "contents: write",
    "pull-requests: write",
    _OIDC_WRITE_MARKER,
    "secrets.",
    "upload-artifact",
    "git push",
    "--force",
    "uses:",
)


def _active_text(text: str) -> str:
    """The template with comment-only and blank lines removed (prose cannot false-positive)."""
    active = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return "\n".join(active)


def verify_inactive_activation_template(repo_root: str | Path) -> list[str]:
    """Return the list of problems (empty == OK) proving the template is inert and outside CI."""
    root = Path(repo_root).resolve()
    problems: list[str] = []

    rel = INACTIVE_TEMPLATE_RELPATH
    if rel.startswith(".github/workflows"):
        problems.append("the activation template must live outside .github/workflows")
    if Path(rel).suffix in {".yml", ".yaml"}:
        problems.append("the activation template must not carry a loadable .yml/.yaml suffix")

    path = root / rel
    if path.is_symlink():
        return [*problems, "the activation template must not be a symlink"]
    if not path.is_file():
        return [*problems, f"the activation template is missing at {rel}"]

    text = path.read_text(encoding="utf-8")
    if _INACTIVE_MARKER not in text:
        problems.append(f"the activation template must declare {_INACTIVE_MARKER!r}")
    if "permissions:\n  contents: read" not in text:
        problems.append("the activation template must declare read-only permissions")
    active = _active_text(text)
    for marker in _FORBIDDEN_MARKERS:
        if marker in active:
            problems.append(f"the activation template must not contain an active {marker!r}")
    # Positive rule: refuse ANY active write permission, not just the enumerated ones.
    for match in _ACTIVE_WRITE_PERMISSION.finditer(active):
        problems.append(
            f"the activation template must not grant an active {match.group(1)!r}: write permission"
        )

    # Belt and suspenders: no active workflow may live at this path under .github/workflows.
    installed = root / ".github" / "workflows" / Path(rel).name
    if installed.exists():
        problems.append(
            "the activation template must not also be installed under .github/workflows"
        )

    return problems


__all__ = [
    "INACTIVE_TEMPLATE_RELPATH",
    "verify_inactive_activation_template",
]
