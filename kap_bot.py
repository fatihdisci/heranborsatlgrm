#!/usr/bin/env python3
"""KAP test API -> important disclosure -> Turkish draft -> Telegram."""
import argparse, base64, html, json, logging, os, re, sqlite3, time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent

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

KEYWORDS = re.compile(r"temettü|bedelli|bedelsiz|sermaye artır|geri alım|ihale sonucu|sözleşme imzalan|iş ilişkisi|yatırım projesi|kapasite artış|birleşme|satın alma|finansal sonuç|net kâr|net zarar|iflas|konkordato|geri alım programı|pay alım satım|özel durum|devre kesici|sürekli işleme ara|tek fiyat emir toplama", re.I)
NOISE = re.compile(r"borsa dışı repo|yatırımcı bilgi formu|yönetim kurulu komiteleri|varant|itfa fiyat|summernote|project|issues", re.I)
def clean(value):
    text = re.sub(r"<[^>]+>", " ", html.unescape(value or "")); return re.sub(r"\s+", " ", text).strip()
def text_of(obj, lang="tr"):
    return obj.get(lang) if isinstance(obj, dict) else (obj or "")
def stocks(detail):
    # BIST symbols may contain digits (for example AVGY0), but a number alone
    # is never a valid symbol and must not become a hashtag such as #18.
    return [x.get("code") for x in detail.get("relatedStocks", []) if re.fullmatch(r"[A-Z][A-Z0-9]{1,5}", x.get("code", ""))]
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
    return item.get("disclosureType") == "DKB" or bool(KEYWORDS.search(joined))

def circuit_tweet(detail):
    """Circuit-breaker notices are time-sensitive; do not risk an AI fragment."""
    codes = stocks(detail)
    code = codes[0]
    content = clean(text_of(detail.get("content")) or text_of(detail.get("summary")))
    resume = re.search(r"(?:işlemlere|işlemler)\s+(\d{1,2}:\d{2}:\d{2}).{0,30}?devam", content, re.I)
    text = f"⚠️ {code}'ta devre kesici devrede. Sürekli işleme ara verildi, tek fiyat emir toplama başladı."
    if resume: text += f" İşlemler {resume.group(1)}'de yeniden başlayacak."
    return required_tags(text, codes)

def draft(detail):
    subject, summary = clean(text_of(detail.get("subject"))), clean(text_of(detail.get("summary")))
    content = clean(text_of(detail.get("content")))
    stock_codes = stocks(detail)
    codes = " ".join(f"#{x}" for x in stock_codes)
    if re.search(r"devre kesici|sürekli işleme ara", f"{subject} {summary} {content}", re.I):
        return circuit_tweet(detail)
    api_key = cfg("AI_API_KEY")
    if api_key:
        prompt = "Türkçe borsa gündemini takip eden gerçek bir yatırımcı gibi yaz. Verilen KAP bildiriminden 110-220 karakterlik, tek parça ve doğrudan X'te paylaşılabilecek doğal bir tweet üret. Açıklama detayındaki somut bilgiyi bir kez, sade biçimde anlat; başlığı tekrar etme, cümleleri uzatma ve resmî bülten/yapay zekâ tonu kullanma. Konuya uygun tek emoji kullan. Yatırım tavsiyesi, tahmin, abartı veya uydurma bilgi ekleme. İlgili her hisse kodunu # etiketiyle, ayrıca #borsa ve #bist etiketlerini kesinlikle yaz. KAP bağlantısı veya başka URL yazma. Kesinlikle başlık, 'Tweet:', 'Taslak:', açıklama, tırnak işareti veya alternatif sürüm yazma; yalnızca paylaşılacak metni döndür.\n\n" + json.dumps({"subject": subject, "summary": summary, "detail": content, "stocks": stock_codes}, ensure_ascii=False)
        # GPT-5.6 family uses the current Responses API. Its compact output is
        # extracted below without relying on a particular SDK.
        body = json.dumps({"model": cfg("AI_MODEL", "gpt-5.6-luna"), "input":prompt, "max_output_tokens":180, "store":False}).encode()
        req = Request(cfg("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/responses", data=body, headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"})
        try:
            with urlopen(req, timeout=45) as r:
                result=json.loads(r.read().decode())
            if result.get("status") != "completed":
                raise ValueError(f"AI yanıtı tamamlanmadı: {result.get('status')}")
            output = result.get("output_text")
            if not output:
                output = "".join(part.get("text", "") for item in result.get("output", []) for part in item.get("content", []) if part.get("type") == "output_text")
            if output: return required_tags(tweet_only(output), stock_codes)
            raise ValueError("AI yanıtında metin yok")
        except Exception as error: logging.warning("AI taslağı üretilemedi (%s); yerel taslağa geçiliyor", error)
    body = f"📌 {codes + ' ' if codes else ''}{subject or summary}"
    extra = content or summary
    return required_tags(tweet_only(body + (f" — {extra}" if extra and extra.lower() != subject.lower() else "")), stock_codes)

def telegram_send(text):
    token, chat = cfg("TELEGRAM_BOT_TOKEN"), cfg("TELEGRAM_CHAT_ID")
    if not token or not chat: logging.warning("Telegram ayarları eksik; bildirim atlanıyor"); return False
    data = urlencode({"chat_id":chat, "text":text, "disable_web_page_preview":"true"}).encode()
    with urlopen(Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data), timeout=30) as r: return json.loads(r.read().decode()).get("ok", False)

def deliver(store, ident, item, detail, dry_run):
    important = is_important(item, detail)
    store.save(ident, important, text_of(detail.get("subject")))
    if not important or store.telegram_sent(ident): return 0
    message = draft(detail)
    if dry_run: logging.info("DRY RUN:\n%s", message)
    elif telegram_send(message):
        store.mark_telegram_sent(ident)
        logging.info("Telegram gönderildi: %s", ident)
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
    parser=argparse.ArgumentParser(); parser.add_argument("--once", action="store_true"); parser.add_argument("--dry-run", action="store_true"); args=parser.parse_args()
    store=Store(cfg("DATABASE_PATH", "data/kap_bot.sqlite3"))
    while True:
        try: run_public_once(store, args.dry_run) if cfg("KAP_SOURCE", "public").lower() == "public" else run_once(store, args.dry_run)
        except (HTTPError, URLError, TimeoutError, KeyError, ValueError): logging.exception("KAP kontrolü başarısız")
        except Exception: logging.exception("Beklenmeyen hata")
        if args.once: break
        time.sleep(int(cfg("POLL_INTERVAL_SECONDS", "60")))
if __name__ == "__main__": main()
