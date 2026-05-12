# ================== 廣告偵測模組 ==================
# 兩層過濾：L1 正則規則 + L2 模板相似度（不依賴外部模型）

import re
import unicodedata
from typing import Tuple
from ad_templates import AD_TEMPLATES

# ──────────────────────────────────────────────
# 文字清洗
# ──────────────────────────────────────────────

# 常見混淆替換（廣告商慣用手法）
_CONFUSE_MAP = {
    "减介": "简介",
    "简届": "简介",
    "硷介": "简介",
    "筒介": "简介",
    "jian jie": "简介",
    "１": "1", "２": "2", "３": "3", "４": "4", "５": "5",
    "６": "6", "７": "7", "８": "8", "９": "9", "０": "0",
    "万＋": "万+",
}

def clean_text(text: str) -> str:
    """移除零寬字元、統一全形、替換混淆詞"""
    # 移除零寬字元
    text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    # NFKC 正規化（全形→半形）
    text = unicodedata.normalize("NFKC", text)
    # 混淆詞替換
    for k, v in _CONFUSE_MAP.items():
        text = text.replace(k, v)
    return text.strip()


# ──────────────────────────────────────────────
# L1：正則規則引擎
# ──────────────────────────────────────────────

_RULES = [
    # 金額 + 收益
    (r"一天[0-9０-９一二三四五六七八九十百千]+万", "金額誘惑"),
    (r"保底[0-9０-９一二三四五六七八九十百千]+万", "金額誘惑"),
    (r"日入[0-9０-９]+", "金額誘惑"),
    (r"月入[0-9０-９]+万", "金額誘惑"),
    # 豪車
    (r"提(宝马|奔驰|保时捷|大G|劳斯莱斯|玛莎拉蒂)", "豪車誘惑"),
    (r"一周.*?(宝马|奔驰|保时捷)", "豪車誘惑"),
    # 模糊行動號召
    (r"看\s*(我\s*)?(简介|减介|简届)", "模糊號召"),
    (r"看\s*(我\s*)?简\s*介", "模糊號召"),
    (r"(缺|招)\s*[0-9一二三四五六七八九十几]+?\s*(个|名|位)\s*(兄弟|伙伴|人手)", "招募廣告"),
    # 上門服務
    (r"上门\s*(按摩|服务|推拿)", "上門服務"),
    (r"同城\s*配送", "上門服務"),
    (r"24[Hh小时]\s*(便民|服务|待命)", "上門服務"),
    # TG 代發
    (r"(飞机|TG|tg)\s*(全行业|群发|代发|推广)", "TG代發"),
    (r"(广告|ad)\s*代\s*(发|投)", "TG代發"),
    (r"精准\s*引流", "TG代發"),
    (r"覆盖\s*[0-9]+\s*(万|千|百|个)?\s*(粉|群)", "TG代發"),
    # 軟色情
    (r"(可约|约|预约)\s*(学生妹|学生|妹子|小姐姐|少妇)", "色情服務"),
    (r"(高端|私人)\s*伴游", "色情服務"),
    (r"保养\s*(读书妹|学生妹|妹子)", "色情服務"),
    # 地域 + 引流組合
    (r"(吉隆坡|KL|大马|东南亚).{0,20}@\w+", "地域引流"),
    # 通用 @ 引流（附帶行動詞）
    (r"(速来|来|了解|私聊|联系).{0,10}@\w{3,}", "引流@帳號"),
    (r"看(简介|我).{0,5}@\w{3,}", "引流@帳號"),
]

_COMPILED_RULES = [(re.compile(pattern, re.IGNORECASE), label) for pattern, label in _RULES]


def check_rules(text: str) -> Tuple[bool, list]:
    """L1：正則規則檢查，返回 (是否命中, 命中標籤列表)"""
    hits = []
    for pattern, label in _COMPILED_RULES:
        if pattern.search(text):
            if label not in hits:
                hits.append(label)
    return len(hits) > 0, hits


# ──────────────────────────────────────────────
# L2：模板相似度（字符 n-gram Jaccard）
# 不需要任何外部模型，純 Python，夠快
# ──────────────────────────────────────────────

def _ngrams(text: str, n: int = 3) -> set:
    """字元 n-gram 集合"""
    text = text.lower()
    return {text[i:i+n] for i in range(len(text) - n + 1)}

# 預計算模板 n-gram
_TEMPLATE_NGRAMS = [_ngrams(clean_text(t)) for t in AD_TEMPLATES]

SIMILARITY_THRESHOLD = 0.30   # Jaccard 閾值（廣告通常有大量共同詞組）

def jaccard_similarity(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)

def check_similarity(text: str) -> Tuple[bool, float]:
    """L2：與模板庫比較，返回 (是否超過閾值, 最高相似度)"""
    ng = _ngrams(text)
    if not ng:
        return False, 0.0
    best = max(jaccard_similarity(ng, tmpl) for tmpl in _TEMPLATE_NGRAMS)
    return best >= SIMILARITY_THRESHOLD, round(best, 3)


# ──────────────────────────────────────────────
# 主偵測函數
# ──────────────────────────────────────────────

def detect_ad(raw_text: str) -> Tuple[bool, float, str]:
    """
    輸入：原始訊息文字
    輸出：(是否廣告, 置信度 0~1, 匹配說明)
    """
    text = clean_text(raw_text)

    # L1：正則
    hit_rule, labels = check_rules(text)
    if hit_rule:
        confidence = min(0.6 + 0.1 * len(labels), 0.99)
        return True, confidence, "規則命中: " + ", ".join(labels)

    # L2：模板相似度
    hit_sim, score = check_similarity(text)
    if hit_sim:
        return True, score, f"模板相似度: {score:.2f}"

    return False, round(score if 'score' in dir() else 0.0, 3), "正常訊息"
