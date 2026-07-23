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
    ("餐厅", "restaurant"), ("饭馆", "restaurant"), ("饭店", "restaurant"), ("食堂", "restaurant"),
    ("酒吧", "bar"),
    ("商店", "shop"), ("超市", "shop"), ("便利店", "shop"),
    ("医院", "hospital"),
    ("车站", "station"), ("地铁", "station"), ("末班车", "station"), ("站台", "station"),
    ("车厢", "car"), ("车里", "car"), ("车内", "car"), ("开车", "car"),
    ("公园", "park"),
    ("大海", "beach"), ("海边", "beach"), ("海滩", "beach"), ("海岸", "beach"), ("沙滩", "beach"),
    ("山上", "mountain"), ("山路", "mountain"), ("深山", "mountain"), ("山林", "mountain"), ("爬山", "mountain"),
    ("小巷", "alley"), ("巷子", "alley"),
    ("街", "street"), ("马路", "street"),
    ("夜景", "nightview"), ("城市", "nightview"),
    ("写字楼", "office"), ("办公楼", "office"), ("配电", "office"), ("走廊", "office"), ("茶水间", "office"),
]

# mood keyword -> mood (matches /scene/bgm/<mood>.mp3 + client gradient)
_MOOD = [
    # world-flavored beds first (battle outranks tense when both keywords appear)
    ("战斗", "battle"), ("厮杀", "battle"), ("打斗", "battle"), ("激战", "battle"), ("交手", "battle"),
    ("帝皇", "grimdark"), ("蜂巢", "grimdark"), ("审判庭", "grimdark"), ("祷文", "grimdark"),
    ("斗气", "ancient"), ("魂力", "ancient"), ("武魂", "ancient"), ("修炼", "ancient"), ("宗门", "ancient"),
    ("调查", "mystery"), ("线索", "mystery"), ("真相", "mystery"), ("蹊跷", "mystery"),
    ("紧张", "tense"), ("害怕", "tense"), ("恐惧", "tense"), ("发抖", "tense"), ("不安", "tense"),
    ("诡异", "eerie"), ("镜子", "eerie"), ("黑暗", "eerie"), ("阴森", "eerie"), ("影子", "eerie"),
    ("温馨", "warm"), ("温柔", "warm"), ("陪着", "warm"), ("陪伴", "warm"), ("依偎", "warm"),
    ("浪漫", "romantic"), ("心动", "romantic"), ("脸红", "romantic"), ("暧昧", "romantic"),
    ("悲伤", "sad"), ("哭", "sad"), ("眼泪", "sad"), ("失去", "sad"), ("离开", "sad"), ("走了", "sad"),
    ("孤独", "lonely"), ("一个人", "lonely"), ("空荡", "lonely"), ("空落落", "lonely"),
]

# sfx keyword -> filename stem (matches /scene/sfx/<stem>.mp3), one-shot
_SFX = [
    ("敲门", "knock"), ("敲响", "knock"),
    ("开门", "door"), ("关门", "door"),
    ("脚步", "footsteps"),
    ("下雨", "rain"), ("雨", "rain"),
    ("风声", "wind"), ("刮风", "wind"), ("大风", "wind"), ("寒风", "wind"),
    ("震动", "buzz"), ("手机响", "buzz"),
    ("打雷", "thunder"), ("雷声", "thunder"), ("惊雷", "thunder"),
    ("海浪", "waves"), ("浪涛", "waves"), ("浪花", "waves"),
    ("心跳", "heartbeat"),
    ("电话铃", "ringtone"), ("铃声", "ringtone"),
    # CC0 foley (Kenney packs): blades, coin, glass, blows, arcana, ambience one-shots
    ("拔刀", "draw"), ("拔剑", "draw"),
    ("挥剑", "sword"), ("剑光", "sword"), ("刀光", "sword"), ("斩", "sword"), ("劈", "sword"),
    ("金铁", "clash"), ("兵刃", "clash"), ("刀剑相", "clash"),
    ("金币", "coin"), ("铜板", "coin"), ("星币", "coin"), ("数钱", "coin"),
    ("玻璃", "glass"), ("碎裂", "glass"),
    ("一拳", "punch"), ("挥拳", "punch"), ("拳砸", "punch"),
    ("爆炸", "explosion"), ("轰然", "explosion"),
    ("枪响", "laser"), ("开枪", "laser"), ("激光", "laser"), ("爆矢", "laser"),
    ("施法", "magic"), ("法术", "magic"), ("术法", "magic"), ("咒文", "magic"),
    ("钟声", "bell"), ("钟响", "bell"), ("敲钟", "bell"),
    ("翻书", "book"), ("书页", "book"),
    ("吱呀", "creak"), ("嘎吱", "creak"),
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
