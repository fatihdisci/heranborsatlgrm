import sys
import os
import unittest
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kap_bot


class KapBotTests(unittest.TestCase):
    def test_stock_validation_allows_bist_code_with_digit(self):
        detail = {"relatedStocks": [{"code": "AVGY0"}, {"code": "18"}]}
        self.assertEqual(kap_bot.stocks(detail), ["AVGY0"])

    def test_stock_validation_uses_company_stock_code_fallback(self):
        detail = {"relatedStocks": [{"code": "MAGEN"}]}
        self.assertEqual(kap_bot.stocks(detail), ["MAGEN"])

    def test_noise_is_not_alerted(self):
        item = {"disclosureType": "PUBLIC"}
        detail = {"subject": {"tr": "Borsa Dışı Repo Sözleşmesi"}, "summary": {"tr": "Fon bildirimi"}, "relatedStocks": [{"code": "DOV"}]}
        self.assertFalse(kap_bot.is_important(item, detail))

    def test_circuit_breaker_is_alerted(self):
        item = {"disclosureType": "DKB"}
        detail = {"subject": {"tr": "Pay Bazında Devre Kesici Bildirimi"}, "summary": {"tr": "Devre kesici uygulaması"}, "relatedStocks": [{"code": "AVGY0"}]}
        self.assertTrue(kap_bot.is_important(item, detail))

    def test_notification_is_compact_and_contains_only_requested_fields(self):
        detail = {"subject": {"tr": "Pay Bazında Devre Kesici Bildirimi"}, "summary": {"tr": "Devre kesici uygulaması"}, "content": {"tr": "Sürekli işleme ara verilmiş, tek fiyat emir toplama başlamıştır. İşlemlere 15:21:21 itibarıyla devam edilecektir."}, "relatedStocks": [{"code": "IHAAS"}]}
        detail["link"] = "https://www.kap.org.tr/tr/Bildirim/1655131"
        self.assertEqual(kap_bot.draft(detail), "#IHAAS\nPay Bazında Devre Kesici Bildirimi\nhttps://www.kap.org.tr/tr/Bildirim/1655131")

    def test_circuit_tweet_is_short_and_ready_to_post(self):
        self.assertEqual(kap_bot.circuit_tweet("HEDEF"), "#HEDEF Devre kesti. #borsa #bist")

    def test_circuit_batch_tweet_combines_unique_tickers(self):
        self.assertEqual(kap_bot.circuit_batch_tweet(["HEDEF", "ALVES", "HEDEF"]), "#HEDEF #ALVES Devre kesti. #borsa #bist")

    def test_circuit_card_discloses_delayed_yahoo_price_data(self):
        self.assertEqual(kap_bot.CIRCUIT_DATA_NOTE, "Not: KAP haberi anlık; fiyat ve % değişim Yahoo Finance kaynaklı, yaklaşık 15 dk gecikmeli.")

    def test_special_kap_events_are_selected_for_cards(self):
        cases = {
            "buyback": "Payların Geri Alınmasına İlişkin Bildirim",
            "business": "Yeni İş İlişkisi",
            "share_trade": "Pay Alım Satım Bildirimi",
            "suspension": "Faaliyetlerin Kısmen veya Tamamen Durdurulması ya da İmkansız Hale Gelmesi",
        }
        for expected, title in cases.items():
            detail = {"subject": {"tr": title}, "summary": {"tr": "Önemli KAP açıklaması"}, "relatedStocks": [{"code": "TEST"}]}
            self.assertEqual(kap_bot.special_event(detail)[0], expected)

    def test_business_contract_inflections_are_selected(self):
        detail = {"subject": {"tr": "Jeotermal Sondaj Hizmetleri Sözleşmesinin İmzalanması Hk."}, "relatedStocks": [{"code": "KPEKS"}]}
        self.assertEqual(kap_bot.special_event(detail), ("business", "YENİ İŞ İLİŞKİSİ"))

    def test_event_tweet_keeps_ticker_and_market_tags(self):
        detail = {"subject": {"tr": "Yeni İş İlişkisi"}, "content": {"tr": "Şirket sözleşme imzaladı."}, "relatedStocks": [{"code": "BRLSM"}]}
        self.assertEqual(kap_bot.event_tweet("business", detail), "Şirket sözleşme imzaladı. #BRLSM #borsa #bist")

    def test_event_summary_prefers_current_contract_over_history(self):
        detail = {"content": {"tr": "Önceki KAP açıklamasında duyurulduğu üzere ruhsat devir sözleşmesi imzalanmış ve tamamlanmıştı. Şirket, 5+5 toplam 10 kuyu için sondaj kulesi hizmet sözleşmesi imzaladı."}}
        self.assertEqual(kap_bot.event_summary(detail, "business"), "Şirket, 5+5 toplam 10 kuyu için sondaj kulesi hizmet sözleşmesi imzaladı.")

    def test_focused_summary_keeps_the_event_at_end_of_a_long_sentence(self):
        sentence = "Ruhsat sahalarında yürütülen çok kapsamlı hazırlık çalışmaları ve teknik planlamalar kapsamında Türkiye'de yerleşik bir şirket ile 5+5 toplam 10 kuyu için sondaj kulesi hizmet sözleşmesi imzalanmıştır."
        match = __import__("re").search(r"sözleşme\w*.*imzalan", sentence, __import__("re").I)
        result = kap_bot.focused_summary(sentence, match, 110)
        self.assertIn("10 kuyu", result)
        self.assertIn("sözleşmesi imzalanmıştır", result)

    def test_business_fallback_rewrites_quoted_contract_without_mid_sentence_cut(self):
        detail = {
            "content": {"tr": "Taşınmaz üzerinde ticarethane/iş yeri nitelikli proje geliştirilmesi amacıyla arsa sahipleri ile 28.08.2026 tarihinde \"Arsa Satışı Karşılığı Gelir Paylaşımı Sözleşmesi\" imzalanmıştır. Sözleşmeye göre, projeden elde edilecek hasılatın %70'i Şirketimize, %30'u arsa sahiplerine ait olacaktır."},
            "relatedStocks": [{"code": "ZRGYO"}],
        }
        result = kap_bot.factual_tweet(detail, "business")
        self.assertTrue(result.startswith("#ZRGYO, 28.08.2026 tarihinde Arsa Satışı Karşılığı Gelir Paylaşımı Sözleşmesi imzaladı."))
        self.assertIn("%70'i şirkete", result)
        self.assertIn("%30'u arsa sahiplerine", result)

    def test_store_tracks_telegram_link_separately(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            store = kap_bot.Store(Path(directory) / "test.sqlite3")
            self.addCleanup(store.close)
            store.save(123, True, "Test")
            self.assertFalse(store.telegram_link_sent(123))
            store.mark_telegram_link_sent(123)
            self.assertTrue(store.telegram_link_sent(123))

    def test_non_circuit_delivery_sends_link_after_card(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            store = kap_bot.Store(Path(directory) / "test.sqlite3")
            self.addCleanup(store.close)
            calls = []
            original_photo, original_message = kap_bot.telegram_send_photo, kap_bot.telegram_send
            original_card = kap_bot.render_event_card
            try:
                kap_bot.telegram_send_photo = lambda path, text: calls.append(("photo", text)) or True
                kap_bot.telegram_send = lambda text: calls.append(("link", text)) or True
                kap_bot.render_event_card = lambda event, label, detail: str(Path(directory) / "card.png")
                Path(directory, "card.png").touch()
                detail = {"subject": {"tr": "Yeni İş İlişkisi"}, "content": {"tr": "Şirket sözleşme imzaladı."}, "relatedStocks": [{"code": "BRLSM"}], "link": "https://www.kap.org.tr/tr/Bildirim/123"}
                item = {"disclosureType": "PUBLIC"}
                kap_bot.deliver(store, 123, item, detail, dry_run=False)
            finally:
                kap_bot.telegram_send_photo, kap_bot.telegram_send = original_photo, original_message
                kap_bot.render_event_card = original_card
            self.assertEqual([kind for kind, _ in calls], ["photo", "link"])
            self.assertEqual(calls[1][1], detail["link"])

    def test_circuit_batch_sends_each_card_then_one_shared_tweet(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            store = kap_bot.Store(Path(directory) / "test.sqlite3")
            self.addCleanup(store.close)
            calls = []
            original_photo, original_message = kap_bot.telegram_send_photo, kap_bot.telegram_send
            original_card = kap_bot.build_circuit_card
            try:
                def card(code):
                    path = Path(directory) / f"{code}.png"
                    path.touch()
                    return str(path)
                kap_bot.build_circuit_card = card
                kap_bot.telegram_send_photo = lambda path, text: calls.append(("photo", Path(path).stem, text)) or True
                kap_bot.telegram_send = lambda text: calls.append(("text", text)) or True
                for index, code in enumerate(("HEDEF", "ALVES", "KPEKS"), 100):
                    store.save(index, True, "Pay Bazında Devre Kesici Bildirimi")
                    store.queue_circuit(index, code)
                store.db.execute("UPDATE circuit_queue SET queued_at=0")
                store.db.commit()
                kap_bot.flush_circuit_queue(store)
            finally:
                kap_bot.telegram_send_photo, kap_bot.telegram_send = original_photo, original_message
                kap_bot.build_circuit_card = original_card
            self.assertEqual([call[0] for call in calls], ["photo", "photo", "photo", "text"])
            self.assertTrue(all(call[2] == "" for call in calls[:3]))
            self.assertEqual(calls[-1][1], "#HEDEF #ALVES #KPEKS Devre kesti. #borsa #bist")

    def test_circuit_batch_posts_its_cards_in_one_x_post(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            store = kap_bot.Store(Path(directory) / "test.sqlite3")
            self.addCleanup(store.close)
            original = {
                "X_AUTO_POST_DKB": os.environ.get("X_AUTO_POST_DKB"),
                "card": kap_bot.build_circuit_card,
                "photo": kap_bot.telegram_send_photo,
                "message": kap_bot.telegram_send,
                "x_post": kap_bot.x_post_circuit_batch,
            }
            calls = []
            try:
                os.environ["X_AUTO_POST_DKB"] = "true"
                def card(code):
                    path = Path(directory) / f"{code}.png"
                    path.touch()
                    return str(path)
                kap_bot.build_circuit_card = card
                kap_bot.telegram_send_photo = lambda path, text: True
                kap_bot.telegram_send = lambda text: True
                kap_bot.x_post_circuit_batch = lambda codes, paths: calls.append((codes, [Path(path).stem for path in paths])) or "x-post"
                for index, code in enumerate(("HEDEF", "ALVES", "KPEKS"), 100):
                    store.save(index, True, "Pay Bazında Devre Kesici Bildirimi")
                    store.queue_circuit(index, code)
                store.db.execute("UPDATE circuit_queue SET queued_at=0")
                store.db.commit()
                kap_bot.flush_circuit_queue(store)
            finally:
                kap_bot.build_circuit_card = original["card"]
                kap_bot.telegram_send_photo = original["photo"]
                kap_bot.telegram_send = original["message"]
                kap_bot.x_post_circuit_batch = original["x_post"]
                if original["X_AUTO_POST_DKB"] is None: os.environ.pop("X_AUTO_POST_DKB", None)
                else: os.environ["X_AUTO_POST_DKB"] = original["X_AUTO_POST_DKB"]
            self.assertEqual(calls, [(["HEDEF", "ALVES", "KPEKS"], ["HEDEF", "ALVES", "KPEKS"])])
            self.assertTrue(all(store.x_posted(ident) for ident in (100, 101, 102)))

    def test_single_circuit_keeps_caption_with_its_own_card(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            store = kap_bot.Store(Path(directory) / "test.sqlite3")
            self.addCleanup(store.close)
            calls = []
            original_photo, original_card = kap_bot.telegram_send_photo, kap_bot.build_circuit_card
            try:
                def card(code):
                    path = Path(directory) / f"{code}.png"
                    path.touch()
                    return str(path)
                kap_bot.build_circuit_card = card
                kap_bot.telegram_send_photo = lambda path, text: calls.append((Path(path).stem, text)) or True
                store.save(100, True, "Pay Bazında Devre Kesici Bildirimi")
                store.queue_circuit(100, "HEDEF")
                store.db.execute("UPDATE circuit_queue SET queued_at=0")
                store.db.commit()
                kap_bot.flush_circuit_queue(store)
            finally:
                kap_bot.telegram_send_photo, kap_bot.build_circuit_card = original_photo, original_card
            self.assertEqual(calls, [("HEDEF", "#HEDEF Devre kesti. #borsa #bist")])

    def test_ai_tweet_finalizer_removes_link_and_keeps_tags(self):
        result = kap_bot.finalise_ai_tweet("Şirket sözleşme imzaladı. https://example.com", ["BRLSM"])
        self.assertEqual(result, "Şirket sözleşme imzaladı. #BRLSM #borsa #bist")

    def test_disclosure_content_includes_all_body_paragraphs(self):
        source = ('text-block-value"><p>İlk ayrıntı.</p><p>İkinci ayrıntı.</p>'
                  '</div></div></div></td><td class="taxonomy-context-value-summernote">')
        self.assertEqual(kap_bot.extract_disclosure_content(source), "İlk ayrıntı. İkinci ayrıntı.")

    def test_event_card_renders(self):
        detail = {"summary": {"tr": "Şirket yeni bir iş ilişkisi açıkladı."}, "relatedStocks": [{"code": "BRLSM"}]}
        path = kap_bot.render_event_card("business", "YENİ İŞ İLİŞKİSİ", detail)
        with Image.open(path) as image: self.assertEqual(image.size, (720, 1280))
        Path(path).unlink()

    def test_project_name_omits_generic_disclosure_lead_in(self):
        detail = {"summary": {"tr": "Şirket ve bağlı ortaklık, İstanbul Uluslararası Finans Merkezi Borsa Binası Projesi kapsamında sözleşme imzaladı."}}
        self.assertEqual(kap_bot.card_project(detail), "İstanbul Uluslararası Finans Merkezi Borsa Binası Projesi")

    def test_editorial_headline_uses_reference_layout(self):
        self.assertEqual(kap_bot.event_headline("YENİ İŞ İLİŞKİSİ"), ["YENİ İŞ", "İLİŞKİSİ"])

    def test_branded_backgrounds_are_available(self):
        self.assertTrue((kap_bot.ASSETS / "dkb-background.jpg").exists())
        self.assertTrue((kap_bot.ASSETS / "event-background.jpg").exists())

    def test_required_tags_removes_urls_and_keeps_ticker(self):
        text = kap_bot.required_tags(kap_bot.tweet_only("Kısa açıklama https://example.com"), ["AVGY0"])
        self.assertEqual(text, "Kısa açıklama #AVGY0 #borsa #bist")

    def test_circuit_card_renders(self):
        path = kap_bot.render_circuit_card("HEDEF", {"name": "Hedef Holding", "price": 98.8, "change_pct": -5.0, "points": [104, 100, 99, 98.8]})
        self.assertTrue(Path(path).exists())
        with Image.open(path) as image:
            self.assertEqual(image.size, (1200, 675))
        Path(path).unlink()

    def test_circuit_card_still_renders_when_yahoo_has_no_intraday_points(self):
        path = kap_bot.render_circuit_card("ALVES", {"name": "Alves Kablo", "price": 1.6, "change_pct": 0.0, "points": []})
        with Image.open(path) as image: self.assertEqual(image.size, (1200, 675))
        Path(path).unlink()

    def test_circuit_card_still_renders_when_yahoo_quote_is_unavailable(self):
        path = kap_bot.render_circuit_card("ALVES", {"name": "ALVES", "price": None, "change_pct": None, "points": []})
        with Image.open(path) as image: self.assertEqual(image.size, (1200, 675))
        Path(path).unlink()

    def test_oauth_header_is_created(self):
        original = {key: os.environ.get(key) for key in ("X_API_KEY", "X_API_KEY_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")}
        os.environ.update({"X_API_KEY": "key", "X_API_KEY_SECRET": "secret", "X_ACCESS_TOKEN": "token", "X_ACCESS_TOKEN_SECRET": "token-secret"})
        header = kap_bot.x_oauth_header("GET", "https://api.x.com/2/users/me")
        self.assertIn('oauth_consumer_key="key"', header)
        self.assertIn("oauth_signature=", header)
        for key, value in original.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value

    def test_bearer_token_is_preferred_when_present(self):
        original = os.environ.get("X_OAUTH2_ACCESS_TOKEN")
        try:
            os.environ["X_OAUTH2_ACCESS_TOKEN"] = "oauth2-token"
            kap_bot._x_oauth2_access_token = None
            self.assertEqual(kap_bot.x_bearer_token(), "oauth2-token")
        finally:
            kap_bot._x_oauth2_access_token = None
            if original is None: os.environ.pop("X_OAUTH2_ACCESS_TOKEN", None)
            else: os.environ["X_OAUTH2_ACCESS_TOKEN"] = original

    def test_x_authorization_url_uses_user_scopes_and_pkce(self):
        original = os.environ.get("X_OAUTH2_CLIENT_ID")
        try:
            os.environ["X_OAUTH2_CLIENT_ID"] = "client-id"
            url = kap_bot.x_authorization_url("http://127.0.0.1:8787/callback", "state-value", "verifier-value")
            self.assertIn("response_type=code", url)
            self.assertIn("client_id=client-id", url)
            self.assertIn("tweet.write", url)
            self.assertIn("code_challenge_method=S256", url)
        finally:
            if original is None: os.environ.pop("X_OAUTH2_CLIENT_ID", None)
            else: os.environ["X_OAUTH2_CLIENT_ID"] = original


if __name__ == "__main__":
    unittest.main()
