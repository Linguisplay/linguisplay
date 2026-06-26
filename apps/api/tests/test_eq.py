"""Emotional intelligence: the director reads the player's underlying emotion (情绪 line),
which is parsed out (not leaked as dialogue) and carried forward in run state for
cross-turn emotional continuity. The EQ guidance + per-character eq_style only shape the
live qwen prompt; here we lock the parse + state plumbing deterministically."""

from app.engine import qwen, runtime


def test_emotion_line_parsed_not_leaked_as_dialogue():
    reply = "\n".join([
        "旁白：他顿了顿，目光柔和下来。",
        "情绪：在逞强，其实想被安慰",
        "老周：别怕，有我在呢。",
        "好感：+2",
        "推进：否",
        "结局：无",
    ])
    out = qwen._parse_reply(reply, "老周", channel="say")
    assert out["player_emotion"] == "在逞强，其实想被安慰"
    texts = " ".join(b["text"] for b in out["beats"])
    assert "在逞强" not in texts                      # the read never appears in spoken/narrated text
    assert any(b["type"] == "dialogue" and "别怕" in b["text"] for b in out["beats"])
    assert out["affinity_delta"] == 2


def test_missing_emotion_line_is_neutral():
    out = qwen._parse_reply("旁白：风停了。\n老周：嗯。\n好感：0\n推进：否", "老周")
    assert out["player_emotion"] == ""


def test_eq_style_and_prior_emotion_injected_into_prompt():
    sys = qwen._build_system({
        "speaker_name": "龙卷风",
        "speaker_persona": "城寨话事人",
        "persona": {"name": "蔡妍"},
        "channel": "say",
        "context": {},
        "eq_style": "话少眼神重，体贴从不挂嘴上",
        "player_emotion": "强忍委屈",
    })
    assert "情商" in sys                       # the EQ guidance block is present
    assert "话少眼神重" in sys                  # this character's own EQ style is used
    assert "强忍委屈" in sys                    # prior emotional read carried in for continuity


def test_inter_character_eq_in_group_and_observer():
    base = {"speaker_name": "蓝信一", "speaker_persona": "城寨四子", "persona": {"name": "蔡妍"},
            "channel": "say", "context": {}, "cast": ["龙卷风", "十二少"]}
    # one-on-one: EQ aimed at 对方 (the player), no inter-character clause
    solo = qwen._build_system(base)
    assert "有来有往" not in solo
    # broadcast member + god/observer: EQ aimed at reading the OTHER characters
    member = qwen._build_system({**base, "group_mode": "member"})
    obs = qwen._build_system({**base, "observer": True})
    for s in (member, obs):
        assert "有来有往" in s and "各说各的" in s   # characters attune to each other, not monologue


def test_player_emotion_persists_across_turns():
    class EmoLLM:
        def generate(self, prompt):
            if prompt.get("intro") or prompt.get("observe"):
                return {"beats": [{"type": "description", "speaker_name": None, "text": "x"}],
                        "affinity_delta": 0, "advance_act": False, "ending": None}
            return {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"), "text": "嗯"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None,
                    "player_emotion": "放下戒备"}

    story = {"story": {"id": "s", "characters": [{"id": "c1", "name": "M", "is_lead": True}],
                       "acts": [{"index": 1, "title": "a"}]}, "secrets": []}
    st = runtime.default_state()
    assert st["player_emotion"] == ""
    out = runtime.run_turn(story, st, {"name": "我"}, "你好", channel="say", llm=EmoLLM())
    assert out["state"]["player_emotion"] == "放下戒备"  # the read is carried into next turn
