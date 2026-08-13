# -*- coding: utf-8 -*-
"""🎨 头像配方只有一份 —— 2026-08-13 九龙城寨·狗笼 实弹回归。

出事经过: backfill_avatars.py 私藏了一份注释写着「same recipe as
runs._ensure_char_avatars」的复制品, 但四道保护一个都没有。用它给狗笼重渲头像,
十二少那张把整块数值卡当画面文字画进了图里 —— 因为该角色的 persona_text 开头
就是「战力：8.5/10 / 颜值：7.5/10 / 身高：180cm / 武器：武士刀」, 而复制品的
调用处没传含「文字,水印」的反向词。

这里钉死的是**配方的四道保护**, 不是像素。注释保证不了这件事, 断言可以。
"""
import ast
from pathlib import Path

from app.engine.sprites import portrait_prompt
from app.routers.runs import _char_seed, _story_art

_API = Path(__file__).resolve().parents[1]

_CARD = {
    "id": "twelfth", "name": "十二少", "gender": "男", "age_band": "青年",
    "role": "架势堂头马",
    # 真实卡面 (狗笼库里就长这样): 开头整块数值, 正是被画成文字的那段
    "persona_text": "战力：8.5/10\n颜值：7.5/10\n身高：180cm\n武器：武士刀\n"
                    "所属帮派：架势堂\n\n1964年出生于九龙城寨。",
}
_CONTENT = {"story": {"id": "gl", "tuning": {"art_style": "港片写实胶片，35mm 扫描"}}}


def test_art_leads_the_prompt():
    """① 画风压在最前 —— 放句尾会被人物描述带跑 (gal 实弹教训)。"""
    art, _ = _story_art(_CONTENT)
    p = portrait_prompt(_CARD, "九龙城寨", art)
    assert p.startswith(art), f"画风没压在开头: {p[:60]}"


def test_gender_is_written_not_guessed():
    """② look_bits 硬写性别/年龄 —— 「头马」这种职业词会被脑补成别的性别。"""
    p = portrait_prompt(_CARD, "九龙城寨", "港片写实")
    assert "男性" in p


def test_negative_blocks_text_in_image():
    """③ 反向词末尾必须封「文字/水印」—— 这次数值卡被画成字就是缺了它。"""
    _, neg = _story_art(_CONTENT)
    assert "文字" in neg and "水印" in neg


def test_same_face_seed_is_stable_and_per_story():
    """④ 同角色重画不换脸; 且两本剧本各自一颗种 (共用 id 时才不会互相盖)。"""
    assert _char_seed(_CONTENT, "twelfth") == _char_seed(_CONTENT, "twelfth")
    other = {"story": {"id": "dragon", "tuning": {}}}
    assert _char_seed(_CONTENT, "twelfth") != _char_seed(other, "twelfth")


def test_no_second_portrait_recipe_anywhere():
    """配方只准有一份。谁再抄一句「人物肖像，胸像特写」到别的文件里就红。

    (只认字面量, 所以 sprites.py 里的那一份原文不算 —— 它就是唯一的那份。)
    """
    needle = "人物肖像，胸像特写"
    home = _API / "app" / "engine" / "sprites.py"
    guilty = []
    for f in list(_API.glob("*.py")) + list((_API / "app").rglob("*.py")):
        if f == home or "tests" in f.parts:
            continue
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and needle in node.value:
                guilty.append(f"{f.relative_to(_API)}:{node.lineno}")
    assert not guilty, "又抄了一份头像配方, 请改调 sprites.portrait_prompt: " + "、".join(guilty)
