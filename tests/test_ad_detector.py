import unittest

from ad_detector import clean_text, detect_ad


class ObfuscatedAdTests(unittest.TestCase):
    def assertAd(self, text):
        detected, _, _ = detect_ad(text)
        self.assertTrue(detected, text)

    def test_collection_high_income(self):
        self.assertAd("没事做的兄弟看过来🔥d.y.好橡木，秒结\n招代收钱 日赚一W")

    def test_football_red_ticket(self):
        self.assertAd("五大联赛足球红单推荐👗天天收米🦆日赚6千 @xhdkm8121bot")

    def test_punctuated_fruit_machine(self):
        text = "低⁠。​價‌。‌出‌.正。品。水。果‌。機​"
        self.assertAd(text)

    def test_punctuated_fruit_machine_price(self):
        text = "17。p。​m。a‌x.‌僅。⁠５。K.​多"
        self.assertAd(text)
        self.assertIn("17pmax僅5K多", clean_text(text))

    def test_punctuated_fruit_price(self):
        self.assertAd("水​.⁠果​.‍１.​6特.價")

    def test_anti_ban_phrase_alone_is_not_an_ad_signal(self):
        self.assertFalse(detect_ad("拒绝私聊，聊天机器人暂时维护中")[0])

    def test_mutual_restriction_routing_is_not_an_ad_signal(self):
        self.assertFalse(
            detect_ad(
                "拒绝私聊, 聊天机器人 @Boss1_56IDC_Bot 官网:56idc.net 群:@Chat_56IDC_Net"
            )[0]
        )

    def test_long_quoted_black_market_discussion_is_not_deleted(self):
        text = """七氟烷新品接批发接面交 @seller
        有没有人想做兼职？手机像素高就行。
        擔保群：https://t.me/example
        這是黑產來聚會了？想討論黑產氾濫程度，避免誤殺。"""
        self.assertFalse(detect_ad(text)[0])


if __name__ == "__main__":
    unittest.main()
