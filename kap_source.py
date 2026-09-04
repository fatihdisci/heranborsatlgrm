"""Read one KAP disclosure's own DOM and metadata, including Turkish tables."""
import io
import json
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse, urljoin
from urllib.request import Request, urlopen


def normalize(text):
    return re.sub(r"\s+", " ", text or "").strip()


class Node:
    def __init__(self, tag="root", attrs=(), parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []

    def has_class(self, name):
        return name in self.attrs.get("class", "").split()

    def nodes(self):
        yield self
        for child in self.children:
            if isinstance(child, Node): yield from child.nodes()

    def visible(self):
        node = self
        while node:
            if node.tag in {"script", "style", "button", "svg"} or node.has_class("content-en") or node.has_class("taxonomy-field-name-cell") or "display:none" in node.attrs.get("style", "").replace(" ", ""):
                return False
            node = node.parent
        return True

    def text(self):
        if not self.visible(): return ""
        return normalize(" ".join(child.text() if isinstance(child, Node) else child for child in self.children))


class Document(HTMLParser):
    VOID = {"br", "hr", "img", "meta", "link", "input", "wbr", "source", "area", "col", "embed", "param", "track"}

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.current = self.root
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in self.VOID: self.current = node

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID: self.handle_endtag(tag)

    def handle_endtag(self, tag):
        node = self.current
        while node.parent:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        if self.current.tag not in {"script", "style"}: self.current.children.append(data)


def disclosure_metadata(source, index):
    decoder = json.JSONDecoder()
    for marker in re.finditer(r"self\.__next_f\.push\(", source):
        try:
            chunk = decoder.raw_decode(source, marker.end())[0][1]
            if not isinstance(chunk, str): continue
            start = chunk.find('"disclosureBasic":')
            if start < 0: continue
            basic, end = decoder.raw_decode(chunk, start + len('"disclosureBasic":'))
            if str(basic.get("disclosureIndex")) != str(index): continue
            detail_start = chunk.find('"disclosureDetail":', end)
            extra = decoder.raw_decode(chunk, detail_start + len('"disclosureDetail":'))[0] if detail_start >= 0 else {}
            return basic, extra
        except (ValueError, TypeError, IndexError): continue
    return {}, {}


def parse_public_page(source, index):
    basic, extra = disclosure_metadata(source, index)
    document = Document(source)
    body = next((n for n in document.root.nodes() if n.attrs.get("id") == f"notification-body-scale-{index}"), None)
    if body is None: return None
    summary_node = next((n for n in body.nodes() if n.has_class("disclosureSummary")), None)
    summary = normalize(basic.get("summary") or (summary_node.text() if summary_node else ""))
    title = normalize(basic.get("title") or summary)
    paragraphs = [n.text() for n in body.nodes() if n.has_class("text-block-value") and n.text()]
    rows = []
    for row in body.nodes():
        if row.tag != "tr" or not row.visible(): continue
        cells = [n.text() for n in row.children if isinstance(n, Node) and n.tag in {"td", "th"} and n.text()]
        if len(cells) > 1: rows.append(" | ".join(cells))
    narratives = list(dict.fromkeys(paragraphs))
    # Full table values are essential for buybacks, ownership changes and amounts.
    tables = [r for r in dict.fromkeys(rows) if not any(p in r for p in narratives)]
    content = "\n".join(narratives + tables)
    has_details = any(len(p) > 80 and p not in {title, summary} for p in narratives) or any(
        re.search(r"\d|TL|USD|EUR", r) and not re.search(r"[Öö]nce|[İi]lgili|[Yy]apılan [Aa]çıklama", r) for r in tables
    )
    related = basic.get("relatedStocks") or ""
    if isinstance(related, list): related = ",".join(str(x) for x in related)
    codes = re.findall(r"\b[A-Z][A-Z0-9]{3,5}\b", related)
    if not codes:
        for row in rows:
            if "İlgili Şirketler" in row or "Related Companies" in row:
                codes = re.findall(r"\b[A-Z][A-Z0-9]{3,5}\b", row)
                break
    own = basic.get("stockCode") or ""
    if not codes and extra.get("memberType") == "IGS" and re.fullmatch(r"[A-Z][A-Z0-9]{3,5}", own): codes = [own]
    attachments = []
    for node in document.root.nodes():
        href = urljoin("https://www.kap.org.tr", node.attrs.get("href", ""))
        parsed = urlparse(href)
        if node.tag == "a" and parsed.hostname in {"www.kap.org.tr", "kap.org.tr"} and parsed.path.startswith("/tr/api/file/download/"):
            attachment = {"name": node.text(), "url": href}
            if attachment not in attachments: attachments.append(attachment)
    dkb = bool(re.search(r"pay bazında devre kesici|devre kesici uygulaması", title + " " + summary, re.I))
    detail = {
        "subject": {"tr": "Pay Bazında Devre Kesici Bildirimi" if dkb else title},
        "summary": {"tr": summary}, "content": {"tr": content},
        "relatedStocks": [{"code": c} for c in dict.fromkeys(codes)],
        "time": basic.get("publishDate", ""), "senderTitle": basic.get("companyTitle", ""),
        "link": f"https://www.kap.org.tr/tr/Bildirim/{index}", "attachments": attachments,
        "attachment_count": basic.get("attachmentCount", len(attachments)),
        "member_type": extra.get("memberType", ""), "source_complete": bool(basic and content),
        "body_has_details": has_details,
    }
    return {"disclosureIndex": str(index), "disclosureType": "DKB" if dkb else "PUBLIC"}, detail


def complete_source(detail):
    """Read text PDFs in a bounded subprocess. Never silently omit a failed file."""
    result = dict(detail)
    errors, texts = [], []
    attachments = detail.get("attachments", [])
    if detail.get("attachment_count", len(attachments)) != len(attachments): errors.append("Ek listesi eksik")
    if len(attachments) > 5: errors.append("Ek sayısı otomatik okuma sınırını aşıyor")
    for attachment in attachments[:5]:
        try:
            parsed = urlparse(attachment["url"])
            if parsed.scheme != "https" or parsed.hostname not in {"kap.org.tr", "www.kap.org.tr"}: raise ValueError("Ek adresi doğrulanamadı")
            req = Request(attachment["url"], headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=20) as response:
                if urlparse(response.url).hostname not in {"kap.org.tr", "www.kap.org.tr"}: raise ValueError("Ek yönlendirmesi doğrulanamadı")
                data = response.read(10_000_001)
            if len(data) > 10_000_000: raise ValueError("Ek boyut sınırını aşıyor")
            data = unwrap_kap_pdf(data)
            process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--pdf-text"], input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25)
            if process.returncode: raise ValueError("PDF metni eksik ya da okunamıyor")
            texts.append(f"EK: {attachment['name']}\n{process.stdout.decode('utf-8')}")
        except Exception as error:
            errors.append(f"{attachment.get('name', 'Ek')}: {type(error).__name__}")
    result["content"] = {"tr": "\n\n".join([detail.get("content", {}).get("tr", "")] + texts)}
    result["source_errors"] = errors
    result["source_complete"] = detail.get("source_complete", True) and not errors
    result["body_has_details"] = detail.get("body_has_details", True) or bool(texts)
    return result


def unwrap_kap_pdf(data):
    # KAP sometimes returns a Java-serialized byte[] containing the PDF.
    # Only remove the known serialization header; never deserialize Java objects.
    offset = data.find(b"%PDF-")
    if data.startswith(b"\xac\xed\x00\x05") and 0 < offset < 64: data = data[offset:]
    if not data.startswith(b"%PDF-"): raise ValueError("Ek PDF olarak doğrulanamadı")
    return data


if __name__ == "__main__" and "--pdf-text" in sys.argv:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(sys.stdin.buffer.read()))
    if len(reader.pages) > 40: raise ValueError("PDF page limit")
    pages = [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]
    if not pages or any(len(normalize(page)) < 20 for page in pages): raise ValueError("PDF needs visual/OCR review")
    print("\n\n".join(f"SAYFA {i + 1}\n{page}" for i, page in enumerate(pages)))
