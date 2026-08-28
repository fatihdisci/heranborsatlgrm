#!/usr/bin/env python3
"""KAP test API -> important disclosure -> Turkish draft -> Telegram."""
import argparse, base64, hashlib, hmac, html, json, os, re, secrets, sqlite3, time, tempfile, webbrowser
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlencode, urlparse
from urllib.request import Request, urlopen
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"

def load_env(path=ROOT / ".env"):
    if path.exists():
        for raw in path.read_text().splitlines():
            raw = raw.strip()
            if not raw or raw.startswith("#") or "=" not in raw: continue
            key, value = raw.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

def cfg(key, default=None): return os.getenv(key, default)

class KapClient:
    def __init__(self):
        self.base = cfg("MKK_BASE_URL", "https://apigwdev.mkk.com.tr/api/vyk").rstrip("/")
        user, password = cfg("MKK_USERNAME", ""), cfg("MKK_PASSWORD", "")
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "Accept": "application/json", "User-Agent": "kap-bot/1.0"}

    def get(self, path, params=None):
        url = self.base + path + (("?" + urlencode(params)) if params else "")
        req = Request(url, headers=self.headers)
        with urlopen(req, timeout=30) as response: return json.loads(response.read().decode("utf-8"))

    def latest(self): return int(self.get("/lastDisclosureIndex")["lastDisclosureIndex"])
    def disclosures(self, index): return self.get("/disclosures", {"disclosureIndex": index})
    def detail(self, index): return self.get(f"/disclosureDetail/{index}", {"fileType": "data"})

class PublicKapClient:
    """Reads public, production KAP disclosure pages without MKK credentials."""
    base = "https://www.kap.org.tr/tr/Bildirim/"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; KAP-Telegram-Bot/1.0)", "Accept": "text/html"}

    def detail(self, index):
        try:
            with urlopen(Request(self.base + str(index), headers=self.headers), timeout=30) as response:
                source = response.read().decode("utf-8", "replace")
        except HTTPError as error:
            if error.code == 404: return None
            raise
        # KAP's Next.js page embeds the disclosure in escaped HTML/JSON. Work
        # only inside this notification's DOM section; otherwise unrelated
        # JavaScript or third-party page text can be mistaken for a disclosure.
        source = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), source)
        source = html.unescape(source.replace("\\\"", '"').replace("\\n", " "))
        marker = f"notification-body-scale-{index}"
        start = source.find(marker)
        if start < 0: return None
        source = source[start:]
        summary = re.search(r'class="disclosureSummary[^>]*>(.*?)</div>', source, re.S)
        # Keep the match inside the related-company cell.  A broad match can
        # accidentally pick a later numeric field (for example, "18").
        company = re.search(r'Related Companies.*?<div class="gwt-Label">\[([A-Z][A-Z0-9]{1,5}(?:\s*,\s*[A-Z][A-Z0-9]{1,5})*)\]</div>', source, re.S)
        explanation = re.search(r'text-block-value[^>]*>.*?<p[^>]*>(.*?)</p>', source, re.S)
        sent_at = re.search(r'(\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2})', source)
        if not summary and not explanation: return None
        summary_text = clean(summary.group(1) if summary else explanation.group(1))
        is_circuit = "Devre Kesici" in source or "Circuit Break" in source
        item = {"disclosureIndex": str(index), "disclosureType": "DKB" if is_circuit else "PUBLIC"}
        detail = {
            "subject": {"tr": "Pay Bazında Devre Kesici Bildirimi" if is_circuit else summary_text},
            "summary": {"tr": summary_text},
            "content": {"tr": clean(explanation.group(1)) if explanation else ""},
            "relatedStocks": [{"code": code.strip()} for code in company.group(1).split(",")] if company else [],
            "time": sent_at.group(1) if sent_at else "",
            "link": self.base + str(index),
        }
        return item, detail

class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS disclosures (id INTEGER PRIMARY KEY, important INTEGER NOT NULL, telegram_sent INTEGER NOT NULL DEFAULT 0, title TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(disclosures)")}
        if "x_post_id" not in columns: self.db.execute("ALTER TABLE disclosures ADD COLUMN x_post_id TEXT")
        self.db.commit()
    def get_cursor(self, key="cursor"):
        row = self.db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone(); return int(row[0]) if row else None
    def set_cursor(self, value, key="cursor"):
        self.db.execute("INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value))); self.db.commit()
    def seen(self, ident): return self.db.execute("SELECT 1 FROM disclosures WHERE id=?", (ident,)).fetchone() is not None
    def save(self, ident, important, title):
        self.db.execute("INSERT OR IGNORE INTO disclosures(id,important,title) VALUES(?,?,?)", (ident, int(important), title)); self.db.commit()
    def telegram_sent(self, ident):
        row = self.db.execute("SELECT telegram_sent FROM disclosures WHERE id=?", (ident,)).fetchone(); return bool(row and row[0])
    def mark_telegram_sent(self, ident):
        self.db.execute("UPDATE disclosures SET telegram_sent=1 WHERE id=?", (ident,)); self.db.commit()
    def x_posted(self, ident):
        row = self.db.execute("SELECT x_post_id FROM disclosures WHERE id=?", (ident,)).fetchone(); return bool(row and row[0])
    def mark_x_posted(self, ident, post_id):
        self.db.execute("UPDATE disclosures SET x_post_id=? WHERE id=?", (str(post_id), ident)); self.db.commit()

KEYWORDS = re.compile(r"temettü|bedelli|bedelsiz|sermaye artır|geri alım|ihale sonucu|sözleşme imzalan|iş ilişkisi|yatırım projesi|kapasite artış|birleşme|satın alma|finansal sonuç|net kâr|net zarar|iflas|konkordato|geri alım programı|pay alım satım|özel durum|devre kesici|sürekli işleme ara|tek fiyat emir toplama|faaliyet.*durdur|imkansız hale", re.I)
NOISE = re.compile(r"borsa dışı repo|yatırımcı bilgi formu|yönetim kurulu komiteleri|varant|itfa fiyat|summernote|project|issues", re.I)
SPECIAL_EVENTS = (
    ("circuit", "DEVRE KESİCİ", re.compile(r"devre kesici|sürekli işleme ara|tek fiyat emir toplama", re.I)),
    ("buyback", "PAY GERİ ALIMI", re.compile(r"payların geri alınması|pay geri alım|geri alınan pay", re.I)),
    ("business", "YENİ İŞ İLİŞKİSİ", re.compile(r"yeni iş ilişkisi|sözleşme imzalanması|ihale sonucu", re.I)),
    ("share_trade", "PAY ALIM SATIMI", re.compile(r"pay alım satım bildirimi|pay satış bildirimi|sermaye piyasası aracı alım satım", re.I)),
    ("suspension", "FAALİYET DURDURMA", re.compile(r"faaliyetlerin kısmen veya tamamen durdurulması|faaliyet.*durdurul|imkansız hale", re.I)),
)
def clean(value):
    text = re.sub(r"<[^>]+>", " ", html.unescape(value or "")); return re.sub(r"\s+", " ", text).strip()
def text_of(obj, lang="tr"):
    return obj.get(lang) if isinstance(obj, dict) else (obj or "")
def stocks(detail):
    # BIST symbols may contain digits (for example AVGY0), but a number alone
    # is never a valid symbol and must not become a hashtag such as #18.
    return [x.get("code") for x in detail.get("relatedStocks", []) if re.fullmatch(r"[A-Z][A-Z0-9]{1,5}", x.get("code", ""))]
def disclosure_text(detail):
    return " ".join(clean(text_of(detail.get(part))) for part in ("subject", "summary", "content"))
def special_event(detail):
    joined = disclosure_text(detail)
    for ident, label, pattern in SPECIAL_EVENTS:
        if pattern.search(joined): return ident, label
    return None
def summary_line(detail, limit=165):
    text = clean(text_of(detail.get("summary")) or text_of(detail.get("content")) or text_of(detail.get("subject")))
    if len(text) <= limit: return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(".,;:") + "…"
def tweet_only(text):
    """Keep the Telegram payload ready to paste into X, with no meta labels."""
    text = re.sub(r"https?://\S+", "", text, flags=re.I)
    text = clean(text).strip().strip('"“”')
    text = re.sub(r"^(tweet|tweet metni|taslak|x paylaşımı)\s*[:\-–]\s*", "", text, flags=re.I)
    return text.strip().strip('"“”')[:280].strip()
def required_tags(text, codes):
    """Guarantee stock codes and market tags while staying within X's limit."""
    tags = [f"#{code}" for code in codes] + ["#borsa", "#bist"]
    missing = [tag for tag in tags if tag.lower() not in text.lower()]
    if not missing: return text[:280]
    suffix = " " + " ".join(missing)
    room = 280 - len(suffix)
    base = text[:room].rstrip()
    if len(text) > room and " " in base: base = base.rsplit(" ", 1)[0]
    return (base + suffix).strip()
def is_important(item, detail):
    joined = " ".join([item.get("disclosureType", ""), text_of(detail.get("subject")), text_of(detail.get("summary")), detail.get("senderTitle", "")])
    # Every published message must identify a real listed company.  This
    # prevents fund notices, forms and page noise from becoming stock alerts.
    if not stocks(detail) or NOISE.search(joined): return False
    return bool(special_event(detail)) or item.get("disclosureType") == "DKB" or bool(KEYWORDS.search(joined))

def draft(detail):
    """A compact, verbatim notification card; no AI-generated wording."""
    title = clean(text_of(detail.get("subject")) or text_of(detail.get("summary")))
    codes = " ".join(f"#{code}" for code in stocks(detail))
    return "\n".join(part for part in (codes, title, detail.get("link", "")) if part)

def circuit_tweet(code):
    """The ready-to-post text paired with every circuit-breaker card."""
    return f"#{code} Devre kesti. #borsa #bist"

def event_tweet(event, detail):
    codes = stocks(detail)
    if event == "circuit": return circuit_tweet(codes[0])
    titles = {"buyback": "Pay geri alımı", "business": "Yeni iş ilişkisi", "share_trade": "Pay alım satım bildirimi", "suspension": "Faaliyet durdurma kararı"}
    body = f"{titles[event]}: {summary_line(detail, 180)}"
    return required_tags(tweet_only(body), codes)

def telegram_send(text):
    token, chat = cfg("TELEGRAM_BOT_TOKEN"), cfg("TELEGRAM_CHAT_ID")
    if not token or not chat: logging.warning("Telegram ayarları eksik; bildirim atlanıyor"); return False
    data = urlencode({"chat_id":chat, "text":text, "disable_web_page_preview":"true"}).encode()
    with urlopen(Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data), timeout=30) as r: return json.loads(r.read().decode()).get("ok", False)

def yahoo_chart(code):
    """Return delayed intraday price data for a BIST symbol from Yahoo Finance."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.IS?range=1d&interval=5m"
    with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    result = payload["chart"]["result"][0]
    meta, quote = result["meta"], result["indicators"]["quote"][0]
    points = [value for value in quote.get("close", []) if isinstance(value, (int, float))]
    price = meta.get("regularMarketPrice")
    previous = meta.get("chartPreviousClose") or meta.get("previousClose")
    if not isinstance(price, (int, float)) or not isinstance(previous, (int, float)) or not points: raise ValueError("Yahoo fiyat verisi eksik")
    return {"name": meta.get("longName") or code, "price": price, "change_pct": (price - previous) / previous * 100, "points": points}

def card_font(size, bold=False):
    paths = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
    ]
    for path in paths:
        if Path(path).exists(): return ImageFont.truetype(path, size)
    return ImageFont.load_default()

def card_background(filename, size):
    """Fit one of the supplied branded background images to the card canvas."""
    path = ASSETS / filename
    if not path.exists(): return Image.new("RGB", size, "#FAFAF8")
    with Image.open(path) as original:
        return ImageOps.fit(original.convert("RGB"), size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))

def translucent_panel(image, bounds, alpha=225):
    overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
    ImageDraw.Draw(overlay).rounded_rectangle(bounds, radius=30, fill=(255, 255, 255, alpha))
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")

def wrap_card_text(draw, text, font, max_width, max_lines):
    words, lines, line = text.split(), [], ""
    for word in words:
        candidate = (line + " " + word).strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
            if line: lines.append(line)
            line = word
            if len(lines) == max_lines: break
        else: line = candidate
    if line and len(lines) < max_lines: lines.append(line)
    return lines

def render_circuit_card(code, market):
    """Create a branded horizontal 1200×675 circuit-breaker card."""
    image = translucent_panel(card_background("dkb-background.jpg", (1200, 675)), (55, 48, 1145, 610), 218)
    draw = ImageDraw.Draw(image)
    dark, muted, red = "#141414", "#747474", "#D65A4A"
    draw.text((90, 82), "DEVRE KESİCİ", font=card_font(30, True), fill=red)
    draw.text((90, 126), f"#{code}", font=card_font(64, True), fill=dark)
    draw.text((92, 205), str(market["name"])[:38], font=card_font(27), fill=muted)
    price = (f"{market['price']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")) + " TL"
    draw.text((90, 250), price, font=card_font(54, True), fill=dark)
    change = f"%{market['change_pct']:+.2f}".replace(".", ",")
    draw.text((375, 270), change, font=card_font(30, True), fill=red if market["change_pct"] < 0 else "#27805C")
    points = market["points"]
    low, high = min(points), max(points)
    left, top, right, bottom = 90, 350, 1110, 535
    if high == low: high += 1
    coords = [(left + i * (right-left)/(len(points)-1), bottom - (point-low)/(high-low)*(bottom-top)) for i, point in enumerate(points)] if len(points) > 1 else []
    if coords: draw.line(coords, fill=red, width=6, joint="curve")
    draw.line((left, bottom, right, bottom), fill="#ECEAE6", width=2)
    draw.text((90, 560), "İşlemler tek fiyat yöntemiyle devam ediyor.", font=card_font(23), fill=muted)
    handle = tempfile.NamedTemporaryFile(prefix=f"kap-{code}-", suffix=".png", delete=False)
    handle.close(); image.save(handle.name, "PNG", optimize=True)
    return handle.name

def render_event_card(event, label, detail):
    """Render a branded vertical 1080×1920 card for high-signal KAP events."""
    codes = stocks(detail)
    image = translucent_panel(card_background("event-background.jpg", (1080, 1920)), (54, 70, 1026, 1580), 220)
    draw = ImageDraw.Draw(image)
    accent = {"buyback": "#3B82C4", "business": "#27805C", "share_trade": "#9C6BDB", "suspension": "#D65A4A"}[event]
    badge_width = max(305, draw.textbbox((0, 0), label, font=card_font(30, True))[2] + 72)
    draw.rounded_rectangle((105, 145, 105 + badge_width, 210), radius=16, fill=accent)
    draw.text((138, 160), label, font=card_font(30, True), fill="#FFFFFF")
    code_font = card_font(76, True)
    code_lines = wrap_card_text(draw, "  ".join(f"#{code}" for code in codes), code_font, 840, 2)
    for index, line in enumerate(code_lines): draw.text((105, 280 + index * 90), line, font=code_font, fill="#141414")
    summary_font = card_font(48)
    summary = summary_line(detail, 390)
    lines = wrap_card_text(draw, summary, summary_font, 840, 7)
    summary_y = 505 if len(code_lines) == 1 else 590
    for index, line in enumerate(lines): draw.text((105, summary_y + index * 67), line, font=summary_font, fill="#292929")
    draw.line((105, 1480, 975, 1480), fill="#D9D7D2", width=2)
    draw.text((105, 1518), "KAP BİLDİRİMİ", font=card_font(28, True), fill="#747474")
    handle = tempfile.NamedTemporaryFile(prefix=f"kap-{event}-", suffix=".png", delete=False)
    handle.close(); image.save(handle.name, "PNG", optimize=True)
    return handle.name

def telegram_send_photo(path, caption):
    token, chat = cfg("TELEGRAM_BOT_TOKEN"), cfg("TELEGRAM_CHAT_ID")
    if not token or not chat: logging.warning("Telegram ayarları eksik; görsel atlanıyor"); return False
    boundary = "----KapBotBoundary"
    data = Path(path).read_bytes()
    body = b"".join([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat}\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"kap-card.png\"\r\nContent-Type: image/png\r\n\r\n".encode(), data, f"\r\n--{boundary}--\r\n".encode(),
    ])
    request = Request(f"https://api.telegram.org/bot{token}/sendPhoto", data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urlopen(request, timeout=30) as response: return json.loads(response.read().decode()).get("ok", False)

def oauth_quote(value): return quote(str(value), safe="~")

def x_oauth_header(method, url):
    key, secret = cfg("X_API_KEY"), cfg("X_API_KEY_SECRET")
    token, token_secret = cfg("X_ACCESS_TOKEN"), cfg("X_ACCESS_TOKEN_SECRET")
    if not all((key, secret, token, token_secret)): raise ValueError("X API anahtarları eksik")
    oauth = {
        "oauth_consumer_key": key, "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1", "oauth_timestamp": str(int(time.time())),
        "oauth_token": token, "oauth_version": "1.0",
    }
    parsed = urlparse(url)
    pairs = parse_qsl(parsed.query, keep_blank_values=True) + list(oauth.items())
    encoded = "&".join(f"{oauth_quote(k)}={oauth_quote(v)}" for k, v in sorted(pairs, key=lambda pair: (oauth_quote(pair[0]), oauth_quote(pair[1]))))
    base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    base = "&".join((method.upper(), oauth_quote(base_url), oauth_quote(encoded)))
    signing_key = f"{oauth_quote(secret)}&{oauth_quote(token_secret)}"
    oauth["oauth_signature"] = base64.b64encode(hmac.new(signing_key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{oauth_quote(k)}="{oauth_quote(v)}"' for k, v in sorted(oauth.items()))

_x_oauth2_access_token = None

def x_bearer_token():
    """Use the short-lived OAuth 2 token when supplied, else OAuth 1.0a."""
    global _x_oauth2_access_token
    if _x_oauth2_access_token is None:
        _x_oauth2_access_token = cfg("X_OAUTH2_ACCESS_TOKEN")
    return _x_oauth2_access_token

def update_env_secret(key, value):
    """Persist a rotated OAuth token locally; .env is intentionally ignored."""
    path = ROOT / ".env"
    lines = path.read_text().splitlines() if path.exists() else []
    pattern = re.compile(rf"^{re.escape(key)}=")
    replacement = f"{key}={value}"
    replaced = False
    for index, line in enumerate(lines):
        if pattern.match(line):
            lines[index], replaced = replacement, True
            break
    if not replaced: lines.append(replacement)
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o600)

def refresh_x_oauth2_token():
    """Refresh OAuth 2 credentials and retain the rotating refresh token."""
    refresh_token = cfg("X_OAUTH2_REFRESH_TOKEN")
    if not refresh_token: raise ValueError("X OAuth 2 yenileme ayarları eksik")
    result = x_oauth2_token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})
    global _x_oauth2_access_token
    _x_oauth2_access_token = result["access_token"]
    update_env_secret("X_OAUTH2_ACCESS_TOKEN", result["access_token"])
    if result.get("refresh_token"):
        update_env_secret("X_OAUTH2_REFRESH_TOKEN", result["refresh_token"])
    return _x_oauth2_access_token

def x_oauth2_token_request(payload):
    """Exchange or refresh user-context OAuth 2 credentials."""
    client_id = cfg("X_OAUTH2_CLIENT_ID")
    if not client_id: raise ValueError("X_OAUTH2_CLIENT_ID eksik")
    body = dict(payload)
    headers = {"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "heranborsa-kap-bot/1.0"}
    client_secret = cfg("X_OAUTH2_CLIENT_SECRET")
    if client_secret:
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        headers["Authorization"] = f"Basic {basic}"
    else:
        body.setdefault("client_id", client_id)
    request = Request("https://api.x.com/2/oauth2/token", data=urlencode(body).encode(), headers=headers, method="POST")
    with urlopen(request, timeout=30) as response: return json.loads(response.read().decode("utf-8"))

def x_authorization_url(redirect_uri, state, verifier):
    client_id = cfg("X_OAUTH2_CLIENT_ID")
    if not client_id: raise ValueError("X_OAUTH2_CLIENT_ID eksik")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    params = {
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
        "scope": "tweet.read tweet.write users.read offline.access media.write",
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
    }
    return "https://x.com/i/oauth2/authorize?" + urlencode(params)

def authorize_x_oauth2():
    """Run once locally to obtain an OAuth 2 *user-context* token for X."""
    redirect_uri = cfg("X_OAUTH2_REDIRECT_URI", "http://127.0.0.1:8787/callback")
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or not parsed.port:
        raise ValueError("X_OAUTH2_REDIRECT_URI yerel http://127.0.0.1:PORT/callback olmalı")
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    auth_url = x_authorization_url(redirect_uri, state, verifier)
    received = {}
    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            values = dict(parse_qsl(urlparse(self.path).query, keep_blank_values=True))
            received.update(values)
            text = "Yetkilendirme alındı. Bu sekmeyi kapatabilirsiniz."
            self.send_response(200); self.send_header("Content-Type", "text/plain; charset=utf-8"); self.end_headers(); self.wfile.write(text.encode())
        def log_message(self, format, *args): pass
    server = HTTPServer((parsed.hostname, parsed.port), CallbackHandler)
    server.timeout = 300
    logging.info("X kullanıcı yetkilendirmesi tarayıcıda açılıyor")
    webbrowser.open(auth_url)
    while "code" not in received and "error" not in received:
        server.handle_request()
    server.server_close()
    if received.get("state") != state or received.get("error"):
        raise ValueError("X kullanıcı yetkilendirmesi tamamlanamadı")
    result = x_oauth2_token_request({
        "grant_type": "authorization_code", "code": received["code"],
        "redirect_uri": redirect_uri, "code_verifier": verifier,
    })
    global _x_oauth2_access_token
    _x_oauth2_access_token = result["access_token"]
    update_env_secret("X_OAUTH2_ACCESS_TOKEN", result["access_token"])
    if result.get("refresh_token"): update_env_secret("X_OAUTH2_REFRESH_TOKEN", result["refresh_token"])
    return x_verify_identity()

def x_request(method, url, payload=None, retried=False):
    data = json.dumps(payload).encode() if payload is not None else None
    bearer = x_bearer_token()
    headers = {"Authorization": f"Bearer {bearer}" if bearer else x_oauth_header(method, url), "Content-Type": "application/json", "User-Agent": "heranborsa-kap-bot/1.0"}
    try:
        with urlopen(Request(url, data=data, headers=headers, method=method), timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        # OAuth 2 access tokens expire after two hours.  Refresh once and retry
        # the exact same API request; never retry a post more than once.
        if error.code == 401 and bearer and not retried and cfg("X_OAUTH2_REFRESH_TOKEN"):
            refresh_x_oauth2_token()
            return x_request(method, url, payload, retried=True)
        raise

def x_verify_identity():
    return x_request("GET", "https://api.x.com/2/users/me")["data"]

def x_upload_image(path):
    encoded = base64.b64encode(Path(path).read_bytes()).decode()
    response = x_request("POST", "https://api.x.com/2/media/upload", {"media": encoded, "media_category": "tweet_image", "media_type": "image/png"})
    return response["data"]["id"]

def x_post_circuit_breaker(code, image_path):
    media_id = x_upload_image(image_path)
    response = x_request("POST", "https://api.x.com/2/tweets", {"text": f"#{code} Devre kesti. #borsa #bist", "media": {"media_ids": [media_id]}})
    return response["data"]["id"]

def deliver(store, ident, item, detail, dry_run):
    important = is_important(item, detail)
    store.save(ident, important, text_of(detail.get("subject")))
    if not important: return 0
    event = special_event(detail)
    is_circuit = event is not None and event[0] == "circuit"
    message = event_tweet(event[0], detail) if event else draft(detail)
    card = None
    try:
        if is_circuit: card = render_circuit_card(stocks(detail)[0], yahoo_chart(stocks(detail)[0]))
        elif event: card = render_event_card(event[0], event[1], detail)
    except Exception as error:
        logging.warning("Devre kesici görseli üretilemedi (%s); sade metin gönderiliyor", error)
    if dry_run: logging.info("DRY RUN:\n%s", message)
    elif not store.telegram_sent(ident) and (telegram_send_photo(card, message) if card else telegram_send(message)):
        store.mark_telegram_sent(ident)
        logging.info("Telegram gönderildi: %s", ident)
    if card and cfg("X_AUTO_POST_DKB", "false").lower() == "true" and not store.x_posted(ident) and not dry_run:
        try:
            post_id = x_post_circuit_breaker(stocks(detail)[0], card)
            store.mark_x_posted(ident, post_id)
            logging.info("X paylaşımı yapıldı: %s", ident)
        except Exception:
            logging.exception("X paylaşımı başarısız: %s", ident)
    if card: Path(card).unlink(missing_ok=True)
    return 1

def run_public_once(store, dry_run=False):
    cursor_key = "public_cursor"
    cursor = store.get_cursor(cursor_key)
    if cursor is None:
        cursor = int(cfg("PUBLIC_INITIAL_INDEX", "0"))
        if cursor <= 0: raise ValueError("PUBLIC_INITIAL_INDEX pozitif bir KAP bildirim ID'si olmalı")
        store.set_cursor(cursor, cursor_key)
        logging.info("Canlı KAP başlangıç imleci: %s", cursor)
        return 0
    ident = cursor + 1
    result = PublicKapClient().detail(ident)
    if result is None:
        logging.info("Yeni canlı KAP bildirimi yok (beklenen ID %s)", ident)
        return 0
    item, detail = result
    count = deliver(store, ident, item, detail, dry_run)
    store.set_cursor(ident, cursor_key)
    return count

def run_once(store, dry_run=False):
    client, latest = KapClient(), None
    latest = client.latest(); cursor = store.get_cursor()
    if cursor is None:
        initial = cfg("INITIAL_CURSOR", "latest")
        cursor = latest if initial == "latest" else int(initial)
        store.set_cursor(cursor); logging.info("Başlangıç imleci: %s", cursor); return 0
    if latest <= cursor: logging.info("Yeni bildirim yok (son ID %s)", cursor); return 0
    count = 0
    for item in client.disclosures(cursor + 1):
        ident = int(item["disclosureIndex"])
        if ident <= cursor or store.seen(ident): continue
        detail = client.detail(ident); count += deliver(store, ident, item, detail, dry_run)
        store.set_cursor(ident)
    # The endpoint can return at most a page of disclosures. Advance only to
    # the highest disclosure actually inspected, so a busy period cannot skip IDs.
    if count or latest > cursor:
        inspected = store.db.execute("SELECT MAX(id) FROM disclosures").fetchone()[0]
        if inspected is not None: store.set_cursor(min(int(inspected), latest))
    return count

def main():
    load_env(); logging.basicConfig(level=getattr(logging, cfg("LOG_LEVEL", "INFO").upper()), format="%(asctime)s %(levelname)s %(message)s")
    parser=argparse.ArgumentParser(); parser.add_argument("--once", action="store_true"); parser.add_argument("--dry-run", action="store_true"); parser.add_argument("--x-authorize", action="store_true"); parser.add_argument("--x-verify", action="store_true"); args=parser.parse_args()
    if args.x_authorize:
        profile = authorize_x_oauth2(); logging.info("X kullanıcı yetkilendirmesi tamamlandı: @%s", profile.get("username")); return
    if args.x_verify:
        profile = x_verify_identity(); logging.info("X bağlantısı doğrulandı: @%s", profile.get("username")); return
    store=Store(cfg("DATABASE_PATH", "data/kap_bot.sqlite3"))
    while True:
        try: run_public_once(store, args.dry_run) if cfg("KAP_SOURCE", "public").lower() == "public" else run_once(store, args.dry_run)
        except (HTTPError, URLError, TimeoutError, KeyError, ValueError): logging.exception("KAP kontrolü başarısız")
        except Exception: logging.exception("Beklenmeyen hata")
        if args.once: break
        time.sleep(int(cfg("POLL_INTERVAL_SECONDS", "60")))
if __name__ == "__main__": main()
