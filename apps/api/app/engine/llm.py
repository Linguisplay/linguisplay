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
        }
        """
        ...


def get_llm() -> "LLM":
    """Pick the LLM backend from settings. Default 'mock' keeps tests deterministic."""
    from ..config import get_settings

    s = get_settings()
    if s.llm_provider == "qwen" and s.dashscope_api_key:
        from .qwen import QwenLLM

        return QwenLLM()
    return MockLLM()


class MockLLM:
    """Deterministic stand-in. Reflects gate decisions so behavior is observable."""

    def generate(self, prompt: dict[str, Any]) -> dict[str, Any]:
        # rolling memory digest: deterministic concat (bounded) so tests stay reproducible.
        if prompt.get("summarize"):
            prior = prompt.get("prior_memory") or ""
            lines = [l.get("content", "") for l in (prompt.get("new_lines") or [])]
            digest = (prior + " " + " ".join(lines)).strip()
            return {"memory": digest[-2000:]}

        # opening intro: narration only, deterministic.
        if prompt.get("intro"):
            pc = prompt.get("player_char")
            who = f"你是{pc.get('name','')}。" if pc else ("你是这场戏的旁观者。" if prompt.get("mode") == "god" else "")
            goal = prompt.get("goal") or ""
            text = f"{who}故事开始了。" + (f"目标：{goal}" if goal else "")
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
