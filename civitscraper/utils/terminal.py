"""Small helpers shared by the interactive jobs (sort, update downloads)."""

from typing import Any, Callable, Dict, List

from ..api.domains import build_model_url, get_domain_settings, is_nsfw

InputFn = Callable[[str], str]
OutputFn = Callable[[str], None]


class Style:
    """ANSI styling, or plain text when output is not a terminal."""

    def __init__(self, enabled: bool):
        """Enable or disable colours."""
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def bold(self, text: str) -> str:
        """Bold text."""
        return self._wrap("1", text)

    def dim(self, text: str) -> str:
        """Dimmed text."""
        return self._wrap("2", text)

    def accent(self, text: str) -> str:
        """Highlighted text."""
        return self._wrap("36", text)

    def warn(self, text: str) -> str:
        """Warning text."""
        return self._wrap("33", text)


def ask(input_fn: InputFn, output_fn: OutputFn, prompt: str, valid: str, default: str) -> str:
    """Ask until the first letter of the answer is one of ``valid`` (EOF answers ``q``)."""
    while True:
        try:
            answer = input_fn(prompt).strip().lower()
        except EOFError:
            return "q"
        if not answer:
            return default
        if answer[0] in valid:
            return answer[0]
        output_fn(f"  Please answer one of: {', '.join(valid)}")


def version_links(
    config: Dict[str, Any], model_id: Any, version_id: Any, metadata: Dict[str, Any]
) -> List[str]:
    """Return a version's CivitAI pages on both domains, its routed domain first."""
    if not model_id or not version_id:
        return []
    domains, threshold, _ = get_domain_settings(config)
    nsfw = is_nsfw(metadata or {}, threshold)
    return [
        build_model_url(model_id, version_id, nsfw, domains),
        build_model_url(model_id, version_id, not nsfw, domains),
    ]


def human_size(num_bytes: float) -> str:
    """Return ``1.2 GB``-style sizes."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
