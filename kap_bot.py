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

class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS disclosures (id INTEGER PRIMARY KEY, important INTEGER NOT NULL, telegram_sent INTEGER NOT NULL DEFAULT 0, title TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        self.db.commit()
    def get_cursor(self):
        row = self.db.execute("SELECT value FROM state WHERE key='cursor'").fetchone(); return int(row[0]) if row else None
    def set_cursor(self, value):
        self.db.execute("INSERT INTO state(key,value) VALUES('cursor',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(value),)); self.db.commit()
    def seen(self, ident): return self.db.execute("SELECT 1 FROM disclosures WHERE id=?", (ident,)).fetchone() is not None
    def save(self, ident, important, title):
        self.db.execute("INSERT OR IGNORE INTO disclosures(id,important,title) VALUES(?,?,?)", (ident, int(important), title)); self.db.commit()

KEYWORDS = re.compile(r"temettü|bedelli|bedelsiz|sermaye artır|geri alım|ihale|sözleşme|yatırım|kapasite|iş ilişkisi|birleşme|satın alma|finansal sonuç|kâr|zarar|iflas|konkordato|yönetim kurulu|istifa|pay alım|özel durum|devre kesici|sürekli işleme ara|tek fiyat emir toplama", re.I)
def clean(value):
    text = re.sub(r"<[^>]+>", " ", html.unescape(value or "")); return re.sub(r"\s+", " ", text).strip()
def text_of(obj, lang="tr"):
    return obj.get(lang) if isinstance(obj, dict) else (obj or "")
def stocks(detail):
    return [x.get("code") for x in detail.get("relatedStocks", []) if x.get("code")]
def tweet_only(text):
    """Keep the Telegram payload ready to paste into X, with no meta labels."""
    text = clean(text).strip().strip('"“”')
    text = re.sub(r"^(tweet|tweet metni|taslak|x paylaşımı)\s*[:\-–]\s*", "", text, flags=re.I)
    return text.strip().strip('"“”')[:280].strip()
def is_important(item, detail):
    joined = " ".join([item.get("disclosureType", ""), text_of(detail.get("subject")), text_of(detail.get("summary")), detail.get("senderTitle", "")])
    return item.get("disclosureType") in {"ODA", "CA", "OD", "FR", "DGK", "DKB"} or bool(KEYWORDS.search(joined)) or bool(stocks(detail))

def draft(detail):
    subject, summary = clean(text_of(detail.get("subject"))), clean(text_of(detail.get("summary")))
    codes = " ".join(f"#{x}" for x in stocks(detail))
    api_key = cfg("AI_API_KEY")
    if api_key:
        prompt = "Türkçe borsa gündemini doğal ve akıcı anlatan deneyimli bir editörsün. Verilen KAP bildiriminden en fazla 280 karakterlik, kopyalayıp doğrudan X'te paylaşılabilecek tek bir tweet yaz. Resmî bülten ya da yapay zekâ gibi konuşma; kısa, sade ve doğal piyasa dili kullan. Yatırım tavsiyesi, tahmin, abartı veya uydurma bilgi ekleme. Varsa hisse kodunu # etiketiyle kullan ve KAP bağlantısını metne ekle. Kesinlikle başlık, 'Tweet:', 'Taslak:', açıklama, tırnak işareti veya alternatif sürüm yazma; yalnızca paylaşılacak metni döndür.\n\n" + json.dumps({"subject": subject, "summary": summary, "stocks": stocks(detail), "link": detail.get("link")}, ensure_ascii=False)
        # GPT-5.6 family uses the current Responses API. Its compact output is
        # extracted below without relying on a particular SDK.
        body = json.dumps({"model": cfg("AI_MODEL", "gpt-5.6-luna"), "input":prompt, "max_output_tokens":180, "store":False}).encode()
        req = Request(cfg("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/responses", data=body, headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"})
        try:
            with urlopen(req, timeout=45) as r:
                result=json.loads(r.read().decode())
            output = result.get("output_text")
            if not output:
                output = "".join(part.get("text", "") for item in result.get("output", []) for part in item.get("content", []) if part.get("type") == "output_text")
            if output: return tweet_only(output)
            raise ValueError("AI yanıtında metin yok")
        except Exception as error: logging.warning("AI taslağı üretilemedi (%s); yerel taslağa geçiliyor", error)
    body = f"{codes + ' ' if codes else ''}{subject or summary}"
    return tweet_only(body + (f" — {summary}" if summary and summary.lower() != subject.lower() else "") + f"\n{detail.get('link','')}")

def telegram_send(text):
    token, chat = cfg("TELEGRAM_BOT_TOKEN"), cfg("TELEGRAM_CHAT_ID")
    if not token or not chat: logging.warning("Telegram ayarları eksik; bildirim atlanıyor"); return False
    data = urlencode({"chat_id":chat, "text":text, "disable_web_page_preview":"true"}).encode()
    with urlopen(Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data), timeout=30) as r: return json.loads(r.read().decode()).get("ok", False)

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
        detail = client.detail(ident); important = is_important(item, detail); store.save(ident, important, text_of(detail.get("subject")))
        if important:
            message = draft(detail)
            if dry_run: logging.info("DRY RUN:\n%s", message)
            elif telegram_send(message): logging.info("Telegram gönderildi: %s", ident)
            count += 1
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
        try: run_once(store, args.dry_run)
        except (HTTPError, URLError, TimeoutError, KeyError, ValueError): logging.exception("KAP kontrolü başarısız")
        except Exception: logging.exception("Beklenmeyen hata")
        if args.once: break
        time.sleep(int(cfg("POLL_INTERVAL_SECONDS", "60")))
if __name__ == "__main__": main()
