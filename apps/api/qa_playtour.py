# -*- coding: utf-8 -*-
"""🌙 夜巡 (Yi 2026-08-01: 「要一个反复验证、保证玩家体验的方法」)。

每晚在服务器上扮演一次真玩家: 轮换挑几本已发布剧本, 用专属 QA 账号开专用档,
走【真实玩家路径】(HTTP + SSE 流式回合, 不抄引擎近道) 打两个回合, 然后用一套
「体验判官」机械检查判卷。发现即红灯, 写进日志; 与 smoke/守卫榜同在 daily_check
里出现。轮换保证一周内所有剧本都被巡到 — 这就是"反复"。

    QA_STORIES=2 QA_TURNS=2 ./.venv/bin/python qa_playtour.py
    ./.venv/bin/python qa_playtour.py --story 末班车上的陌生人   # 点名巡某本

体验判官管的是玩家眼睛看得到的东西 (每条都来自真实弹):
  半词截断 / 语言泄漏 / 空拍巨拍 / 复读玩家原话 / 说话者不在场 /
  建议常驻 / 开卷欢迎通告 / 地图-在场四面一致 / 回合时长
成本: 默认 2 本 × 2 回合 = 4 次 LLM 调用/晚, 几分钱。巡完即删档, 不留垃圾。
铁律: 只用 QA 账号 (qa@lpqa.com) 的档, 永不触碰真实玩家存档。
"""
import argparse
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

import httpx  # noqa: E402

BASE = os.environ.get("QA_BASE", "http://127.0.0.1:8100/api/v1")
N_STORIES = int(os.environ.get("QA_STORIES", "2"))
N_TURNS = int(os.environ.get("QA_TURNS", "2"))
TURN_TIMEOUT = 240
QA_EMAIL = "qa@lpqa.com"

# 通用玩家台词: 任何剧本都说得通; 中文输入也顺带压英文本子的翻译链路
TURN_INPUTS = [
    ("do", "我放慢脚步环顾四周，留意此刻谁在场、这里正在发生什么。"),
    ("say", "和我说说，眼下这里最要紧的事是什么？"),
]

CJK = re.compile(r"[一-鿿]{2,}")
# 引擎里允许出现的中文前缀标记 (parser 靠它们) — 不算泄漏
MARKER_OK = re.compile(r"^(好感|心动|背景|回应|【已读】|【沉默】)")


def _qa_token():
    """QA 账号找不到就当场造 (直连库, 不走注册页); 铸会话 token。"""
    from app.db import SessionLocal
    from app.models import User
    from app.security import hash_password, make_session_token
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == QA_EMAIL).first()
        if not u:
            u = User(email=QA_EMAIL, password_hash=hash_password(uuid.uuid4().hex),
                     dob=datetime(1990, 1, 1), accepted_tos=True)
            db.add(u)
            db.commit()
            db.refresh(u)
        return make_session_token(u.id), u.id
    finally:
        db.close()


def _pick_stories(client, only=None):
    """轮换: 按天数偏移取 N 本, 一周把货架巡个遍。"""
    rows = client.get("/stories").json().get("items") or []
    if only:
        rows = [s for s in rows if s["title"] == only or s["id"] == only]
        return rows[:1]
    if not rows:
        return []
    day = datetime.now(timezone.utc).timetuple().tm_yday
    off = (day * N_STORIES) % len(rows)
    return [rows[(off + i) % len(rows)] for i in range(min(N_STORIES, len(rows)))]


def _play_turn(client, rid, channel, text):
    """走真 SSE 流 (玩家的路), 收齐事件; 返回 (事件流摘要, TTFT, 总时长)。"""
    t0 = time.time()
    ttft = None
    events = []
    with client.stream("POST", f"/runs/{rid}/play",
                       json={"input": text, "channel": channel,
                             "client_turn_id": uuid.uuid4().hex},
                       timeout=TURN_TIMEOUT) as r:
        for line in r.iter_lines():
            if not line.startswith("data: "):
                continue
            try:
                ev = json.loads(line[6:])
            except Exception:
                continue
            if ttft is None and ev.get("event") in ("token", "beat"):
                ttft = time.time() - t0
            events.append(ev)
    return events, ttft, time.time() - t0


def _judge(story, beats, turns_meta, state, suggestions, phone, mapv, feed):
    """体验判官: 全机械, 零 LLM。返回 (红灯列表, 提醒列表)。"""
    en = (story.get("language") or "zh") == "en" if isinstance(story, dict) else False
    errs, warns = [], []
    player_lines = {t[1] for t in TURN_INPUTS}
    here_names = {c.get("name") for c in (state.get("here") or [])}

    for b in beats:
        t = (b.get("text") or "").strip()
        typ = b.get("type") or ""
        spk = b.get("speaker_name") or ""
        if not t:
            errs.append(f"空拍 (seq={b.get('seq')})")
            continue
        if len(t) > 900:
            warns.append(f"巨拍 {len(t)} 字 (seq={b.get('seq')})")
        if t in player_lines and b.get("author") != "player" and spk != "我":
            errs.append(f"复读玩家原话 (seq={b.get('seq')})")
        if en and b.get("author") != "player":
            # 玩家拍豁免: 夜巡故意用中文输入压翻译链路 (TURN_INPUTS 注释),
            # 首跑实弹: 判官把自己打的中文判成「引擎漏中文」— 用坏尺子量
            if CJK.search(t) and not MARKER_OK.match(t):
                errs.append(f"英文本子漏中文: …{CJK.search(t).group()}… (seq={b.get('seq')})")
            # 半词截断: 以字母收尾且长度贴着某个硬截口 (60/80/160 及其英文双倍) = 强信号
            if t[-1].isalpha() and not t.endswith(("I", "a", "A")):
                near_cap = any(abs(len(t) - c) <= 2 for c in (60, 80, 120, 160))
                if near_cap:
                    errs.append(f"疑似半词截断 @len={len(t)}: …{t[-24:]} (seq={b.get('seq')})")
                elif len(t) > 40:
                    warns.append(f"句尾无标点: …{t[-18:]} (seq={b.get('seq')})")

    # 最后一回合的说话者必须在场 (画外音有专门通路, 对话拍不许)
    last_turn_speakers = {b.get("speaker_name") for b in beats[-8:]
                         if b.get("type") == "dialogue" and b.get("author") != "player"
                         and b.get("speaker_name")}
    ghosts = last_turn_speakers - here_names - {"我"}
    if ghosts and here_names:
        warns.append(f"收尾回合的说话者不在最终在场名单: {sorted(ghosts)} (可能是回合内离场, 人查)")

    # 建议常驻 (在 GET /runs 顶层, 不在 state 里 — 判官自己踩过这坑)
    if not suggestions:
        errs.append("回合后没有建议 (建议常驻回归)")
    # 🎭 建议视角: 这是玩家的下一步 — 「你/You」开头 = 角色在劝玩家, 视角串了
    # (Yi 实弹 2026-08-02 二犯; 引擎已有护栏, 这里盯复发)
    for sg in suggestions or []:
        if re.match(r"^(你|請你|请你|You\b|Your\b)", str(sg), re.IGNORECASE):
            errs.append(f"建议串了角色视角: 「{sg}」")
        if en and CJK.search(str(sg)):
            errs.append(f"英文本子建议冒中文: 「{sg}」")

    # 📣 开卷欢迎通告
    posts = (feed or {}).get("posts") or []
    if not any(p.get("welcome") for p in posts):
        errs.append("feed 没有开卷欢迎通告")

    # 🗺 四面一致: 地图玩家所在节点的人 == state.here (位置真源法条的 E2E 面)
    nodes = (mapv or {}).get("nodes") or []
    here_node = next((n for n in nodes if n.get("here")), None)
    if here_node is not None:
        map_chars = set(here_node.get("chars") or [])
        if map_chars != here_names:
            errs.append(f"地图与在场打架: 地图={sorted(map_chars)} 在场={sorted(here_names)}")
    # 📞 通讯录与位置同源: away 的人不许同时标 here
    for row in (phone or {}).get("contacts") or []:
        if row.get("away") and row.get("here"):
            errs.append(f"通讯录自相矛盾: {row.get('name')} 同时 away+here")

    # ⏱ 回合时长
    for i, (ttft, total) in enumerate(turns_meta):
        if total > 120:
            errs.append(f"回合{i + 1} 总时长 {total:.0f}s (>120s)")
        elif total > 75:
            warns.append(f"回合{i + 1} 偏慢 {total:.0f}s")
    return errs, warns


def tour_one(client, story):
    sid, title = story["id"], story["title"]
    masks = client.get("/personas").json()
    pid = masks[0]["id"] if masks else client.post(
        "/personas", json={"name": "夜巡员", "pronouns": "they"}).json()["id"]
    r = client.post("/runs", json={"story_id": sid, "persona_id": pid,
                                   "mode": "character", "player_character_id": None},
                    timeout=180)
    if r.status_code >= 300:
        return [f"开档失败 HTTP {r.status_code}: {r.text[:120]}"], [], None
    rid = r.json()["id"]
    turns_meta = []
    try:
        for ch, text in TURN_INPUTS[:N_TURNS]:
            _, ttft, total = _play_turn(client, rid, ch, text)
            turns_meta.append((ttft, total))
        beats = client.get(f"/runs/{rid}/play").json()
        run_full = client.get(f"/runs/{rid}").json()
        state = run_full.get("state") or {}
        suggestions = run_full.get("suggestions") or []
        phone = client.get(f"/runs/{rid}/phone").json()
        mapv_r = client.get(f"/runs/{rid}/map")
        mapv = mapv_r.json() if mapv_r.status_code == 200 else {}
        feed_r = client.get(f"/runs/{rid}/social")
        feed = feed_r.json() if feed_r.status_code == 200 else {}
        full_story = client.get(f"/stories/{sid}").json()
        errs, warns = _judge(full_story, beats, turns_meta, state, suggestions, phone, mapv, feed)
        return errs, warns, rid
    finally:
        client.delete(f"/runs/{rid}")   # 巡完即删 — QA 账号自己的档, 不留垃圾


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", help="点名巡某本 (标题或 id)")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    token, _uid = _qa_token()
    client = httpx.Client(base_url=BASE, cookies={"lp_session": token}, timeout=60)
    stories = _pick_stories(client, a.story)
    if not stories:
        print("没有可巡的剧本")
        return 1
    red = 0
    print(f"🌙 夜巡 {datetime.now().strftime('%F %H:%M')} · {len(stories)} 本 × {N_TURNS} 回合")
    for s in stories:
        try:
            errs, warns, rid = tour_one(client, s)
        except Exception as e:   # 单本炸了不拖垮整晚
            errs, warns = [f"巡演炸了: {type(e).__name__}: {e}"], []
        mark = "❌" if errs else "✅"
        print(f"{mark} 《{s['title']}》")
        for e in errs:
            print(f"    🔴 {e}")
        for w in warns:
            print(f"    🟡 {w}")
        red += len(errs)
    print(f"—— 夜巡收官: {'红灯 ' + str(red) + ' 处' if red else '全绿'} ——")
    return 1 if red else 0


if __name__ == "__main__":
    raise SystemExit(main())
