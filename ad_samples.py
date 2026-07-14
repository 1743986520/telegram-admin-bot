# ================== 動態樣本庫 ==================
# 在不改動 ad_templates.py（基礎大庫）的前提下，
# 讓管理員可於執行時「入庫」新廣告樣本、或把誤封訊息加入白樣本。
# 資料持久化到 JSON，重啟後保留；被 ad_detector 熱重載時合併。

import json
import os
import threading
from typing import List

_DIR = os.path.dirname(os.path.abspath(__file__))
AD_SAMPLES_FILE = os.path.join(_DIR, "custom_ad_samples.json")
WHITELIST_FILE = os.path.join(_DIR, "whitelist_samples.json")

_lock = threading.Lock()


def _load(path: str) -> List[str]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            # 只保留非空字串並去重（保序）
            seen = set()
            out = []
            for x in data:
                if isinstance(x, str):
                    s = x.strip()
                    if s and s not in seen:
                        seen.add(s)
                        out.append(s)
            return out
    except (json.JSONDecodeError, OSError):
        return []
    return []


def _save(path: str, items: List[str]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # 原子寫入，避免半截檔案


def load_ad_samples() -> List[str]:
    """讀取動態廣告樣本。"""
    return _load(AD_SAMPLES_FILE)


def load_whitelist_samples() -> List[str]:
    """讀取白樣本（非廣告）。"""
    return _load(WHITELIST_FILE)


def _add(path: str, text: str) -> bool:
    """加入一筆樣本，回傳是否為新增（已存在則 False）。"""
    text = (text or "").strip()
    if not text:
        return False
    with _lock:
        items = _load(path)
        if text in items:
            return False
        items.append(text)
        _save(path, items)
    return True


def add_ad_sample(text: str) -> bool:
    """入庫：新增廣告樣本。"""
    return _add(AD_SAMPLES_FILE, text)


def add_whitelist_sample(text: str) -> bool:
    """誤封處理：把訊息加入白樣本（非廣告）。"""
    return _add(WHITELIST_FILE, text)


def remove_ad_sample(text: str) -> bool:
    """從廣告樣本移除一筆。"""
    text = (text or "").strip()
    with _lock:
        items = _load(AD_SAMPLES_FILE)
        if text not in items:
            return False
        items.remove(text)
        _save(AD_SAMPLES_FILE, items)
    return True


def remove_whitelist_sample(text: str) -> bool:
    """從白樣本移除一筆。"""
    text = (text or "").strip()
    with _lock:
        items = _load(WHITELIST_FILE)
        if text not in items:
            return False
        items.remove(text)
        _save(WHITELIST_FILE, items)
    return True
