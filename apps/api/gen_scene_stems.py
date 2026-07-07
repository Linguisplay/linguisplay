# -*- coding: utf-8 -*-
"""Generate the GENERIC keyword-scene backgrounds (bedroom/street/cafe/…) that
paintKeywordBg() falls back to when a story has no authored location. These stems come
from engine/scene.py `_BG` + the "indoor" default; they were never generated, so every
location-less story has been playing on a plain gradient (and 404ing per scene switch).

Idempotent: skips stems whose jpg already exists. Run ON THE SERVER:
    cd /opt/linguisplay/apps/api && set -a && . .env && set +a && \
        ./.venv/bin/python gen_scene_stems.py
Output: app/static/scene/bg/<stem>.jpg  →  /scene/bg/<stem>.jpg
"""
import os
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from app.engine.qwen import generate_image  # noqa: E402

BG_DIR = Path(__file__).parent / "app" / "static" / "scene" / "bg"

STEMS = {
    "indoor": "一间安静的现代室内空间，暖黄台灯，木地板，窗外天色沉下来",
    "bedroom": "一间温馨的卧室，床头灯亮着，被子松软，窗帘半掩",
    "livingroom": "一间现代客厅，沙发与茶几，落地窗外是城市灯火",
    "kitchen": "一间干净的家用厨房，灶上有汤在冒热气，暖光",
    "bathroom": "一间白瓷砖浴室，镜面带着水汽，暖色小灯",
    "study": "一间书房，整墙书架，桌上一盏绿罩台灯，纸页摊开",
    "office": "一层深夜的办公室，工位隔断，只有几盏灯还亮着，落地窗外是城市夜景",
    "classroom": "一间放学后的教室，夕阳斜进课桌椅，黑板上还有粉笔字迹",
    "cafe": "一间温暖的咖啡馆，木质桌椅，吧台暖灯，窗外行人虚化",
    "restaurant": "一间夜里的餐厅，暖黄吊灯下的餐桌，餐具反着微光",
    "bar": "一间昏暗的酒吧，吧台酒瓶背光陈列，霓虹微光",
    "shop": "一间深夜便利店，冷白货架灯，玻璃门外是暗色街道",
    "hospital": "一条医院走廊，冷白灯光，长椅与指示牌，空无一人",
    "station": "一座夜晚的车站站台，站牌灯箱亮着，铁轨延伸进黑暗",
    "car": "一辆车的车厢内部视角，仪表盘微光，挡风玻璃外是雨夜街灯",
    "park": "一座傍晚的城市公园，长椅与路灯，树影层叠",
    "beach": "一片黄昏的海滩，浪线泛着落日余光，远处海平线",
    "mountain": "山间小径，雾气缠绕林梢，远山层叠",
    "alley": "一条夜晚的小巷，湿漉漉的石板路反着一盏孤灯",
    "street": "一条夜晚的城市街道，霓虹与车灯拉出光轨，路面微湿",
    "nightview": "城市天际线夜景，万家灯火，深蓝夜空",
}

SUFFIX = ("。电影感写实场景概念图，强烈氛围与光影，景深，电影级调色，横构图宽幅；"
          "空镜，画面里没有任何人物，没有文字、字幕或水印。")


def main() -> None:
    BG_DIR.mkdir(parents=True, exist_ok=True)
    todo = {k: v for k, v in STEMS.items() if not (BG_DIR / f"{k}.jpg").exists()}
    print(f"{len(todo)}/{len(STEMS)} generic scene stems to generate…")
    for stem, desc in todo.items():
        print(f"  generating {stem}…", end=" ", flush=True)
        try:
            img = generate_image(desc + SUFFIX, size="1280*720")
            if not img:
                print("SKIP (no image returned)")
                continue
            (BG_DIR / f"{stem}.jpg").write_bytes(img)
            print(f"OK ({len(img) // 1024} KB)")
        except Exception as e:
            print(f"FAIL ({e})")


if __name__ == "__main__":
    main()
