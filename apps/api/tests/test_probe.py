"""Model-judged ask/event detection (anti keyword-stuffing). Keyword hits are
PROVISIONAL; the primary director call returns `probed`/`occurred` judgments and the
engine reconciles: denied keyword asks roll back (unless they already unlocked —
sticky), genuine probes the keywords missed get counted, denied keyword events untrigger,
confirmed events trigger. No judgment (mock/prose) → pure keyword behavior stands."""

from app.engine import runtime

STORY = {
    "story": {
        "id": "s",
        "characters": [{"id": "c1", "name": "Mara", "is_lead": True, "persona_text": "a"}],
        "acts": [
            {"index": 1, "title": "一",
             "events": [{"id": "ev1", "what_happens": "警报响起"}]},
            {"index": 2, "title": "二"},
        ],
    },
    "secrets": [{
        "id": "sec1", "character_id": "c1", "title": "那本账",
        "fragments": [{
            "id": "f1", "content": "BODY_SECRET", "retrieval_key": "ledger",
            "known_by_character_ids": ["c1"],
            # asks_min=2 so a single provisional ask can't unlock anything this turn
            "unlock": {"affinity_min": 0, "act_min": 1, "asks_min": 2},
        }],
    }],
}


class JudgeLLM:
    """Returns a fixed judgment alongside a normal beat."""

    def __init__(self, probed=None, occurred=None):
        self.probed = probed
        self.occurred = occurred

    def generate(self, prompt):
        if prompt.get("intro") or prompt.get("observe") or prompt.get("suggest"):
            return {"beats": [{"type": "description", "speaker_name": None, "text": "x"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}
        out = {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"), "text": "嗯"}],
               "affinity_delta": 0, "advance_act": False, "ending": None}
        if self.probed is not None:
            out["probed"] = self.probed
        if self.occurred is not None:
            out["occurred"] = self.occurred
        return out


def test_keyword_stuffing_rolled_back_when_model_denies():
    st = runtime.default_state()
    # input contains the secret title verbatim (classic stuffing) but the model judges
    # the player wasn't genuinely probing → the provisional ask must roll back
    out = runtime.run_turn(STORY, st, {"name": "我"}, "那本账什么的随便啦，聊聊天气",
                           channel="say", llm=JudgeLLM(probed=[]))
    assert out["state"]["asks"].get("sec1", 0) == 0


def test_model_confirmed_probe_sticks():
    st = runtime.default_state()
    out = runtime.run_turn(STORY, st, {"name": "我"}, "那本账到底记了什么？",
                           channel="say", llm=JudgeLLM(probed=["那本账"]))
    assert out["state"]["asks"].get("sec1", 0) == 1


def test_paraphrase_probe_counted_even_without_keywords():
    st = runtime.default_state()
    # no title keywords in the input, but the model recognizes a genuine probe
    out = runtime.run_turn(STORY, st, {"name": "我"}, "你晚上偷偷在写的那个东西是什么？",
                           channel="say", llm=JudgeLLM(probed=["那本账"]))
    assert out["state"]["asks"].get("sec1", 0) == 1


def test_no_judgment_keeps_keyword_result():
    st = runtime.default_state()
    # JudgeLLM without probed → engine keeps the provisional keyword ask (mock/prose path)
    out = runtime.run_turn(STORY, st, {"name": "我"}, "跟我说说那本账",
                           channel="say", llm=JudgeLLM())
    assert out["state"]["asks"].get("sec1", 0) == 1


def test_sticky_unlock_survives_denial():
    # once a provisional ask actually unlocks a fragment, denial must not un-reveal it
    st = runtime.default_state()
    st["asks"] = {"sec1": 1}  # one genuine ask already on record
    out = runtime.run_turn(STORY, st, {"name": "我"}, "那本账！那本账！",
                           channel="say", llm=JudgeLLM(probed=[]))
    # the stuffed ask hit asks_min=2 and unlocked f1 this turn → unlock stays,
    # and the count backing it is not rolled back
    assert "f1" in out["state"]["unlocked_fragment_ids"]
    assert out["state"]["asks"].get("sec1", 0) == 2


def test_event_judgment_reconciles_both_ways():
    st = runtime.default_state()
    # keyword would fire ev1 ("警报" appears) but the model denies it happened
    out = runtime.run_turn(STORY, st, {"name": "我"}, "要是警报响起就糟了",
                           channel="say", llm=JudgeLLM(occurred=[]))
    assert "ev1" not in out["state"]["triggered_event_ids"]
    # no keywords, but the model says the event truly happened this turn
    out2 = runtime.run_turn(STORY, out["state"], {"name": "我"}, "（拉下手闸）",
                            channel="do", llm=JudgeLLM(occurred=["警报响起"]))
    assert "ev1" in out2["state"]["triggered_event_ids"]
