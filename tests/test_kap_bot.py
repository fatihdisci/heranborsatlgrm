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
        detail = {"subject": {"tr": "Yeni İş İlişkisi"}, "summary": {"tr": "Şirket sözleşme imzaladı."}, "relatedStocks": [{"code": "BRLSM"}]}
        self.assertEqual(kap_bot.event_tweet("business", detail), "Yeni iş ilişkisi: Şirket sözleşme imzaladı. #BRLSM #borsa #bist")

    def test_ai_tweet_finalizer_removes_link_and_keeps_tags(self):
        result = kap_bot.finalise_ai_tweet("Şirket sözleşme imzaladı. https://example.com", ["BRLSM"])
        self.assertEqual(result, "Şirket sözleşme imzaladı. #BRLSM #borsa #bist")

    def test_disclosure_content_includes_all_body_paragraphs(self):
        source = ('text-block-value"><p>İlk ayrıntı.</p><p>İkinci ayrıntı.</p>'
                  '</div></div></div></td><td class="taxonomy-context-value-summernote">')
        self.assertEqual(kap_bot.extract_disclosure_content(source), "İlk ayrıntı. İkinci ayrıntı.")

    def test_event_card_renders(self):
        detail = {"summary": {"tr": "Şirket yeni bir iş ilişkisi açıkladı."}, "senderTitle": "BİRLEŞİM MÜHENDİSLİK ISITMA SOĞUTMA HAVALANDIRMA SANAYİ VE TİCARET A.Ş.", "relatedStocks": [{"code": "BRLSM"}]}
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
