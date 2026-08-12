"""Per-group feature settings for the Telegram admin bot."""

from typing import Dict, MutableMapping


DEFAULT_FEATURES = {
    "welcome": True,
    "leave_notice": True,
    "profile_check": True,
    "ad_detection": True,
    "ad_delete": True,
    "ad_mute": True,
    "ad_notify_admins": True,
    "referendum": True,
    "banme": True,
    "ban_command": True,
    "join_captcha": True,
    "profile_hit_report": True,
    "rename_recheck": True,
    "block_contact_share": True,
    "external_quote_check": True,
}

FEATURE_LABELS = {
    "welcome": "入群歡迎",
    "leave_notice": "離群通知",
    "profile_check": "入群簡介檢測",
    "ad_detection": "訊息廣告檢測",
    "ad_delete": "廣告自動刪除",
    "ad_mute": "廣告自動禁言",
    "ad_notify_admins": "廣告通知管理員",
    "referendum": "全員禁言公投",
    "banme": "/banme 彩蛋禁言",
    "ban_command": "/ban 管理員禁言",
    "join_captcha": "入群人機驗證",
    "profile_hit_report": "簡介命中通報",
    "rename_recheck": "改名重新檢測",
    "block_contact_share": "非管理員分享聯絡人卡片阻擋",
    "external_quote_check": "跨群引用廣告偵測",
}


def get_group_features(group: MutableMapping) -> Dict[str, bool]:
    """Return valid settings, filling defaults for old or new group records."""
    stored = group.get("features", {})
    if not isinstance(stored, dict):
        stored = {}
    return {
        name: stored.get(name, default)
        if isinstance(stored.get(name, default), bool)
        else default
        for name, default in DEFAULT_FEATURES.items()
    }


def feature_enabled(group: MutableMapping, feature: str) -> bool:
    """Check a feature; unknown feature names are disabled for safety."""
    if feature not in DEFAULT_FEATURES:
        return False
    return get_group_features(group)[feature]


def set_group_feature(groups: MutableMapping, chat_id: int, feature: str, enabled: bool) -> None:
    """Persist one feature setting in a group's record."""
    if feature not in DEFAULT_FEATURES:
        raise ValueError(f"unknown feature: {feature}")
    key = str(chat_id) if str(chat_id) in groups else chat_id
    group = groups.setdefault(key, {})
    group["features"] = get_group_features(group)
    group["features"][feature] = bool(enabled)
