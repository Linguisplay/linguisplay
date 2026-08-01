# -*- coding: utf-8 -*-
"""🎙 语气音精灵库生成 (run LOCALLY, then upload) — galgame 简语音.

每个已选角的音色预生成一小套语气短音频 (惊/怒/哀/喜/常态 × 2 变体),
客户端在角色开口时按导演 expr 注记挑一个播 — 零 token、零延迟、声音稳定。
语言跟音色走 (选角 1:1, 无跨语双持): 粤语音色配粤语叹词, 英文音色配英文叹词。

Output: app/static/scene/voice/<voice_id>/<cat>_<n>.mp3 — play.html 按此路径取。
Idempotent: 已存在跳过 (--force 重生成)。费用: 全量 ~110 段 × 数字符, 几分钱级。

Usage:  python gen_voice.py [--force] [voice_id ...]     # 不带参数 = 全部
Upload: tar czf - -C app/static/scene voice | ssh persona "tar xzf - -C /opt/linguisplay/apps/api/app/static/scene"
"""
import os
import sys

from app.engine.voice import SPRITES, synth

OUT_DIR = os.path.join("app", "static", "scene", "voice")

# 音色 → 叹词语言。选角: 九龙城寨·龙头 (yue/zh) + Golden Hour (en)。
# 新剧本选角落在这里加一行 + 跑一次本脚本即可; 引擎与前端都只认文件路径。
VOICES: dict[str, str] = {
    # 九龙城寨·狗笼 / 龙头 (同班底)
    "longanyue_v3":   "yue",   # 龙卷风 (唯一粤语男声)
    "longjiayi_v3":   "yue",   # 蔡妍 (知性粤语女; 狗笼里是NPC)
    "longtian_v3":    "zh",    # 蓝信一
    "longfei_v3":     "zh",    # 十二少
    "longjielidou_v3": "zh",   # 四仔
    "longcheng_v3":   "zh",    # 王九
    "longanzhi_v3":   "zh",    # 大老板
    "longyingxun_v3": "zh",    # 陈洛军 (狗笼库生角色)
    "longze_v3":      "zh",    # Tiger哥 (狗笼库生角色)
    "longanyang":     "zh",    # 狄秋 (狗笼库生角色; 该音色无 _v3 后缀)
    # Golden Hour
    "loongeric_v3":   "en",    # Elias (英音)
    "loongdavid_v3":  "en",    # Rafael (美音)
    "loongandy_v3":   "en",    # Niko (美音)
    "loongluca_v3":   "en",    # Marek (英音)
    "longanlang_v3":  "en",    # Ilya (双语音色, 微口音正合丹麦人设; 勿再跨语双持)
}

# 精灵台本住在 engine/voice.SPRITES (克隆音即时生成与这里共用一份, 不许分家)。


def main() -> None:
    force = "--force" in sys.argv
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    todo = {v: l for v, l in VOICES.items() if not only or v in only}
    made = skipped = failed = 0
    for voice, lang in todo.items():
        vdir = os.path.join(OUT_DIR, voice)
        for cat, texts in SPRITES[lang].items():
            for i, text in enumerate(texts, 1):
                path = os.path.join(vdir, f"{cat}_{i}.mp3")
                if not force and os.path.exists(path):
                    skipped += 1
                    continue
                try:
                    audio = synth(text, voice)
                except Exception as e:
                    print(f"  FAIL {voice}/{cat}_{i} ({text!r}): {e}")
                    failed += 1
                    continue
                os.makedirs(vdir, exist_ok=True)
                with open(path, "wb") as f:
                    f.write(audio)
                made += 1
                print(f"  {path}  ({len(audio)//1024} KB)")
    print(f"done. made={made} skipped={skipped} failed={failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
