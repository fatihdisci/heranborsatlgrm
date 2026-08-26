# KAP Haber Botu

Mac mini üzerinde 7/24 çalışmak üzere hazırlanmış ilk sürüm. KAP'ın herkese açık canlı bildirim sayfalarını periyodik olarak kontrol eder, yeni bildirimleri SQLite'a kaydeder, önemli görünenleri seçer, doğal dilli ve emojili Türkçe tweet metni üretir ve Telegram'a yollar. X'e otomatik paylaşım yapmaz.

## Klasör yapısı

```text
kap-bot/
├── kap_bot.py             # Bot ve CLI
├── .env.example           # Ayar şablonu
├── requirements.txt       # Harici paket gerekmez
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

2. `.env` içinde `KAP_SOURCE=public` ve `PUBLIC_INITIAL_INDEX` değerini o anki son KAP bildirim ID'si olarak ayarlayın. Telegram için BotFather'dan alınan token ve hedef `chat_id` değerini ekleyin. AI taslağı için `AI_API_KEY` girin; boş bırakılırsa emojili basit yerel taslak kullanılır.

3. Önce bağlantıyı tek sefer test edin:

   ```bash
   python3 kap_bot.py --once --dry-run
   ```

   İlk çalıştırmada `PUBLIC_INITIAL_INDEX` yalnızca başlangıç noktası olarak kaydedilir; eski bildirimler gönderilmez. Bot sonraki KAP ID'sini takip eder.

4. Sürekli önizleme:

   ```bash
   python3 kap_bot.py
   ```

## launchd ile 7/24 çalışma

Şablondaki `/ABSOLUTE/PATH/TO/kap-bot` ve kullanıcı adını gerçek değerlerle değiştirin. Ardından:

```bash
mkdir -p data logs
sed -e "s|/ABSOLUTE/PATH/TO/kap-bot|$(pwd)|g" -e "s|/ABSOLUTE/PATH/TO/PYTHON3|$(which python3)|g" \
  launchd/com.fatih.kapbot.plist.template > "$HOME/Library/LaunchAgents/com.fatihdisci.kapbot.plist"
launchctl bootout "gui/$(id -u)"/com.fatihdisci.kapbot 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.fatihdisci.kapbot.plist"
launchctl kickstart -k "gui/$(id -u)/com.fatihdisci.kapbot"
```

Durumu görmek için `launchctl print gui/$(id -u)/com.fatihdisci.kapbot`, logları görmek için `tail -f logs/kap-bot.log` kullanın. `KeepAlive` sayesinde çökme sonrası yeniden başlar.

Hermes'in açık olması gerekmez; launchd botu ayrı bir süreç olarak çalıştırır. İlk sürüm yalnızca Telegram'a taslak yollar.
