# -*- coding: utf-8 -*-
"""📋→🧭 短期任务: the quest ledger now takes UNPAID leads too — a concrete
objective someone hands the player in dialogue (去某处取某物) books as a tracked
task (kind=lead), not something to keep in your head."""
from app.engine import runtime
from app.engine.llm import MockLLM

SB = {"story": {"id": "ql", "sandbox": {"enabled": True},
                "characters": [{"id": "c1", "name": "Mara", "is_lead": True,
                                "persona_text": "a"}],
                "acts": [{"index": 1}], "locations": []}, "secrets": []}


class LeadLLM(MockLLM):
    """Mock director that hands out one unpaid lead on its first director call."""
    def __init__(self):
        super().__init__()
        self.fired = False

    def generate(self, prompt):
        out = super().generate(prompt)
        if isinstance(out, dict) and "beats" in out and not self.fired:
            self.fired = True
            out["quest_accepted"] = "去档案室取值班日志|0|0"
        return out


def test_unpaid_lead_books_as_tracked_objective():
    st = runtime.default_state()
    o = runtime.run_turn(SB, st, {"name": "我"}, "值班日志在哪", channel="say",
                         llm=LeadLLM())
    qs = o["state"]["quests"]
    assert len(qs) == 1
    assert qs[0]["kind"] == "lead" and qs[0]["reward"] == 0 and qs[0]["status"] == "open"
    assert qs[0]["title"] == "去档案室取值班日志"
    assert any(m.get("kind") == "quest" and m.get("status") == "open"
               for m in o.get("moments") or [])
    assert any("记在了心里" in (b.get("text") or "") for b in o.get("beats") or [])


def test_paid_job_still_books_as_job():
    class JobLLM(LeadLLM):
        def generate(self, prompt):
            out = MockLLM.generate(self, prompt)
            if isinstance(out, dict) and "beats" in out and not self.fired:
                self.fired = True
                out["quest_accepted"] = "送三坛酒到码头|40|2"
            return out
    st = runtime.default_state()
    o = runtime.run_turn(SB, st, {"name": "我"}, "有活吗", channel="say", llm=JobLLM())
    qs = o["state"]["quests"]
    assert len(qs) == 1 and qs[0]["kind"] == "job" and qs[0]["reward"] == 40
    assert any("应下了这桩事" in (b.get("text") or "") for b in o.get("beats") or [])
