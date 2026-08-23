import re

_GENERATED_LABEL = re.compile(
    r"\[(?:synthetic\s+(?:demo\s+)?(?:review|reply|follow-up|post)|"
    r"synthetic\s+security-test\s+review)\]\s*",
    re.IGNORECASE,
)
_THREAD_LABEL = re.compile(
    r"^\s*\[(?:level\s+\d+[^\]]*|root|reply\s+depth=\d+)\]\s*",
    re.IGNORECASE | re.MULTILINE,
)
_DISCLOSURE = re.compile(
    r"\s*(?:Merchant identity is source-backed; this post, media and promotions are synthetic\."
    r"|It is not a real user visit; prices and hours are synthetic\.)",
    re.IGNORECASE,
)
_LEGACY_BLOG_TITLE = re.compile(
    r"^\s*A practical visit to [^\r\n]+(?:\r?\n)+",
    re.IGNORECASE,
)


def clean_display_text(value: str | None) -> str:
    """Remove generator/provenance markup from text shown as user content.

    Provenance remains in structured citation fields. This also keeps an older
    Qdrant collection readable until it is rebuilt from the cleaned dataset.
    """

    text = str(value or "")
    text = _THREAD_LABEL.sub("", text)
    text = _GENERATED_LABEL.sub("", text)
    text = _LEGACY_BLOG_TITLE.sub("", text)
    text = re.sub(r"\bThis generated scenario describes\s+", "", text, flags=re.IGNORECASE)
    text = _DISCLOSURE.sub("", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip()).strip()
