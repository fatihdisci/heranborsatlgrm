import sys
import unittest
from pathlib import Path

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

    def test_circuit_breaker_message_is_complete_and_deterministic(self):
        detail = {"subject": {"tr": "Pay Bazında Devre Kesici Bildirimi"}, "summary": {"tr": "Devre kesici uygulaması"}, "content": {"tr": "Sürekli işleme ara verilmiş, tek fiyat emir toplama başlamıştır. İşlemlere 15:21:21 itibarıyla devam edilecektir."}, "relatedStocks": [{"code": "IHAAS"}]}
        self.assertEqual(kap_bot.draft(detail), "⚠️ IHAAS'ta devre kesici devrede. Sürekli işleme ara verildi, tek fiyat emir toplama başladı. İşlemler 15:21:21'de yeniden başlayacak. #IHAAS #borsa #bist")

    def test_required_tags_removes_urls_and_keeps_ticker(self):
        text = kap_bot.required_tags(kap_bot.tweet_only("Kısa açıklama https://example.com"), ["AVGY0"])
        self.assertEqual(text, "Kısa açıklama #AVGY0 #borsa #bist")


if __name__ == "__main__":
    unittest.main()
