"""Keyword scene classifier — drives the immersive layer (background / BGM / SFX).

Pure and deterministic (no LLM cost). Maps a turn's narration+dialogue text to a
background key, a mood, and optional one-shot sound effects, using the same asset
taxonomy as SCENE_ASSETS.md. Missing asset files degrade gracefully on the client
(gradient background by mood, silent audio)."""

from __future__ import annotations

from typing import Any

# location keyword -> background filename stem (matches /scene/bg/<stem>.jpg)
_BG = [
    ("卧室", "bedroom"), ("床", "bedroom"),
    ("客厅", "livingroom"),
    ("厨房", "kitchen"),
    ("浴室", "bathroom"), ("洗手间", "bathroom"),
    ("书房", "study"),
    ("办公室", "office"), ("工位", "office"), ("会议", "office"),
    ("教室", "classroom"),
    ("咖啡", "cafe"),
    ("餐厅", "restaurant"), ("饭", "restaurant"),
    ("酒吧", "bar"),
    ("商店", "shop"), ("超市", "shop"), ("便利店", "shop"),
    ("医院", "hospital"),
    ("车站", "station"), ("地铁", "station"), ("末班车", "station"), ("站台", "station"),
    ("车厢", "car"), ("车里", "car"), ("车内", "car"), ("开车", "car"),
    ("公园", "park"),
    ("海", "beach"), ("沙滩", "beach"),
    ("山", "mountain"),
    ("小巷", "alley"), ("巷子", "alley"),
    ("街", "street"), ("马路", "street"),
    ("夜景", "nightview"), ("城市", "nightview"),
    ("楼", "office"), ("配电", "office"), ("走廊", "office"), ("茶水间", "office"),
]

# mood keyword -> mood (matches /scene/bgm/<mood>.mp3 + client gradient)
_MOOD = [
    ("紧张", "tense"), ("害怕", "tense"), ("恐惧", "tense"), ("发抖", "tense"), ("不安", "tense"),
    ("诡异", "eerie"), ("镜子", "eerie"), ("黑暗", "eerie"), ("阴森", "eerie"), ("影子", "eerie"),
    ("温馨", "warm"), ("温柔", "warm"), ("陪", "warm"), ("依偎", "warm"),
    ("浪漫", "romantic"), ("心动", "romantic"), ("脸红", "romantic"), ("暧昧", "romantic"),
    ("悲伤", "sad"), ("哭", "sad"), ("眼泪", "sad"), ("失去", "sad"), ("离开", "sad"), ("走了", "sad"),
    ("孤独", "lonely"), ("一个人", "lonely"), ("空", "lonely"),
]

# sfx keyword -> filename stem (matches /scene/sfx/<stem>.mp3), one-shot
_SFX = [
    ("敲门", "knock"), ("敲", "knock"),
    ("开门", "door"), ("关门", "door"),
    ("脚步", "footsteps"),
    ("下雨", "rain"), ("雨", "rain"),
    ("风", "wind"),
    ("震动", "buzz"), ("手机响", "buzz"),
    ("打雷", "thunder"), ("雷", "thunder"),
    ("海浪", "waves"), ("浪", "waves"),
    ("心跳", "heartbeat"),
    ("电话铃", "ringtone"), ("铃", "ringtone"),
]

_NIGHT = ["夜", "深夜", "凌晨", "末班", "晚上", "灯灭", "黑"]


def _first_hit(text: str, table: list[tuple[str, str]]) -> str | None:
    for kw, val in table:
        if kw in text:
            return val
    return None


def classify_scene(text: str, default_bg: str = "indoor") -> dict[str, Any]:
    """Return {bg, mood, sfx, night} for a chunk of narration/dialogue."""
    t = text or ""
    bg = _first_hit(t, _BG) or default_bg
    mood = _first_hit(t, _MOOD) or "daily"
    sfx = _first_hit(t, _SFX)
    night = any(k in t for k in _NIGHT)
    return {"bg": bg, "mood": mood, "sfx": sfx, "night": night}
