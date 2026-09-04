# KAP Haber Botu

Mac mini üzerinde KAP bildirimlerini izler. İzin listesindeki DKB'leri X'te otomatik paylaşır. DKB dışındaki haberleri kaynak kanıtlarıyla hazırlar, ayrı bir AI doğrulamasından geçirir ve aynı bilgi setinden tweet taslağı ile dikey kartı Telegram'a gönderir. DKB dışı X paylaşımı kapalıdır.

DKB dışı metinler `AI_MODEL` ile iki aşamada hazırlanır: resmi başlık + tam Türkçe açıklama/tablo/PDF metni okunur; yapılandırılmış taslak bağımsız doğrulama çağrısıyla kontrol edilir. Başlık/kategori, kaynak alıntıları, rakamlar ve uzunluk sınırları ayrıca kodla kontrol edilir. İçerik okunamazsa, AI tamamlanmazsa veya kart metni sığmazsa kırpılmış/yedek haber yerine inceleme bildirimi gönderilir. Kaynak, model yanıtı ve kontrol sonuçları `data/editorial/` içinde tutulur. Bu kontroller doğruluk garantisi değildir; X otomatiği açılmadan insan incelemesi gerekir.

Editoryal işler ayrı kalıcı kuyruk ve iş parçacığında çalışır; DKB taraması AI'yi beklemez. PDF okumada 5 ek, dosya başına 10 MB/40 sayfa ve toplam 120.000 karakter sınırı vardır. Taranmış/metni okunamayan ekler incelemeye ayrılır. Yerel önizleme (Telegram/X göndermez): `.venv/bin/python scripts/preview_editorial.py 1658852 1658640`.

## Klasör yapısı

```text
kap-bot/
├── kap_bot.py             # Bot ve CLI
├── .env.example           # Ayar şablonu
├── requirements.txt       # Pillow ve pypdf
├── kap_source.py          # Resmi KAP verisi, Türkçe tablolar, PDF ekleri
├── kap_editorial.py       # Kanıtlı taslak ve doğrulama
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

2. `python3 -m venv .venv` ve `.venv/bin/python -m pip install -r requirements.txt` komutlarıyla bağımlılıkları kurun. `.env` içinde `KAP_SOURCE=public` ve `PUBLIC_INITIAL_INDEX` değerini başlangıç KAP ID'si olarak ayarlayın. Telegram token ve chat_id değerlerini, editoryal hazırlama için `AI_API_KEY` değerini ekleyin. AI yoksa DKB dışı haberler incelemeye ayrılır.

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

Hermes'in açık olması gerekmez; launchd botu ayrı bir süreç olarak çalıştırır. DKB dışındaki bildirimler Telegram'a taslak veya inceleme uyarısı olarak gider; X otomasyonu yalnızca mevcut DKB kurallarına bağlıdır.
