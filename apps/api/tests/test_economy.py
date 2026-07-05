"""💰📋🌊🔄 sandbox economy: money is a hard ledger (spending clamps at the balance);
quests pay on delivery and fail past their deadline; the world mints its own news for
each missed real day (told once); rebirth resets the player's side but never the
world's."""

from datetime import datetime, timedelta, timezone

from app.engine import runtime

TZ = timezone(timedelta(hours=8))

STORY = {
    "story": {"id": "s",
              "sandbox": {"enabled": True, "real_time": True,
                          "currency": "铜币", "start_money": 50},
              "characters": [{"id": "a", "name": "甲", "is_lead": True}],
              "acts": [{"index": 1, "title": "无尽"}],
              "locations": [{"id": "hall", "name": "门厅", "detail": "x", "exits": []}]},
    "secrets": [],
}


class EcoLLM:
    def __init__(self, **fields):
        self.fields = fields
        self.prompts = []

    def generate(self, prompt):
        if prompt.get("risk_judge"):
            return {"risk": 100}
        if prompt.get("world_news"):
            self.prompts.append(prompt)
            return {"text": "码头夜里走水，烧了半间货栈"}
        if prompt.get("intro") or prompt.get("observe") or prompt.get("suggest") \
                or prompt.get("arrive") or prompt.get("farewell") or prompt.get("offscreen") \
                or prompt.get("opening_hook"):
            return {"beats": [{"type": "description", "speaker_name": None, "text": "x"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}
        self.prompts.append(prompt)
        out = {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"), "text": "嗯"}],
               "affinity_delta": 0, "advance_act": False, "ending": None}
        if prompt.get("group_mode") in ("primary", None):
            out.update(self.fields)
        return out


def _at(monkeypatch, d, h=9):
    monkeypatch.setattr(runtime, "_now", lambda: datetime(2026, 7, d, h, tzinfo=TZ))


def _st(money=50):
    st = runtime.default_state()
    st["location_id"] = "hall"
    st["money"] = money
    return st


def test_money_is_a_hard_ledger(monkeypatch):
    _at(monkeypatch, 4)
    llm = EcoLLM(money_delta="+40|工钱", next_speakers=[])
    out = runtime.run_turn(STORY, _st(), {"name": "我"}, "结账", channel="say", llm=llm)
    st = out["state"]
    assert st["money"] == 90 and st["money_log"][-1]["delta"] == 40
    assert any(m["kind"] == "money" and m["delta"] == 40 for m in out["moments"])
    # the prompt knows the pocket, so the model can't overspend knowingly…
    assert (llm.prompts[0].get("player_money") or {}).get("amount") == 50
    # …and even if it tries, the ledger clamps at zero
    out2 = runtime.run_turn(STORY, st, {"name": "我"}, "全给你", channel="say",
                            llm=EcoLLM(money_delta="-500|豪掷", next_speakers=[]))
    assert out2["state"]["money"] == 0
    assert out2["state"]["money_log"][-1]["delta"] == -90


def test_quests_pay_on_delivery_and_rot_past_deadline(monkeypatch):
    _at(monkeypatch, 4)
    out = runtime.run_turn(STORY, _st(), {"name": "我"}, "行，我接了", channel="say",
                           llm=EcoLLM(quest_accepted="送三坛酒到码头|40|2", next_speakers=[]))
    st = out["state"]
    q = st["quests"][0]
    assert q["status"] == "open" and q["reward"] == 40 and q["deadline_day"] == 3
    assert any(m["kind"] == "quest" and m["status"] == "open" for m in out["moments"])
    # delivered → paid
    out2 = runtime.run_turn(STORY, st, {"name": "我"}, "酒送到了", channel="say",
                            llm=EcoLLM(quest_done="三坛酒", next_speakers=[]))
    st2 = out2["state"]
    assert st2["quests"][0]["status"] == "done" and st2["money"] == 90
    # a second quest left to rot: three real days later it has failed
    st3 = runtime.run_turn(STORY, st2, {"name": "我"}, "这个也接", channel="say",
                           llm=EcoLLM(quest_accepted="替人守一夜铺子|20|1", next_speakers=[]))["state"]
    _at(monkeypatch, 8)
    out4 = runtime.run_turn(STORY, st3, {"name": "我"}, "回来了", channel="say",
                            llm=EcoLLM(next_speakers=[]))
    rot = [q for q in out4["state"]["quests"] if q["title"] == "替人守一夜铺子"][0]
    assert rot["status"] == "failed"
    assert any(m["kind"] == "quest" and m["status"] == "failed" for m in out4["moments"])


def test_world_news_minted_per_missed_day_and_told_once(monkeypatch):
    _at(monkeypatch, 4)
    st = runtime.run_turn(STORY, _st(), {"name": "我"}, "你好", channel="say",
                          llm=EcoLLM(next_speakers=[]))["state"]
    _at(monkeypatch, 7)      # three days away → capped at 2 pieces of news
    llm = EcoLLM(next_speakers=[])
    st = runtime.run_turn(STORY, st, {"name": "我"}, "回来了", channel="say", llm=llm)["state"]
    assert len(st["world_news"]) == 2
    # the first serving marks one heard, delivered into the primary's prompt
    assert any("走水" in (p.get("news") or "") for p in llm.prompts)
    assert sum(1 for n in st["world_news"] if n["heard"]) == 1


def test_rebirth_resets_the_player_never_the_world():
    st = _st(money=3)
    st["player_hp"] = "dead"
    st["identity"] = "码头的账房先生"
    st["rel"] = {"a": {"closeness": 30, "romance": 10}}
    st["inventory"] = [{"name": "旧怀表"}]
    st["place_facts"] = {"hall": [{"text": "正门被撞开了一道缝", "label": ""}]}
    st["world_news"] = [{"day": 2, "text": "x", "heard": True}]
    st["dead_character_ids"] = ["b"]
    beats = runtime.reincarnate(STORY, st)
    assert st["player_hp"] == "healthy" and st["inventory"] == [] and st["rel"] == {}
    assert st["money"] == 50 and st["identity"] is None       # fresh start money
    assert st["past_lives"][0]["identity"] == "码头的账房先生"
    assert any("账房先生" in r["text"] for r in st["rumors"])  # the old life became a rumor
    # the world keeps every ledger it lived through
    assert st["place_facts"]["hall"][0]["text"] == "正门被撞开了一道缝"
    assert st["world_news"] and st["dead_character_ids"] == ["b"]
    assert any("转生" in b["text"] for b in beats)


def test_declared_powers_reach_the_scene_and_the_judge(monkeypatch):
    _at(monkeypatch, 4)
    st = _st()
    st["powers"] = ["状态之眼：看穿他人好感", "每日一次的抽卡"]
    llm = EcoLLM(next_speakers=[])
    runtime.run_turn(STORY, st, {"name": "我"}, "我用状态之眼看她", channel="say", llm=llm)
    assert llm.prompts[0].get("player_powers") == st["powers"]

    class Judge:
        def __init__(self):
            self.risk_prompt = None

        def generate(self, prompt):
            if prompt.get("risk_judge"):
                self.risk_prompt = prompt
                return {"risk": 90}
            if prompt.get("intro") or prompt.get("observe") or prompt.get("suggest") \
                    or prompt.get("arrive") or prompt.get("farewell") \
                    or prompt.get("offscreen") or prompt.get("world_news"):
                return {}
            return {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"),
                               "text": "嗯"}], "affinity_delta": 0, "advance_act": False,
                    "ending": None, "next_speakers": []}

    j = Judge()
    runtime.run_turn(STORY, st, {"name": "我"}, "发动抽卡", channel="do", llm=j)
    assert j.risk_prompt and j.risk_prompt.get("powers") == st["powers"]
