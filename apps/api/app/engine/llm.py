"""LLM seam. The runtime depends only on the `LLM` protocol; M3 drops in the real
model (Qwen/Claude via the old backend's adapters) without touching gating/runtime.

The mock is deterministic and, crucially, ONLY ever emits text built from the
context the gate handed it — never from locked fragments. That property is what
the engine tests assert, so the mock doubles as a leak tripwire.
"""

from __future__ import annotations

from typing import Any, Protocol


class LLM(Protocol):
    def generate(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """Direct one turn. Return:
        {
          "beats": [{type, speaker_name, text}, ...],
          "affinity_delta": int,   # how this player line moved the character (judged)
          "advance_act": bool,     # whether the scene should move to the next chapter
          "ending": None | {kind: "death"|"bad", reason: str},
                                   # set ONLY when the player's action is fatal/terminal
                                   # (e.g. blows up the building) — the run then concludes
          "location": None | str,  # destination place name IF the player moved this turn
                                   # (only honored if it matches an authored location)
        }
        Keys other than "beats" are optional; runtime reads them defensively with .get().
        """
        ...


def get_llm() -> "LLM":
    """Pick the LLM backend from settings. Default 'mock' keeps tests deterministic."""
    from ..config import get_settings

    s = get_settings()
    if s.llm_provider == "deepseek" and s.deepseek_api_key:
        from .qwen import DeepSeekLLM

        return DeepSeekLLM()
    if s.llm_provider == "qwen" and s.dashscope_api_key:
        from .qwen import QwenLLM

        return QwenLLM()
    return MockLLM()


class MockLLM:
    """Deterministic stand-in. Reflects gate decisions so behavior is observable."""

    def generate(self, prompt: dict[str, Any]) -> dict[str, Any]:
        # suggestions: mock returns none → runtime falls back to its deterministic template.
        if prompt.get("suggest"):
            return {"suggestions": []}
        # rolling memory digest: deterministic concat (bounded) so tests stay reproducible.
        if prompt.get("summarize"):
            prior = prompt.get("prior_memory") or ""
            lines = [l.get("content", "") for l in (prompt.get("new_lines") or [])]
            digest = (prior + " " + " ".join(lines)).strip()
            return {"memory": digest[-2000:]}

        # emergent location: deterministic stub description (real model writes the prose).
        if prompt.get("describe_place"):
            name = prompt.get("place_name", "")
            return {"detail": f"{name}——一处刚在故事里浮现出来的地方，轮廓在眼前渐渐清晰。"}

        # opening location for a map-less story: deterministic stub (real model derives it).
        if prompt.get("start_place"):
            return {"name": "此处", "detail": ""}

        # 🎲 risk judge: mock says "no dice needed" so tests stay deterministic.
        if prompt.get("risk_judge"):
            return {"risk": 100}

        # 到达旁白: mock returns nothing → runtime assembles its deterministic pan.
        if prompt.get("arrive"):
            return {}

        # 📱 incoming-message composer: mock defers to the deterministic fallback text.
        if prompt.get("compose_msg"):
            return {}

        # 📱 text-back: deterministic in-voice stub, no relationship movement.
        if prompt.get("phone_reply"):
            return {"msgs": ["嗯。"], "closeness": 0, "romance": 0}

        # parting cliffhanger (悬念离场): narration only, deterministic.
        if prompt.get("parting"):
            topics = prompt.get("topics") or []
            hint = f"关于「{topics[0]}」的话" if topics else "有句话"
            return {"beats": [{"type": "description", "speaker_name": None,
                               "text": f"（你起身离开。身后有人欲言又止——{hint}，似乎还没说完。）"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}

        # opening intro: narration only, deterministic.
        if prompt.get("intro"):
            pc = prompt.get("player_char")
            who = f"你是{pc.get('name','')}。" if pc else ("你是这场戏的旁观者。" if prompt.get("mode") == "god" else "")
            goal = prompt.get("goal") or ""
            text = f"{who}故事开始了。" + (f"目标：{goal}" if goal else "")
            return {"beats": [{"type": "description", "speaker_name": None, "text": text}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}

        # act transition: narration only, deterministic.
        if prompt.get("transition"):
            act = prompt.get("act") or {}
            goal = prompt.get("goal") or ""
            text = f"局面转入第{act.get('index','')}幕《{act.get('title','')}》。" + (f"目标：{goal}" if goal else "")
            return {"beats": [{"type": "description", "speaker_name": None, "text": text}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}

        # observe/examine (想): narration only, deterministic.
        if prompt.get("observe"):
            tgt = prompt.get("observe_target")
            if tgt:
                text = f"你打量着{tgt.get('name','那个人')}：{tgt.get('role') or ''}。此刻 TA 神色复杂，没有说话。"
            else:
                text = "你环顾四周，记下此刻的处境。"
            return {"beats": [{"type": "description", "speaker_name": None, "text": text}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}

        speaker = prompt.get("speaker_name") or "Narrator"
        ctx = prompt.get("context", {})
        new_reveal = ctx.get("new_reveal", [])
        reveal = ctx.get("reveal", [])
        hints = ctx.get("hint_topics", [])
        has_hidden = ctx.get("has_hidden", False)

        beats: list[dict[str, Any]] = []

        beats.append(
            {
                "type": "description",
                "speaker_name": None,
                "text": f"{speaker}缓缓转过头，看着你。",
            }
        )

        if new_reveal:
            # A secret cracked open THIS turn — voice only the new layer.
            body = " ".join(r["content"] for r in new_reveal)
            text = f"{speaker}沉默了一下，压低声音：“……有件事，你早晚得知道。”{body}"
            beats.append({"type": "dialogue", "speaker_name": speaker, "text": text})
        elif reveal:
            # Already-known ground; don't re-dump it.
            text = f"“这些……我刚才不都跟你说了么。”{speaker}的声音里有种说不清的疲惫。"
            beats.append({"type": "dialogue", "speaker_name": speaker, "text": text})
        elif hints:
            topic = hints[0]
            text = f"“你一直在往「{topic}」上绕……”{speaker}话到嘴边又咽了回去，没再说下去。"
            beats.append({"type": "dialogue", "speaker_name": speaker, "text": text})
        elif has_hidden:
            text = f"“这个……现在先别问。”{speaker}轻描淡写地把话岔开了。"
            beats.append({"type": "dialogue", "speaker_name": speaker, "text": text})
        else:
            text = f"“嗯。”{speaker}盯着你，“接着说。”"
            beats.append({"type": "dialogue", "speaker_name": speaker, "text": text})

        # Deterministic director fields (keep tests reproducible): steady warm-up,
        # never auto-advances the act (the affinity backstop handles progression),
        # never declares a death (authored conditions drive the mock's endings).
        return {"beats": beats, "affinity_delta": 3, "advance_act": False, "ending": None}
