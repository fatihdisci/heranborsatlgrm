import sys
import unittest
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kap_bot


class KapBotTests(unittest.TestCase):
    def test_stock_validation_allows_bist_code_with_digit(self):
        detail = {"relatedStocks": [{"code": "AVGY0"}, {"code": "18"}]}
        self.assertEqual(kap_bot.stocks(detail), ["AVGY0"])

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

    def test_required_tags_removes_urls_and_keeps_ticker(self):
        text = kap_bot.required_tags(kap_bot.tweet_only("Kısa açıklama https://example.com"), ["AVGY0"])
        self.assertEqual(text, "Kısa açıklama #AVGY0 #borsa #bist")

    def test_circuit_card_renders(self):
        path = kap_bot.render_circuit_card("HEDEF", {"name": "Hedef Holding", "price": 98.8, "change_pct": -5.0, "points": [104, 100, 99, 98.8]})
        self.assertTrue(Path(path).exists())
        with Image.open(path) as image:
            self.assertEqual(image.size, (1200, 675))
        Path(path).unlink()


if __name__ == "__main__":
    unittest.main()
