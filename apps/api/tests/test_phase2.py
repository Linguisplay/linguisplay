"""恋与深空-direction retention pieces + 📱 小手机 phase 2.

① 你不在的时候 (offline pulse): a comeback turn makes the absent hearts reach out —
   warmest first, capped; a LONG absence upgrades the warmest to a real LETTER.
② ✨ 稀有奇遇 (golden moments): program-rolled rare drops, model-written, album-bound.
③ 💞 名场面收藏 (album): tier-ups / dates / endings / goldens collect; journal serves it.
④ 📺 下幕预告: leaving mid-story teases the NEXT act's title (never its events).
⑤ 📞 通话: live calls under the same gate; 作息 AWAY → no pickup; in-scene → 当面说.
⑥ 🔓 短信套话: probing over text/call REGISTERS asks and can crack a layer right in
   the thread — while locked bodies still never enter the prompt.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

import pytest  # noqa: E402

from app.engine import runtime  # noqa: E402


STORY = {
    "story": {"id": "s", "tuning": {"turns_per_slot": 1, "min_turns_per_act": 0},
              "phone": {"device": "手机"},
              "characters": [
                  {"id": "a", "name": "甲", "is_lead": True, "home_location_id": "hall"},
                  {"id": "b", "name": "乙", "home_location_id": "alley",
                   "eq_style": "嘴硬心软"},
                  {"id": "c", "name": "丙", "home_location_id": "alley"},
              ],
              "acts": [{"index": 1, "title": "第一章"},
                       {"index": 2, "title": "第二章"}],
              "locations": [{"id": "hall", "name": "门厅", "detail": "一盏吊灯", "exits": ["后巷"]},
                            {"id": "alley", "name": "后巷", "detail": "潮湿", "exits": ["门厅"]}]},
    "secrets": [
        {"id": "s1", "character_id": "b", "title": "夜里的事",
         "fragments": [{"id": "f1", "content": "PHONE_CRACKED", "retrieval_key": "夜",
                        "known_by_character_ids": ["b"],
                        "unlock": {"asks_min": 2}},
                       {"id": "f2", "content": "DEEP_LOCKED", "retrieval_key": "更深",
                        "known_by_character_ids": ["b"],
                        "unlock": {"affinity_min": 999}}]},
    ],
}


class P2LLM:
    """Scripted stand-in: records prompts, answers each branch deterministically."""

    def __init__(self, **fields):
        self.fields = fields
        self.prompts = []

    def generate(self, prompt):
        for key in ("compose_msg", "compose_letter", "phone_reply", "golden_moment",
                    "parting"):
            if prompt.get(key):
                self.prompts.append(prompt)
                return self.fields.get(key, {} if key != "phone_reply"
                                       else {"msgs": ["嗯。"], "closeness": 0, "romance": 0})
        if prompt.get("risk_judge"):
            return {"risk": 100}
        if prompt.get("suggest") or prompt.get("arrive") or prompt.get("offscreen") \
                or prompt.get("farewell") or prompt.get("summarize"):
            return {}
        if prompt.get("intro") or prompt.get("observe") or prompt.get("transition"):
            return {"beats": [{"type": "description", "speaker_name": None, "text": "x"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}
        self.prompts.append(prompt)
        out = {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"),
                          "text": "嗯"}],
               "affinity_delta": 0, "advance_act": False, "ending": None,
               "next_speakers": []}
        out.update(self.fields.get("director", {}))
        return out


def _met(st, *ids):
    st["met_ids"] = sorted(set(st.get("met_ids") or []) | set(ids))
    return st


class FixedRng:
    def __init__(self, v):
        self.v = v

    def randint(self, a, b):
        return min(max(self.v, a), b)

    def sample(self, seq, k):
        return list(seq)[:k]


# ── ① 你不在的时候 ────────────────────────────────────────────────────────────────

def test_offline_pulse_warmest_absent_hearts_text_first():
    st = _met(runtime.default_state(), "b", "c")
    st["location_id"] = "hall"
    st["rel"] = {"b": {"closeness": 60, "romance": 70},   # lover — reaches out first
                 "c": {"closeness": 45, "romance": 0}}    # friend — second
    out = runtime.run_turn(STORY, st, {"name": "我"}, "我回来了", channel="say",
                           llm=P2LLM(), returning=True, away_hours=8)
    threads = out["state"]["phone"]["threads"]
    assert "b" in threads and threads["b"]["unread"] >= 1
    assert "c" in threads    # cap is 2 and only 2 candidates exist
    assert any(m["kind"] in ("phone", "mail") for m in out["moments"])


def test_offline_pulse_long_absence_earns_a_letter():
    st = _met(runtime.default_state(), "b")
    st["location_id"] = "hall"
    st["rel"] = {"b": {"closeness": 60, "romance": 70}}
    llm = P2LLM(compose_letter={"subject": "灯下", "body": "LETTER_BODY 那晚之后我一直想说。乙"})
    out = runtime.run_turn(STORY, st, {"name": "我"}, "我回来了", channel="say",
                           llm=llm, returning=True, away_hours=72)
    box = out["state"]["phone"]["mail"]
    assert len(box) == 1 and box[0]["subject"] == "灯下" and not box[0]["read"]
    assert "LETTER_BODY" in box[0]["body"]
    assert any(m["kind"] == "mail" for m in out["moments"])
    assert out["phone_unread"] >= 1          # letters count on the badge


def test_offline_pulse_needs_returning_and_a_reason():
    st = _met(runtime.default_state(), "b")
    st["location_id"] = "hall"
    st["rel"] = {"b": {"closeness": 60, "romance": 70}}
    out = runtime.run_turn(STORY, st, {"name": "我"}, "你好", channel="say",
                           llm=P2LLM(), returning=False)
    assert "b" not in (out["state"]["phone"].get("threads") or {})
    # a stranger doesn't text just because time passed
    st2 = _met(runtime.default_state(), "b")
    st2["location_id"] = "hall"
    out2 = runtime.run_turn(STORY, st2, {"name": "我"}, "你好", channel="say",
                            llm=P2LLM(), returning=True, away_hours=8)
    assert "b" not in (out2["state"]["phone"].get("threads") or {})


# ── ② 稀有奇遇 + ③ 相册 ──────────────────────────────────────────────────────────

def test_golden_moment_fires_collects_and_cools_down(monkeypatch):
    monkeypatch.setattr(runtime, "_rng", FixedRng(1))     # the roll always hits
    llm = P2LLM(golden_moment={"title": "檐下躲雨", "text": "GOLD_TEXT 他把伞塞进你手里。"})
    st = _met(runtime.default_state(), "a")
    st["location_id"] = "hall"
    out = runtime.run_turn(STORY, st, {"name": "我"}, "聊聊", channel="say", llm=llm)
    st = out["state"]
    assert any("GOLD_TEXT" in (b.get("text") or "") and "✨" in b["text"]
               for b in out["beats"])
    assert any(m["kind"] == "golden" and m["title"] == "檐下躲雨" for m in out["moments"])
    assert st["album"] and st["album"][-1]["kind"] == "golden"
    assert st["golden_cd"] == runtime.DEFAULT_TUNING["golden_cooldown"]
    assert st["rel"]["a"]["closeness"] >= 2               # the drop warms the bond
    # cooldown holds: the very next turn cannot fire again even on a hot roll
    out2 = runtime.run_turn(STORY, st, {"name": "我"}, "再聊聊", channel="say", llm=llm)
    assert not any(m["kind"] == "golden" for m in out2["moments"])


def test_golden_moment_off_or_empty_never_beats(monkeypatch):
    monkeypatch.setattr(runtime, "_rng", FixedRng(1))
    st = _met(runtime.default_state(), "a")
    st["location_id"] = "hall"
    out = runtime.run_turn(STORY, st, {"name": "我"}, "聊聊", channel="say", llm=P2LLM())
    assert not any("✨" in (b.get("text") or "") for b in out["beats"])   # llm returned {}
    off = {"story": {**STORY["story"], "tuning": {**STORY["story"]["tuning"],
                                                  "golden_chance": 0}},
           "secrets": STORY["secrets"]}
    out2 = runtime.run_turn(off, st, {"name": "我"}, "聊聊", channel="say",
                            llm=P2LLM(golden_moment={"title": "x", "text": "y"}))
    assert not any(m["kind"] == "golden" for m in out2["moments"])


def test_rel_up_collects_into_album_and_lover_writes_a_letter():
    st = _met(runtime.default_state(), "a")
    st["location_id"] = "hall"
    st["rel"] = {"a": {"closeness": 58, "romance": 59}}   # one warm beat from 恋人
    llm = P2LLM(director={"rel_event": {"kind": "心动", "evidence": "我心里有你"}},   # 事件记账制: 法条 +2亲近/+4心动 跨过恋人线
                compose_letter={"subject": "给你", "body": "LOVE_LETTER 甲"})
    out = runtime.run_turn(STORY, st, {"name": "我"}, "我心里有你", channel="say", llm=llm)
    st = out["state"]
    assert any(m["kind"] == "rel_up" and m["mode"] == "lover" for m in out["moments"])
    assert any(a["kind"] == "rel_up" for a in st["album"])
    box = st["phone"]["mail"]
    assert box and "LOVE_LETTER" in box[0]["body"]        # 恋人的第一封信
    assert runtime.journal(STORY, st)["album"]            # the journal serves it


# ── ④ 下幕预告 ───────────────────────────────────────────────────────────────────

def test_parting_hook_teases_next_act_title_only():
    st = runtime.default_state()
    st["location_id"] = "hall"
    beats = runtime.build_parting_hook(STORY, st, {"name": "我"}, llm=P2LLM())
    assert len(beats) == 2
    assert "下幕预告" in beats[1]["text"] and "第二章" in beats[1]["text"]
    # final act → nothing left to tease
    st2 = runtime.default_state()
    st2["act"] = 2
    assert all("下幕预告" not in b["text"]
               for b in runtime.build_parting_hook(STORY, st2, {"name": "我"}, llm=P2LLM()))


# ── ⑤ 通话 ───────────────────────────────────────────────────────────────────────

def test_phone_call_speaks_lives_in_thread_with_ambient():
    st = _met(runtime.default_state(), "b")
    st["location_id"] = "hall"
    llm = P2LLM(phone_reply={"msgs": ["是我。", "怎么这个点打来？"],
                             "ambient": "那头有风声", "closeness": 1, "romance": 0})
    view = runtime.phone_call(STORY, st, {"name": "我"}, "b", "喂，是你吗", llm=llm)
    assert view["replied"] is True
    msgs = view["msgs"]
    assert all(m.get("call") for m in msgs)
    assert msgs[0]["from"] == "me" and msgs[0]["text"].startswith("📞")
    assert any(m["from"] == "sys" and "风声" in m["text"] for m in msgs)
    assert [m["text"] for m in msgs if m["from"] == "them"] == ["是我。", "怎么这个点打来？"]
    assert llm.prompts[0]["call"] is True
    assert st["rel"]["b"]["closeness"] >= 1


def test_phone_call_refuses_in_scene_and_away_never_picks_up():
    st = _met(runtime.default_state(), "b", "c")
    st["location_id"] = "alley"                            # 乙 lives here — face to face
    with pytest.raises(ValueError):
        runtime.phone_call(STORY, st, {"name": "我"}, "b", "喂", llm=P2LLM())
    # a scheduled character not covered this hour is AWAY → 无人接听, no LLM exchange
    away_story = {"story": {**STORY["story"], "characters": [
        STORY["story"]["characters"][0],
        {**STORY["story"]["characters"][1],
         "schedule": [{"from_act": 1, "location_id": "alley", "slots": ["夜"]}]},
    ]}, "secrets": []}
    st2 = _met(runtime.default_state(), "b")
    st2["location_id"] = "hall"
    st2["clock"] = {"day": 1, "slot": 0, "turns_in_slot": 0}   # 晨 — not their hour
    llm = P2LLM()
    view = runtime.phone_call(away_story, st2, {"name": "我"}, "b", "喂", llm=llm)
    assert view["replied"] is False
    assert any("无人接听" in m["text"] for m in view["msgs"])
    assert not llm.prompts                                  # never reached the model


def test_lover_afterglow_comes_as_an_incoming_call():
    st = _met(runtime.default_state(), "b")
    st["location_id"] = "hall"
    st["rel"] = {"b": {"closeness": 60, "romance": 70}}
    st["phone"] = {"threads": {}, "seen": {"b": runtime._time_index(st)}}
    out = runtime.run_turn(STORY, st, {"name": "我"}, "接着走吧", channel="say",
                           llm=P2LLM())
    th = out["state"]["phone"]["threads"]["b"]
    assert any(m.get("call") for m in th["msgs"])          # the note arrived as 来电
    assert any(m["kind"] == "phone" for m in out["moments"])


# ── ⑥ 短信套话 ───────────────────────────────────────────────────────────────────

def test_probing_over_text_registers_asks_and_cracks_the_layer():
    st = _met(runtime.default_state(), "b")
    replies = []

    def send(text):
        llm = P2LLM(phone_reply={"msgs": ["……"], "closeness": 0, "romance": 0})
        v = runtime.phone_send(STORY, st, {"name": "我"}, "b", text, llm=llm)
        replies.append((v, llm))
        return v, llm

    v1, llm1 = send("那天夜里到底发生了什么")
    assert st["asks"].get("s1") == 1
    assert v1["unlocked"] == [] and "f1" not in st["unlocked_fragment_ids"]
    assert "PHONE_CRACKED" not in str(llm1.prompts[0])     # still locked → never in prompt
    v2, llm2 = send("你还没说，那个夜里呢")
    assert st["asks"].get("s1") == 2
    assert "f1" in st["unlocked_fragment_ids"]
    assert v2["unlocked"] == ["夜里的事"]                   # the toastable title
    ctx = llm2.prompts[0]["context"]
    assert any("PHONE_CRACKED" in (r.get("content") or "") for r in ctx["new_reveal"])
    assert "DEEP_LOCKED" not in str(llm2.prompts[0])       # the deeper layer holds
    # the crack is remembered in the character's 大事记
    assert any("夜里的事" in e["text"] for e in st["rel_log"]["b"])


def test_probing_someone_who_doesnt_know_unlocks_but_never_voices():
    st = _met(runtime.default_state(), "b", "c")
    st["asks"] = {"s1": 1}                                  # one ask away
    llm = P2LLM(phone_reply={"msgs": ["我不清楚。"], "closeness": 0, "romance": 0})
    v = runtime.phone_send(STORY, st, {"name": "我"}, "c", "夜里的事你知道吗", llm=llm)
    assert "f1" in st["unlocked_fragment_ids"]              # the gate itself is global
    assert v["unlocked"] == []                              # but 丙 has nothing to voice
    ctx = llm.prompts[0]["context"]
    assert not ctx.get("new_reveal")
    assert "PHONE_CRACKED" not in str(llm.prompts[0])       # known_by holds over text


# ── HTTP wiring: /call, /mail, and the journal album through the API ─────────────

def test_phase2_endpoints_wired_through_http():
    from fastapi.testclient import TestClient
    from app.db import Base, engine
    from app.main import app

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        c.post("/api/v1/auth/signup",
               json={"email": "p2@x.com", "password": "password1",
                     "dob": "1990-01-01", "accepted_tos": True})
        story = c.post("/api/v1/stories", json={
            "title": "Phase2", "visibility": "public",
            "characters": [{"id": "c1", "name": "M", "is_lead": True,
                            "home_location_id": "hall"},
                           {"id": "c2", "name": "N", "home_location_id": "alley"}],
            "locations": [{"id": "hall", "name": "门厅", "detail": "d", "exits": ["后巷"]},
                          {"id": "alley", "name": "后巷", "detail": "d", "exits": ["门厅"]}],
        }).json()
        sid = story["id"]
        c.post(f"/api/v1/stories/{sid}/publish")
        persona = c.post("/api/v1/personas", json={"name": "Ash", "pronouns": "they"}).json()
        run = c.post("/api/v1/runs", json={"story_id": sid, "persona_id": persona["id"]}).json()
        rid = run["id"]
        # mailbox starts empty; a bogus letter 404s
        box = c.get(f"/api/v1/runs/{rid}/mail").json()
        assert box["mail"] == [] and box["unread"] == 0
        assert c.get(f"/api/v1/runs/{rid}/mail/nope").status_code == 404
        # calling a stranger → readable 400 (route + validation wired)
        r = c.post(f"/api/v1/runs/{rid}/phone/c2/call", json={"text": "喂"})
        assert r.status_code == 400 and "不认识" in r.json()["detail"]
        # meet M in the hall, then calling them is refused — they're right here
        assert c.post(f"/api/v1/runs/{rid}/play",
                      json={"input": "你好", "channel": "say"}).status_code == 200
        r2 = c.post(f"/api/v1/runs/{rid}/phone/c1/call", json={"text": "喂"})
        assert r2.status_code == 400 and "身边" in r2.json()["detail"]
        # journal carries the album field
        assert "album" in c.get(f"/api/v1/runs/{rid}/journal").json()
