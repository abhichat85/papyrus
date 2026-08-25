"""RFC-822 email (.eml).

Headers become a key/value block so provenance survives; the body prefers
`text/plain`, falling back to the HTML part run through the HTML walker.
Attachments are listed, never executed and never decoded into assets.
"""

from __future__ import annotations

from email import policy
from email.parser import BytesParser

from papyrus.config import ConvertOptions
from papyrus.detect import Detection
from papyrus.errors import ParseError
from papyrus.ir import Document, ListItem, heading, key_values, list_block
from papyrus.parsers.base import BaseParser
from papyrus.parsers.text import text_to_blocks
from papyrus.utils.files import human_bytes
from papyrus.utils.text import clean

_HEADERS = ("From", "To", "Cc", "Subject", "Date", "Reply-To", "Message-ID")


class EmailParser(BaseParser):
    formats = ("eml",)
    label = "Email (.eml)"
    priority = 25

    def parse(self, data: bytes, filename: str, detection: Detection, options: ConvertOptions) -> Document:
        doc = self.new_document(data, filename, detection)
        try:
            message = BytesParser(policy=policy.default).parsebytes(data)
        except Exception as exc:
            raise ParseError(f"Could not parse email: {exc}") from exc

        headers = {h: clean(str(message[h])) for h in _HEADERS if message[h]}
        doc.title = headers.get("Subject") or doc.title
        doc.metadata.update({k.lower().replace("-", "_"): v for k, v in headers.items()})
        if headers:
            doc.add(key_values(headers))

        body, attachments = _body_and_attachments(message)
        if body["html"] and not body["text"]:
            doc.extend(_html_blocks(body["html"], options))
        elif body["text"]:
            doc.extend(text_to_blocks(clean(body["text"]), detect_headings=False))
        else:
            doc.warn("Email had no readable body.")

        if attachments:
            doc.metadata["attachments"] = [a[0] for a in attachments]
            doc.add(heading("Attachments", 2))
            doc.add(
                list_block(
                    [
                        ListItem(f"`{name}` — {media}, {human_bytes(size)}")
                        for name, media, size in attachments
                    ]
                )
            )
        return doc


def _body_and_attachments(message):
    body = {"text": "", "html": ""}
    attachments: list[tuple[str, str, int]] = []

    for part in message.walk():
        if part.is_multipart():
            continue
        disposition = (part.get_content_disposition() or "").lower()
        content_type = part.get_content_type()
        if disposition == "attachment" or part.get_filename():
            payload = part.get_payload(decode=True) or b""
            attachments.append((part.get_filename() or "unnamed", content_type, len(payload)))
            continue
        try:
            text = part.get_content()
        except Exception:
            continue
        if content_type == "text/plain" and not body["text"]:
            body["text"] = text
        elif content_type == "text/html" and not body["html"]:
            body["html"] = text
    return body, attachments


def _html_blocks(html: str, options: ConvertOptions):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()
    return _walk_safe(soup.body or soup, options)


def _walk_safe(node, options):
    from papyrus.parsers.html import _walk

    return _walk(node, options)
