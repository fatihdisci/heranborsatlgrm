# KAP Haber Botu

Mac mini üzerinde KAP bildirimlerini izler. İzin listesindeki DKB'leri X'te otomatik paylaşır. DKB dışındaki seçili bildirimleri özetlemeden ve görselleştirmeden; hisse kodu, KAP başlığı, bildirim türü ve bağlantı olarak tek Telegram mesajında gönderir. Sistemde AI servisi kullanılmaz. DKB dışı X paylaşımı kapalıdır.

## Klasör yapısı

```text
kap-bot/
├── kap_bot.py             # Bot ve CLI
├── .env.example           # Ayar şablonu
├── requirements.txt       # Pillow
├── kap_source.py          # Resmi KAP başlığı, türü ve hisse kodu
├── launchd/com.fatih.kapbot.plist.template
├── data/                  # SQLite burada oluşur
└── logs/                  # launchd logları
```

## Kurulum

1. Terminal'de bu klasöre girin:

   ```bash
   cd /Users/fatihdisci/Documents/Codex/2026-08-26/referenced-chatgpt-conversation-this-is-an/kap-bot
   cp .env.example .env
   chmod 600 .env
   open -e .env
   ```

2. `python3 -m venv .venv` ve `.venv/bin/python -m pip install -r requirements.txt` komutlarıyla bağımlılıkları kurun. `.env` içinde `KAP_SOURCE=public` ve `PUBLIC_INITIAL_INDEX` değerini başlangıç KAP ID'si olarak ayarlayın. Telegram token ve chat_id değerlerini ekleyin.

3. Önce bağlantıyı tek sefer test edin:

   ```bash
   .venv/bin/python kap_bot.py --once --dry-run
   ```

   İlk çalıştırmada `PUBLIC_INITIAL_INDEX` yalnızca başlangıç noktası olarak kaydedilir; eski bildirimler gönderilmez. Bot sonraki KAP ID'sini takip eder.

4. Sürekli önizleme:

   ```bash
   .venv/bin/python kap_bot.py
   ```

## launchd ile 7/24 çalışma

Şablondaki `/ABSOLUTE/PATH/TO/kap-bot` ve kullanıcı adını gerçek değerlerle değiştirin. Ardından:

```bash
mkdir -p data logs
sed -e "s|/ABSOLUTE/PATH/TO/kap-bot|$(pwd)|g" -e "s|/ABSOLUTE/PATH/TO/PYTHON3|$(pwd)/.venv/bin/python|g" \
  launchd/com.fatih.kapbot.plist.template > "$HOME/Library/LaunchAgents/com.fatihdisci.kapbot.plist"
launchctl bootout "gui/$(id -u)"/com.fatihdisci.kapbot 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.fatihdisci.kapbot.plist"
launchctl kickstart -k "gui/$(id -u)/com.fatihdisci.kapbot"
```

Durumu görmek için `launchctl print gui/$(id -u)/com.fatihdisci.kapbot`, logları görmek için `tail -f logs/kap-bot.log` kullanın. `KeepAlive` sayesinde çökme sonrası yeniden başlar.

Hermes'in açık olması gerekmez; launchd botu ayrı bir süreç olarak çalıştırır. DKB dışındaki bildirimler Telegram'a başlık, tür ve bağlantı olarak gider; X otomasyonu yalnızca mevcut DKB kurallarına bağlıdır.
