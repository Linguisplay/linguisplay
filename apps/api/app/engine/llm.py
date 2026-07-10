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

        Backends MAY also provide plan_and_render(prompt) — a generator yielding
        ("token", str) while prose streams, then ("final", <generate()-shaped dict>).
        The runtime feature-detects it with hasattr; absence just means the old
        single-beat contract (docs/plan-render.md).
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

    def plan_and_render(self, prompt: dict[str, Any]):
        """Deterministic twin of the two-beat contract (docs/plan-render.md): same
        observable result as generate(), emitted through the plan/render seam so the
        v2 path is testable without a real model. Tokens carry {kind, text} — kind
        follows the beat type so the client-side bubble routing is exercised too."""
        out = self.generate(prompt)
        for b in out.get("beats", []):
            if b.get("text"):
                yield ("token", {"kind": ("speech" if b.get("type") == "dialogue"
                                          else "narration"), "text": b["text"]})
        yield ("final", out)

    def generate(self, prompt: dict[str, Any]) -> dict[str, Any]:
        # suggestions: mock returns none → runtime falls back to its deterministic template.
        if prompt.get("suggest"):
            return {"suggestions": []}
        # 🎀 galgame maker twins: deterministic parse + compile so build tests never call out
        if prompt.get("gal_parse"):
            return {"characters": [
                        {"name": "林晚", "looks": "短发少女，深色大衣", "personality": "冷静",
                         "weight": 5, "route": False},
                        {"name": "沈刻", "looks": "高瘦青年，金丝眼镜", "personality": "温和",
                         "weight": 4, "route": True}],
                    "scenes": [{"name": "天台", "visual": "夜里的天台，风很大"},
                               {"name": "教室", "visual": "放学后的空教室"}],
                    "protagonist": "林晚",
                    "chapters": [{"summary": "天台初遇。", "from": "林晚在天台"},
                                 {"summary": "教室对峙。", "from": "林晚在天台"}]}
        if prompt.get("gal_compile"):
            pro = prompt.get("protagonist_id") or "c1"
            other = next((c["id"] for c in (prompt.get("characters") or [])
                          if c["id"] != pro), pro)
            s1 = ((prompt.get("scenes") or [{}])[0]).get("id", "s1")
            # per-chapter distinct opening — the echo guard treats a re-told
            # opening as a failed compile, the twin must never trip it
            ch_i = (prompt.get("chapter") or {}).get("i") or 1
            openers = {1: "风从天台的边缘掀过来。",
                       2: "第二天放学，教室里只剩下你们两个。"}
            beats = [{"who": None, "text": openers.get(ch_i, f"新的一天从第{ch_i}声铃响开始。"),
                      "scene": s1, "bgm": "平静"},
                     {"who": other, "text": "「你来了。」", "expr": "喜", "scene": s1},
                     {"who": pro, "text": "「嗯。」", "scene": s1},
                     {"who": None, "text": "你在他身边站定。", "scene": s1},
                     {"who": other, "text": "「有件事想问你。」", "expr": "常态", "scene": s1},
                     {"who": None, "text": "夜色沉下来。", "scene": s1, "cg": True},
                     {"who": other, "text": "「明天，还会来吗？」", "expr": "哀", "scene": s1},
                     {"who": None, "text": "你没有回答。", "scene": s1}]
            # production contract shape: choices ride a separate top-level array
            # with an insertion anchor; the engine splices them into the stream
            choices = [{"after": 7, "options": [
                {"text": "「明天见。」", "fx": {other: 2},
                 "beats": [{"who": other, "text": "「一言为定。」", "expr": "喜", "scene": s1},
                           {"who": None, "text": "他笑了。", "scene": s1}]},
                {"text": "转身离开", "fx": {other: -1},
                 "beats": [{"who": None, "text": "你没有回头。", "scene": s1}]}]}]
            return {"beats": beats, "choices": choices,
                    "summary": "天台上的一问，没有答案。"}
        if prompt.get("gal_endings"):
            s1 = ((prompt.get("scenes") or [{}])[0]).get("id", "s1")
            t = (prompt.get("target") or {}).get("id") or ""
            def _nar(texts):
                return [{"who": None, "text": x, "scene": s1} for x in texts]
            return {"endings": [
                {"char": t, "title": "并肩", "beats": _nar(
                    ["风停了。", "他站在老地方。", "你走过去。",
                     "「我等你很久了。」", "你们并肩看向远处。", "天亮了。"])},
                {"char": "", "title": "独行", "beats": _nar(
                    ["天台空着。", "你独自站了一会儿。", "风很大。",
                     "你把外套裹紧。", "转身下楼。", "故事在这里停笔。"])}]}
        # rolling memory digest: deterministic concat (bounded) so tests stay reproducible.
        if prompt.get("summarize"):
            prior = prompt.get("prior_memory") or ""
            lines = [l.get("content", "") for l in (prompt.get("new_lines") or [])]
            digest = (prior + " " + " ".join(lines)).strip()
            return {"memory": digest[-2000:]}

        # 🔎 character scout: mock says the name fits, with stub whereabouts — the
        # minting twin's tests drive the interesting cases with their own LLMs.
        if prompt.get("scout_char"):
            return {"fits": True, "who": "打听来的人物", "where": "附近的去处", "persona": ""}

        # 🎯 数值账本 aux calls: deterministic mid-band stubs keep tests reproducible.
        if prompt.get("gen_attrs"):
            return {"attrs": {"力量": 5, "敏捷": 5, "体质": 5, "心思": 5, "气运": 5}}
        if prompt.get("rank_judge"):
            return {"rank_i": 0, "money": int(prompt.get("base_money") or 50),
                    "secret": "对某人的旧怨——当年的账还没算清"}
        if prompt.get("gen_market"):
            return {"items": [{"name": "热汤面", "price": 3, "detail": "一碗下肚，浑身是劲"},
                              {"name": "粗布斗篷", "price": 12, "detail": "挡风，也挡眼线"},
                              {"name": "止血散", "price": 25, "detail": "外伤敷上，好得快"}]}

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

        # 📮 letter composer: mock defers to the deterministic fallback letter.
        if prompt.get("compose_letter"):
            return {}

        # ✨ golden moment: mock never drops one — random rolls in tests stay beat-free
        # (a test that wants the drop supplies its own LLM + a pinned _rng).
        if prompt.get("golden_moment"):
            return {}

        # departing goodbye line: mock defers to the deterministic fallback.
        if prompt.get("farewell"):
            return {}

        # ✨ opening hook: mock defers to the deterministic withheld-crack narration.
        if prompt.get("opening_hook"):
            return {}

        # 🏖 sandbox opening cast: mock defers to the deterministic stranger.
        if prompt.get("sandbox_cast"):
            return {}

        # 🌊 world news: mock world stays quiet.
        if prompt.get("world_news"):
            return {}

        # 🌆 offscreen drama: mock stays quiet — no fabricated rumors in tests.
        if prompt.get("offscreen"):
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
