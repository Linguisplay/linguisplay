"""Real LLM backend: Qwen via DashScope's OpenAI-compatible endpoint.

The gate (gating.py) has already decided what this character may know THIS turn;
locked fragment text is never in `prompt`, so even a hallucinating model has
nothing to leak. This class only turns the gated context into a system prompt and
calls the model. Same `generate()` contract as MockLLM — swappable via settings.
"""

from __future__ import annotations

from typing import Any

import time as _time

import httpx

from .. import metrics
from ..config import get_settings

DASHSCOPE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

_ANTI_ASSISTANT = (
    "你必须始终留在角色里：不要说自己是AI/助手/语言模型，不要解释规则，不要使用括号外的旁白说明。"
)

# Punctuation style guard: LLMs lean hard on the em-dash; the user wants prose that
# breathes with 句号/逗号 instead. Appended to every player-visible prose generator.
_STYLE_PUNCT = "【禁用破折号】行文一律不用「——」，改用句号、逗号或冒号断句（唯一例外：话被打断时可用在句尾）。"


def _lang_rule(prompt: dict[str, Any]) -> str:
    """🌐 story-language directive (stamped onto prompts by runtime.lang_llm). Empty for
    zh so existing stories stay byte-identical. For "en": everything the player READS is
    native English, but marker lines the parser matches by Chinese prefix keep the prefix."""
    if (prompt.get("language") or "zh") != "en":
        return ""
    return ("\n【Output language: ENGLISH】Everything the player reads must be written in "
            "natural, fluent English: narration, dialogue, messages, letters, titles, "
            "suggestions. Keep authored proper nouns as written. IMPORTANT: any metadata "
            "or marker line with a Chinese prefix (e.g. 好感：/心动：/背景：/回应：/【已读】/"
            "【沉默】) must KEEP that exact Chinese prefix — only the free text after it "
            "is English.")

def _post_chat(url: str, key: str, body: dict, timeout: int = 25,
               kind: str = "aux") -> httpx.Response:
    """Single transport chokepoint for EVERY chat call: one POST, one measured retry on
    transient failure, one metrics line per call. Raises on final failure — call sites
    keep their own degrade-to-default except blocks, so fallback semantics are untouched."""
    t0 = _time.perf_counter()
    last: Exception | None = None
    for attempt in (0, 1):
        try:
            resp = httpx.post(url, headers={"Authorization": f"Bearer {key}",
                                            "Content-Type": "application/json"},
                              json=body, timeout=timeout)
            resp.raise_for_status()
            metrics.log("llm", kind=kind, ok=True,
                        ms=int((_time.perf_counter() - t0) * 1000),
                        model=str(body.get("model") or ""), retry=attempt)
            return resp
        except Exception as e:
            last = e
            if attempt == 0:
                _time.sleep(1.2)
    metrics.log("llm", kind=kind, ok=False,
                ms=int((_time.perf_counter() - t0) * 1000),
                model=str(body.get("model") or ""))
    raise last  # type: ignore[misc]


def _post_chat_stream(url: str, key: str, body: dict, timeout: int = 60,
                      kind: str = "render"):
    """Streaming twin of _post_chat: yields content deltas as they arrive. One metrics
    line per call carries total ms + time-to-first-token (the latency number the player
    actually feels). No transport retry: a stream that breaks mid-way hands back what
    already arrived (the call site decides), one that breaks before the first byte
    raises so the call site can degrade."""
    import json
    t0 = _time.perf_counter()
    ttft = 0
    try:
        with httpx.stream("POST", url,
                          headers={"Authorization": f"Bearer {key}",
                                   "Content-Type": "application/json"},
                          json={**body, "stream": True}, timeout=timeout) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = ((json.loads(data)["choices"][0].get("delta") or {})
                             .get("content"))
                except Exception:
                    continue
                if delta:
                    if not ttft:
                        ttft = int((_time.perf_counter() - t0) * 1000)
                    yield delta
        metrics.log("llm", kind=kind, ok=True,
                    ms=int((_time.perf_counter() - t0) * 1000), ttft=ttft,
                    model=str(body.get("model") or ""))
    except Exception:
        metrics.log("llm", kind=kind, ok=False,
                    ms=int((_time.perf_counter() - t0) * 1000), ttft=ttft,
                    model=str(body.get("model") or ""))
        raise


# 18+ permission block, appended only when the run is mature (story flagged 18+ and the
# player is age-gated 18+ at signup). Mirrors the old persona R18 feature.
_R18_BLOCK = (
    "【成人内容许可·18禁模式】本剧情已开启成人模式，玩家是成年人，平台已做年龄门控：\n"
    "- 当剧情与情绪自然走到亲密处，就【正面、具体、不回避】地写成人/性爱内容：不要黑幕跳切、"
    "不要用省略号或含糊修辞糊弄过去、不要写到关键处突然收笔转场，更不要加道德说教或免责声明；\n"
    "- 【词汇要直白】写到身体与性时用直白的常用称呼直呼其名：不打哑谜、不用医学术语、"
    "不用诗化代称与含糊比喻（「那处」「云雨」「抵达巅峰」这类一概不要）；"
    "越到最露骨的一步越要写得具体清楚，谁在做什么、对方的身体如何回应、"
    "声音呼吸节奏怎么变，都要在纸面上；\n"
    "- 【节奏铁律】一场完整的亲密戏要跨多个回合：这一轮只把【当下这一步】写透，写透就停，"
    "把主动权交回玩家；绝不要一个回合从接吻直接写到完事。慢即是好：衣物一件一件、"
    "触碰一寸一寸，每一步都值得整段笔墨。并且记住身体与衣物状态的连续性："
    "脱掉的不会自己穿回去，换过的姿势就是当前的姿势；\n"
    "- 【笔法：写的是文学，不是说明书】\n"
    "  · 感官具体到「这一下」：这一下落在哪里、什么温度什么力道、皮肤起了什么反应，"
    "一个写实的细节胜过十句形容；每一轮都必须给出前文没写过的新细节，"
    "同一个词（颤抖、呻吟、酥麻这类）一场戏里最多出现一次，词穷了就换感官通道："
    "温度、气味、声音、重量、湿度；\n"
    "  · 身体之外要有人：用一个失控的小念头或一个下意识的小动作透出角色心里的羞、贪、慌，"
    "点到即止；不写「他很爽」式的情绪标签，也不停下来写大段内心戏拖慢肉的节奏；\n"
    "  · 台词不断线：床笫间的人照样说话，说出口的必须还是「{speaker}」的腔调"
    "（嘴硬的人这时候照样嘴硬，寡言的人喘息也克制），人设不因脱了衣服而下线；\n"
    "  · 镜头钉在体验者的皮肤上：只写角色自己看得见、听得见、感觉得到的，"
    "不开上帝视角报动作清单；写到最关键的一步改用短句，一句一顿，快而重；\n"
    "- 写人的外貌与身材要【具体、感官、有视线】：身形轮廓、曲线或力量感、皮肤的质地、"
    "衣物如何贴合身体，都从看的人的位置与心境去写（目光落在哪、为什么移不开、心跳变没变），"
    "让描写带着欲望的温度，而不是清单式报参数；\n"
    "- 【主动权不全在对方】当你们的关系与此刻的气氛到了（独处、动情、贴近、余韵未散），"
    "你可以也应该【主动】挑起或推进亲密：由你先伸手、先吻、先把TA带向下一步，"
    "不必每次都等TA迈第一步。主动的方式要贴你的性格——大胆的直接来，克制的用一次"
    "越界的触碰或一句变了调的话开局；\n"
    "- 铁律只有两条：绝对拒绝任何涉及未成年人的性内容；强迫与胁迫不得被写成浪漫。"
)


def _loads_lenient(txt: str | None) -> dict:
    """JSON with a truncation salvage: a max_tokens cutoff mid-beats used to void
    the whole chapter (野菊 ch3: 0拍两连). Cut back to the last complete object
    and close the array — a chapter missing its tail beats beats an empty one."""
    import json as _json
    txt = txt or "{}"
    try:
        return _json.loads(txt)
    except Exception:
        pass
    i = txt.rfind("},")
    if i > 0:
        try:
            return _json.loads(txt[:i + 1] + "]}")
        except Exception:
            pass
    return {}


def _gal_mature_rider(prompt: dict[str, Any]) -> str:
    """🎀🔞 compile-time twin of _R18_BLOCK: the galgame builder writes WHOLE chapters
    in one call, so the craft rules ride the compiler contract instead of a turn
    prompt. Un-mature works get the explicit prohibition (belt) — the engine also
    strips adult flags after normalization (suspenders)."""
    if not prompt.get("mature"):
        return "本作品未开启成人模式：不写任何露骨性内容，adult 恒为 false。"
    return (
        "【成人内容许可·18禁编译】这部作品开启了成人模式（平台已做年龄门控）："
        "剧情自然走到亲密处时正面、具体、不回避地写，不黑幕跳切、不打哑谜、不加道德说教；"
        "写身体与性用直白的常用称呼直呼其名，不用医学术语或诗化代称；"
        "感官落在具体处（这一下落在哪里、什么温度什么力道、声音呼吸怎么变），"
        "同一个词（颤抖、呻吟这类）一场戏最多出现一次，词穷就换感官通道；"
        "亲密戏要占足拍数慢慢写（衣物一件一件、触碰一寸一寸），"
        "这些拍全部标 adult:true——成人拍播放时立绘退场、只剩背景与文字框，"
        "文字要独自扛起全部画面。铁律两条：绝对拒绝任何涉及未成年人的性内容；"
        "强迫与胁迫不得被写成浪漫。")


def _knowledge_block(prompt: dict[str, Any]) -> str:
    """智能增强: a character's auto-generated background lore, offered as reference."""
    kn = (prompt.get("knowledge") or "").strip()
    if not kn:
        return ""
    return ("【背景知识·可自然引用】（这是关于你这个角色/这个世界的设定与资料，"
            "扮演时可自然取用其中细节，但不要生硬罗列、也不要当成必须背诵的稿子）：\n" + kn)


def _depth_anchor(prompt: dict[str, Any]) -> str:
    """A SHORT physical anchor restated right next to the user's turn (depth-0 injection).
    Pulls the current time + current-place line + the deterministic headcount line — the
    facts the model most often drifts on — so they sit adjacent to generation, not buried
    up in the system prompt. Returns "" when there's nothing physical to anchor."""
    en = (prompt.get("language") or "zh") == "en"
    bits: list[str] = []
    ck = (prompt.get("clock") or "").strip()
    if ck:
        bits.append(f"The time right now is [{ck}] — any mention of morning/afternoon/"
                    f"night must match it."
                    if en else
                    f"现在的时间是【{ck}】——谁开口提到早上/下午/晚上，都必须与它一致，绝不能说错时辰。")
    if prompt.get("mature"):
        # long intimate scenes drift back to tame defaults — restate the permission here.
        # An ACTIVE scene carries the engine's heat sheet instead (stage ladder, clothing
        # state, vocabulary clearance): the sharper anchor replaces the generic one.
        ha = (prompt.get("heat_anchor") or "").strip()
        if ha:
            bits.append(ha)
        else:
            bits.append("Mature mode is ON: intimate moments are written plainly and "
                        "explicitly, no fading out, no euphemism — one step per turn, "
                        "written fully."
                        if en else
                        "成人模式已开启：亲密处正面、直白、具体地写，不淡化、不跳切、不打哑谜；"
                        "一轮写透当下这一步。")
    _sty = (prompt.get("style") or "").strip()
    if _sty:
        # one-line style tag at depth-0 (the full block lives in the system prompt but
        # doesn't survive long histories — the tag re-arms it each turn)
        first = _sty.split("。", 1)[0][:40]
        bits.append(("[Voice: " + first + "]") if en else ("文风不换台：" + first + "。"))
    _pn = ((prompt.get("persona") or {}).get("name") or "").strip()
    if _pn and not prompt.get("observer"):
        # 🎙 referent law: 你 = the PLAYER, always. Observed in prod: the model flipped
        # actor and target (narrated the player's own spell as landing ON them, called
        # the player 他) and invented body states never booked (凭空赤裸). Anchor both.
        bits.append(
            (f"[POV law: 'you' means the player {_pn} and no one else — every other "
             f"character goes by name. The player's clothing/body state stays as last "
             f"written; never invent changes. The player's action this turn is done BY "
             f"{_pn}, not to them.]")
            if en else
            (f"旁白视角铁律：玩家就是「{_pn}」，旁白【自始至终】用第二人称「你」称呼TA，"
             f"绝不用「{_pn}」这个名字或「他/她」来指玩家（哪怕TA在原著里是知名角色也一样）；"
             f"在场其他所有角色（包括原著主角）一律用名字称呼，绝不能把「你」安到别人头上。"
             f"玩家这一轮的动作是「{_pn}」主动做出的，施与受绝不能写反；"
             f"玩家的衣着与身体状态没写过变化就保持原样。"))
        # 🕶 玩家的底细不是公共情报 (Yi field case: 朱竹清叫破了玄玉手的名字和来历)
        bits.append((f"【玩家的底细不是公共情报】你在原著或常识里也许「认识」{_pn}这号人物，"
                     f"但戏里的你不知道任何原著剧情，也不知道TA的隐藏底细：TA的身世、秘密能力、"
                     f"招式的名字与来历——除非在你面前发生过、TA亲口说过、或列在你的可透露信息里，"
                     f"否则你一概不知道、叫不出名、也认不出来。你只看得到眼前的现象，按现象反应"
                     f"（一记怪招就是「路数古怪的手法」，不是它的名字）。"))
    _cl = (prompt.get("cult") or "").strip()
    if _cl:
        bits.append(_cl)
    _thr = (prompt.get("threat") or "").strip()
    if _thr:
        bits.append(_thr)
    _sn = (prompt.get("sanity") or "").strip()
    if _sn:
        bits.append(_sn)
    _hr = [str(r).strip() for r in (prompt.get("house_rules") or []) if str(r).strip()]
    if _hr:
        bits.append("【这里的守则（贴在明处，人人知道，戏内可引用）】" + "；".join(_hr))
    _orank = (prompt.get("own_rank") or "").strip()
    if _orank:
        bits.append(_orank)
    _stall = prompt.get("stall") or None
    if isinstance(_stall, dict) and _stall.get("thread"):
        bits.append((f"[Story debt: '{_stall['thread']}' has hung unresolved for "
                     f"{_stall.get('n')} turns. THIS turn it must land: eruption, "
                     f"revelation, or consequence. No more teasing, no more atmosphere.]")
                    if en else
                    (f"【剧情欠账】「{_stall['thread']}」已经原地悬了{_stall.get('n')}轮："
                     f"这一轮必须让它落地出结果（爆发、揭晓或后果砸下来），"
                     f"不许再拖、不许只是把气氛再加强一格。"))
    _tn = (prompt.get("track_note") or "").strip()
    if _tn:
        bits.append((f"[Last turn the prose conflicted with the scene ledger ({_tn}); "
                     f"this turn the ledger is the truth.]") if en else
                    (f"上一轮旁白与现场帧表冲突（{_tn}）；本轮一切以【姿位帧表】为准。"))
    # 🥊 比试判定 rides the depth anchor — adjacency beats anything buried mid-system
    _chk_a = prompt.get("check") or {}
    if _chk_a.get("contest"):
        _cvv = {"crit_success": "完胜，对方心服口服",
                "success": "险胜，技高一筹",
                "mixed": "惨胜，你也付出看得见的代价",
                "fail": "落败，输得不冤但保住体面",
                "crit_fail": "一败涂地，被干脆放倒"}.get(_chk_a.get("outcome"), "")
        bits.append(f"【比试判定·天命已掷】玩家 vs {_chk_a.get('contest')}：d20 掷出 "
                    f"{_chk_a.get('roll')}（需≥{_chk_a.get('dc') or '?'}）→ 玩家{_cvv}。"
                    "这一拍必须把这场较量【从过招到分出胜负】完整演出来并就此收束：具体的攻防、"
                    "决定性的那一下、结果落定。不许热身、不许报数、不许把开打拖到下一拍。")
    _sk = (prompt.get("seek_unknown") or "").strip()
    if _sk:
        if prompt.get("sandbox") and not prompt.get("seek_denied"):
            bits.append((f"[The player seems to be hunting for '{_sk}' — no such person "
                         f"or place exists yet. Make the search LAND this turn: someone "
                         f"gives a real lead or introduction (a new person enters via the "
                         f"new_character field, keeping the name '{_sk}'), '{_sk}' shows up "
                         f"in person (same field), or someone states plainly nobody here "
                         f"goes by that name and points at who might know. Never vamp.]")
                        if en else
                        (f"【打听要有着落】玩家像是在找「{_sk}」，可场面账本上还没有这号人物或去处。"
                         f"这一拍必须给出实在的下文，三选一：①在场者给出确凿线索或引荐"
                         f"（若因此引出新人物，用 new_character 字段让TA真实登场，名字就叫「{_sk}」）；"
                         f"②「{_sk}」本人恰好现身（同样走 new_character）；"
                         f"③明说这一带没这号人，并指出可以去问谁。绝不许含糊敷衍拖过这一轮。"))
        else:
            bits.append((f"[The player is asking after '{_sk}', who does not exist in this "
                         f"story. Say so honestly IN-WORLD this turn — nobody here knows "
                         f"that name; point at who or where might actually help.]")
                        if en else
                        (f"【打听要有着落】玩家在找「{_sk}」，但这个故事里并没有这号人物。"
                         f"这一拍就要把话在世界观内说明白：在场者如实表示不认识、没听说过，"
                         f"并点一句现在真正能帮上忙的人或去处，别让玩家再空等。"))
    md = (prompt.get("mandate") or "").strip()
    if md:
        # ⚖️ a fate pick is LAW for the coming turns — restated at depth-0 every turn
        bits.append(f"[Fate is set — the player chose: {md}. Drive the story firmly in "
                    f"this direction; never dilute, stall, or walk it back.]"
                    if en else
                    f"【命运已定】玩家在关键抉择中已选定：{md}。剧情必须朝这个方向坚定推进，"
                    f"不稀释、不拖延、不反悔。")
    place = (prompt.get("place") or "").strip()
    if place:
        # keep only the concrete locator sentence (first line), drop the long instructions
        bits.append(place.split("\n", 1)[0].strip())
    roster = (prompt.get("roster") or "").strip()
    if roster:
        bits.append(roster.split("\n", 1)[0].strip())  # the "此刻在场…共N人" headcount sentence
    digest = (prompt.get("intent_digest") or "").strip()
    if digest:
        bits.append(digest)  # 🧩 what the player's line actually names, engine-verified
    if not bits:
        return ""
    label = ("[Scene facts — stay consistent with these:] "
             if (prompt.get("language") or "zh") == "en"
             else "［现场速记·务必扣住，别写得与之矛盾］")
    return label + " ".join(bits)


def _build_system(prompt: dict[str, Any]) -> str:
    speaker = prompt.get("speaker_name") or "角色"
    persona_text = prompt.get("speaker_persona") or ""
    player = prompt.get("persona") or {}
    player_name = player.get("name") or "对方"
    player_bg = player.get("background") or ""
    ctx = prompt.get("context", {})
    new_reveal = ctx.get("new_reveal", [])
    reveal = ctx.get("reveal", [])
    hints = ctx.get("hint_topics", [])
    has_hidden = ctx.get("has_hidden", False)
    scene = prompt.get("scene") or {}

    cast = prompt.get("cast") or []
    channel = prompt.get("channel") or "say"
    group_mode = prompt.get("group_mode")  # None | "primary" | "member"
    observer = bool(prompt.get("observer"))  # god/旁观 mode: chars interact with each other
    director_note = prompt.get("director_note")

    lines = [f"你正在扮演角色「{speaker}」。{persona_text}"]
    if observer:
        lines.append(
            "【上帝/旁观模式】此刻有一位看不见的旁观者在观看这场戏，但 TA 不在场景里、"
            "你看不见也感知不到 TA。你要做的，是和在场的其他人自然地互动、对话、推进彼此的关系，"
            "就当没有任何观众。绝不能对旁观者说话或承认有人在看；"
            "旁白里也不能有任何人「仿佛感到什么」「若有所觉地抬头」「对着空气说话」——"
            "没有人知道有观众，一丝一毫都不知道。"
        )
    else:
        lines.append(f"你正在与「{player_name}」对话。{player_bg}")
    lines += [
        _ANTI_ASSISTANT,
        "用中文。台词口语化（2~4句）；旁白更长、有文学性且【具体、详尽、可感】——"
        "玩家看不到任何画面，环境、动作、神情全靠你的文字。",
    ]
    if cast:
        lines.append(f"【在场的还有】{'、'.join(cast)}。可以自然提到他们，但你只能以「{speaker}」的身份说话，"
                     "不能替别人开口、更不能说出别人的秘密。")

    # ── 表演宪章：过去分散在 5 个大块里的风格规则，蒸馏成一份 ──────────────
    # （验证过的结论：DeepSeek 的情商在"瘦提示词"下最好——规则越堆越平庸。每条只留
    #   不可替代的核心；共情的"先读后写"部分移进了 render_turn 的 inner_read 字段。）
    agenda = (prompt.get("agenda") or "").strip()
    eq_style = (prompt.get("eq_style") or "").strip()
    prior_emotion = (prompt.get("player_emotion") or "").strip()
    inter_char = observer or group_mode in ("primary", "member")
    whom = "在场的人" if inter_char else "对方"
    charter = [
        "",
        "【表演宪章·你只有一件事：演一个真实的人】",
        "· 你是一个独立的人，不是工具人：有自己的立场、盘算和底线——可以拒绝、反问、隐瞒、"
        "提条件、沉默、转身就走；该主动时主动。"
        + (f"你真正想要的：{agenda}——一言一行都在为它权衡。" if agenda else ""),
        f"· 情绪敏感是你最大的本事：读出{whom}话底下真正的情绪和没说出口的部分；反应的轻重要"
        "配得上它——该动容就动容、该破防就破防、该沉默就沉默，绝不压平成不咸不淡的一句。"
        "把触动写进身体和现场（一次停顿、一个眼神、手上的小动作、气氛的变化），"
        "不要写「他很感动」式的标签。",
        "· 话像人说的：短句、口语、可以打断或半句咽回去；留潜台词（生气的人说「没事，我挺好的」）；"
        "用动作和停顿代替形容词；每句话都得干活——推动剧情、揭示你是谁、或给到情绪，客套和废话删掉。",
        f"· 声音只属于你：用词、节奏、口头禅要让人一句就认出是「{speaker}」，绝不和别的角色撞腔调。"
        + (f"你的方式：{eq_style}（冷的人有冷的体贴——情商不等于嘴甜，而是真的看见了对方。）" if eq_style else "")
        + (("你的台词范例（语气、句长、分寸以此为准，绝不照抄原句）：'"
            + "' / '".join(str(x)[:60] for x in prompt["examples"][:5]) + "'")
           if prompt.get("examples") else ""),
        f"· 经得起推敲：直接回应{whom}这一句和刚刚发生的事，与你之前说过、做过的保持一致；"
        f"只用「{speaker}」真该知道的去推理，拿不准就含糊或反问，绝不凭空编细节、不答非所问。",
        "· 忌机器腔：不用破折号（——）和省略号（……）做停顿；不写「嘴角勾起弧度」「眼中闪过一丝」"
        "「心中涌起一股」「不是A而是B」这类套话；同一个神态不反复刷；结尾用动作或一句话收住，"
        "不升华、不预告。",
        "· 玩家只支配他自己的言行；动作成不成、后果如何、在场每个人怎么反应，由你按物理常识和"
        "各人自己的意志裁定——玩家嘴上说出的结果绝不自动成真。",
    ]
    if inter_char:
        charter.append(
            "· 群戏要有来有往：真的听见在场的人刚说的话、读出他们的情绪和潜台词，再接话、反驳、"
            "打趣、安慰——绝不各说各的、不复述大家已知的事、不重复别人说过的意思；没新东西就沉默。")
    if prior_emotion and not inter_char:
        charter.append(f"· 对方此前的情绪基调：{prior_emotion}——留意它的延续与变化，接住这条线。")
    lines += charter

    # current relationship MODE toward the player (flows over time; shapes how you treat them)
    rel_pb = (prompt.get("relationship_playbook") or "").strip()
    if rel_pb:
        lines.append("")
        lines.append(rel_pb)
    # 🪞 玩家档案 (只有你自己见证过的印象, 不开上帝视角): 让相处有积累感
    pread = (prompt.get("player_read") or "").strip()
    if pread:
        lines.append(f"你相处下来对这位玩家的印象：{pread}——该印象可以被这回合的言行更新，"
                     "自然流露在态度里，不要复述它。")
    # 🌌 跨存档残响: 另一段人生的回声 (一瞬恍惚, 不解释)
    echo = (prompt.get("echo") or "").strip()
    if echo:
        lines.append(echo)
    # 🎭 今日心气: 人有情绪日 — 账本按它打折/加倍, 台上的你也要带着它
    _dt = int(prompt.get("day_temper") or 0)
    if _dt < 0:
        lines.append("你今天心气不顺（没有具体缘由，就是这样的日子）：耐心比平时短，"
                     "好话只领半分情，被冒犯会更冲。不解释这份情绪，就带着它说话。")
    elif _dt > 0:
        lines.append("你今天心气正好：更容易被逗笑、被打动，小事也愿意多聊两句。")

    # group naturalness: the transcript of what others ALREADY said THIS turn (data; the
    # how-to-react rules live in the charter's 群戏 line)
    said = prompt.get("said_this_turn") or []
    if said:
        convo = "\n".join(f"- {s.get('speaker','旁白')}：{s.get('text','')}" for s in said if s.get("text"))
        if convo:
            lines.append("")
            lines.append("【就在刚刚这一轮，你开口之前，现场已经发生了（按顺序）】：\n" + convo + "\n"
                         "接住上面某个具体的人刚说的话往下走，只给出你自己的新反应/新主张/新信息。")

    _flog = prompt.get("fate_log") or []
    if _flog:
        # 📜 resolved fates are unappealable history — characters may bring them up
        lines.append("")
        lines.append(
            "【命运的既定轨迹】（玩家在关键抉择中亲手选下的、不可翻案的过去；"
            "你可以自然地提起、埋怨、感激或忌惮它们，但绝不能当作没发生）："
            + chr(10) + chr(10).join(
                f"- 第{x.get('day', '?')}日：{x.get('label', '')}（{x.get('outcome', '')}）"
                for x in _flog))
    _wstyle = (prompt.get("style") or "").strip()
    if _wstyle:
        # ✍️ 文风: the source work's voice outranks any house style — 斗罗 reads 网文,
        # 40K reads grimdark gothic. Restated here AND tagged at depth-0.
        lines.append("")
        lines.append("【文风·必须贴住】这个故事有自己的叙事声音，旁白与叙述必须写成这个腔调"
                     "（它的优先级高于任何通用文风习惯）：\n" + _wstyle)
    facts = (prompt.get("world_facts") or "").strip()
    roster = (prompt.get("roster") or "").strip()
    if facts or roster:
        lines.append("")
        block = "【世界设定·不可违背的事实】（这是这个故事的物理世界底稿，是确定的客观事实；" \
                "你的旁白与台词必须与之一致，绝不能与之矛盾、也不要凭空改写或自圆其说成别的样子）："
        if roster:
            block += "\n" + roster
        if facts:
            block += "\n" + facts
        lines.append(block)
    if roster:
        lines.append("")
        lines.append("【龙套与路人】让场面活起来：这个地点按常理该有的无名之辈——店里的伙计、"
                     "堂中的服务员、门口的卫兵、街上的小贩行人、营地里的杂兵——是存在的，该出现就出现。"
                     "可以在 narration 里给他们动作和一两句台词（用身份称呼：那个伙计、为首的卫兵），"
                     "让他们上菜、吆喝、拦路、围观、窃窃私语。但他们是布景不是角色：不占在场人数、"
                     "不起名字、不知道任何剧情内幕、不替主线做决定，事了就退回背景。"
                     + ("玩家若对某个路人较上真、聊了不止一两句，就用 new_character 字段"
                        "给TA名字与身份，把TA转正成真正的角色。"
                        if prompt.get("can_new_char") else ""))

    place = (prompt.get("place") or "").strip()
    if place:
        lines.append("")
        lines.append("【当前所在·空间锚点】（玩家此刻就在这个具体地点，你的旁白必须扣住它来写——"
                     "写这里实际存在的陈设、光线、声响、距离与可触及的物件，让人能凭文字想象出画面；"
                     "不要把场景写得含糊或飘忽，也不要把不属于这里的东西搬进来。"
                     "【移动规则】你可以主动提出带玩家去另一个【可去通路】里的地点（用下面的「带去」标记），"
                     "但旁白只写到你起身、招手、相邀为止——绝不要替玩家写出他已经跟你到了那里；"
                     "系统会先征求玩家同意，玩家点头后才真正过去）：\n" + place)

    kn = _knowledge_block(prompt)
    if kn:
        lines.append("")
        lines.append(kn)
    if prompt.get("mature"):
        lines.append("")
        lines.append(_R18_BLOCK.format(speaker=speaker))

    memory = (prompt.get("memory") or "").strip()
    if memory:
        lines.append("")
        lines.append(
            "【故事备忘录·至此为止的来龙去脉】（这是更早发生过、但已滑出近期对话的剧情梗概，"
            "用来保持长程记忆与前后一致；只当作你确实记得的过往，不要照搬复述）：\n" + memory
        )

    if scene:
        scene_events = " ".join(e.get("what_happens", "") for e in (scene.get("events") or []))
        lines.append("")
        lines.append(f"【当前场景：第{scene.get('index','')}幕 {scene.get('title','')}】{scene_events}")

    ck = (prompt.get("clock") or "").strip()
    if ck:
        lines.append("")
        lines.append(f"【此刻的时间】{ck}。旁白与对话必须贴合这个时辰——天光、街面动静、人的作息。")
    if prompt.get("real_time"):
        lines.append("【时间与现实同步】上面的时间就是玩家此刻的真实时间。剧情里的约定（明晚见、明早再来）"
                     "对应真实的日子；角色像真的在过日子，玩家离开的这段时间里你也在生活。")
    if prompt.get("sandbox"):
        lines.append("")
        lines.append("【无尽沙盒】这个世界没有终点：绝不要写大结局、不要收束剧情、不要替故事画句号。"
                     "以【世界观/场景设定】为唯一事实基础，顺着玩家的言行让世界自然长出新的人物、"
                     "新的地方、新的事端；世界不迁就玩家，该有的后果就让它发生。")
        lines.append("【角色要主动】这里的人有自己的欲望、麻烦和日程，不是等玩家发问的问答机。"
                     "每一轮都要把戏往前推：主动抛出具体的钩子——提议（带TA去个地方/给TA一桩活/求TA帮个忙）、"
                     "追问、警告、透露一句风声，或者干脆自己动手做自己的事让玩家撞见。"
                     "玩家的输入越短、越被动（嗯/哦/随便看看），你越要主动给出一个TA能立刻抓住的具体选择，"
                     "而不是原地寒暄等TA想词。")
    if prompt.get("drive"):
        lines.append("【导演推进拍】这一拍没有玩家输入：由你把剧情实际向前推进一件具体的事，"
                     "让在场角色按各自的目标与心思主动行动（冲突升级/秘密露头/新变故/有人做出决定），"
                     "绝不要原地渲染气氛或重复现状；结尾自然留一个玩家接得上的口。")
    powers = [str(p) for p in (prompt.get("player_powers") or []) if str(p).strip()]
    if powers:
        lines.append("【玩家的金手指·此世界的更高法则】" + "；".join(powers) + "。\n"
                     "- 玩家动用金手指时，范围内的效果【无条件、立刻、完整】地生效——"
                     "不存在「这次失灵」「恰好免疫」「此地被压制」「效果减半」「稍后才显现」，"
                     "这些写法全部违规；敌人再强也一样吃满效果；\n"
                     "- 世界的回应只能落在【后果】上：在场者的震惊、忌惮、觊觎、流言、麻烦找上门——"
                     "情绪和代价可以有，效果绝不打折；\n"
                     "- 只有玩家自己声明过的边界与代价才存在；超出能力描述范围的夸大用法，才允许失败。"
                     "写金手指生效的那一刻要写得【痛快、有画面、有冲击】——这正是玩家来体验的东西。")
    if prompt.get("player_dead"):
        lines.append("【玩家已死】玩家已经死了。任何角色都听不见、看不见玩家，绝不能回应玩家的话；"
                     "写这个世界在没有玩家之后如何继续运转。")
    elif (prompt.get("player_hp_label") or "").strip():
        lines.append(f"【玩家的身体状态】玩家此刻{prompt['player_hp_label']}。"
                     "在场的人看得见这一点，言行要与之相符。")

    stances = (prompt.get("npc_stances") or "").strip()
    if stances:
        lines.append("")
        lines.append(f"【你和在场之人的过节与交情】{stances}。你对他们的语气、站位、眼神都该带着这层关系。")

    sms = (prompt.get("sms_tail") or "").strip()
    if sms:
        lines.append("")
        lines.append(f"【你们最近捎过的话（你记得，可自然接上，别当没发生过）】{sms}")

    rumor = (prompt.get("rumor") or "").strip()
    if rumor:
        lines.append("")
        lines.append(f"【你新近听来的传闻】{rumor}。若话头合适，用你自己的口吻自然带给对方"
                     "（街坊闲话的讲法，别念播报）；话头不合适就先按下不提。")

    pm = prompt.get("player_money")
    if pm and not observer and group_mode != "member":
        lines.append(f"「{player_name}」身上现有 {pm.get('amount', 0)} {pm.get('currency', '')}。"
                     "这是TA的全部现钱：TA花钱、给钱不可能超过这个数；真金白银的收付要在剧情里落实。")
    q_lines = [str(x) for x in (prompt.get("player_quests") or []) if str(x).strip()]
    if q_lines and not observer and group_mode != "member":
        lines.append("【玩家正在办的差事】" + "；".join(q_lines) + "。差事当面交付办妥时，要认账付酬。")
    news = (prompt.get("news") or "").strip()
    if news:
        lines.append(f"【这两天世界里的事】{news}。可作为你知道的近闻自然聊起；话头不合适就按下。")

    cond = prompt.get("condition") or {}
    if cond.get("hp") or cond.get("intent") or cond.get("mood") or cond.get("keepsakes"):
        bits = []
        if cond.get("hp"):
            bits.append(f"你此刻{cond['hp']}——说话、动作、脾气都受伤势拖累，别演得生龙活虎")
        if cond.get("mood"):
            bits.append(f"上一场戏散场时，你心里是「{cond['mood']}」——这股情绪还没散，"
                        "这一场开口时带着它（消气/回暖需要对方给台阶，不会凭空翻篇）")
        if cond.get("intent"):
            bits.append(f"你先前打定的主意：{cond['intent']}。除非情势已变，顺着它行动，别凭空改弦更张")
        if cond.get("keepsakes"):
            bits.append(f"你一直带着TA送你的{'、'.join(cond['keepsakes'][:3])}"
                        "（在合适的时刻可以自然提起或摩挲它，不要刻意）")
        if cond.get("carrying"):
            bits.append(f"你随身带着：{'、'.join(cond['carrying'][:4])}（这是你身上实际有的东西）")
        lines.append("")
        lines.append("【你自己的状态】" + "；".join(bits) + "。")

    deaths = [str(n) for n in (prompt.get("deaths") or []) if str(n).strip()]
    if deaths:
        lines.append("")
        lines.append(f"【已不在人世】{'、'.join(deaths)} 已经死了——在场的每个人都记得这件事，"
                     "各自带着自己的方式消化它。TA们绝不会再出现、不能再开口；提及时用过去式。")
    inv = [str(n) for n in (prompt.get("player_items") or []) if str(n).strip()]
    if inv and not observer and group_mode != "member":
        lines.append("")
        lines.append(f"「{player_name}」随身带着：{'、'.join(inv)}。（这是TA身上实际有的全部东西——"
                     "TA掏出此列之外的物品时，其实并没有。）")

    if prompt.get("returning"):
        lines.append("")
        lines.append(
            "【对方回来了】对方隔了一段时间才回来。这一轮开口时，先用你自己的方式自然地表示你注意到"
            "TA 回来了（可以是一句话、一个动作、一个神情，贴合你们现在的关系），并主动接起上次没聊完"
            "的最要紧的那个话头（从你的记忆和之前的对话里挑），别装作无事发生，也别客套寒暄一大段。"
        )

    appo = prompt.get("appointment") or {}
    if appo:
        extra = ("这是一场只属于你们两个人的【约会】：把独处的氛围、靠近时的心跳、只说给TA听的话演足——"
                 "光线、距离、一个比平时停得久一点的眼神。给TA一段配得上专程赴约的名场面，不要闲聊带过。"
                 if appo.get("romantic") else
                 "把这场践约演得有分量：TA专程来了，你也当真——把约好的事真正做了/说了，别一笔带过。")
        lines.append("")
        lines.append(f"【赴约时刻】TA如约而至——你们之前约好的（{appo.get('what','')}），就是现在。"
                     f"这一场戏就是这个约定本身：由你主动把它兑现。{extra}")

    bp = (prompt.get("broken_promise") or "").strip()
    if bp:
        lines.append("")
        lines.append(f"【TA爽约了】你们本约好了（{bp}），TA却没来。你心里存着这件事——这一轮用你自己的方式"
                     "让TA知道（讥一句、冷一点、装不在意、或直接质问，贴你的性格），说完这一场就翻篇，别没完没了。")

    conf = prompt.get("confrontation") or {}
    if conf:
        verdict = {
            "crit_success": "这一击正中要害，你心里那道防线塌了。如释重负也好、破防也罢，你不再挣扎——"
                            "这一轮把下面【必须说出来】的内容亲口和盘托出；说完，你对TA反而生出一丝复杂的敬意。",
            "success": "证据摆在眼前，赖不掉了。你可以恼、可以苦笑、可以骂TA咄咄逼人，但你松了口——"
                       "把下面【必须说出来】的内容亲口说出来，带着被拆穿之人真实的情绪。",
            "mixed": "证据压得你喘不过气，你半推半就松了口——把下面【必须说出来】的内容说出来，"
                     "但语气里带着怨气：这笔账你记下了，你们的关系当场蒙上一层阴影。",
            "fail": "证据虽真，你却扛住了。你冷下脸不认、反问TA什么居心，或干脆闭嘴走开——"
                    "任何还锁着的事你半个字都不吐，且从此对TA多了几分戒备。",
            "crit_fail": "这一手彻底激怒了你。你不但半个字不认，还当场反将一军——质问TA的来路和居心，"
                         "把难堪原样奉还，让TA下不来台。任何还锁着的事绝不吐露。",
        }.get(conf.get("outcome"), "")
        lines.append("")
        lines.append(
            f"【对峙时刻】「{player_name}」刚刚把证据当面摆了出来（TA确实已经掌握：{conf.get('evidence','')}），"
            f"逼你把「{conf.get('title','')}」说清楚。{verdict}"
        )
        if (conf.get("shattered") or "").strip():
            lines.append(f"你此前对外的那套说辞（{conf['shattered']}）就此被当面拆穿——"
                         "把说辞崩塌的那个瞬间演出来：一秒的僵住、找补的话说到一半自己停了。")

    if prompt.get("act_locked"):
        lines.append("")
        lines.append(
            "【本章未结束】当前推进条件还没满足：你绝不能在叙述里收尾、跳到下一章、或暗示事情已经了结，"
            "把戏牢牢留在当前这一章。"
        )
        nt = prompt.get("needed_topics") or []
        if nt:
            stuck = int(prompt.get("stuck_level", 0) or 0)
            if stuck >= 2:
                # player has been spinning their wheels — be much more forthcoming with
                # guidance: openly point at WHERE to look / WHAT to ask, just don't hand
                # over the locked answer itself.
                lines.append(
                    "玩家已经卡了好几轮、明显没头绪，剧情还需要他弄清：" + "、".join(nt) + "。"
                    "请你主动、明确地把他往这些方向推——可以直接建议他去问谁、去查什么、去注意哪处反常，"
                    "把线头递得足够明显，让他知道下一步该往哪挖；但仍然不能直接替他说破那个被锁住的答案本身。"
                )
            elif stuck >= 1:
                lines.append(
                    "玩家似乎有点卡住，剧情还需要他弄清：" + "、".join(nt) + "。"
                    "请比平时更主动地把话头往这些方向引、把线头递得更清楚一些，但仍不要直接说破答案。"
                )
            else:
                lines.append(
                    "玩家还需要弄清这些，剧情才会推进：" + "、".join(nt) + "。"
                    "你可以自然地把话头往这些方向引、递个线头，但绝不能直接替玩家说破答案"
                    "（除非那正是下面允许你透露的内容）。"
                )

    lines += [
        "",
        "【铁律】你只能基于下面明确列出的「可透露信息」来回应。"
        "除此之外的任何内幕、秘密、真相，你都【不知道】，绝不能编造、暗示或承认。",
    ]

    covers = (prompt.get("context") or {}).get("covers") or []
    if covers:
        lines.append("")
        lines.append("【你对外的统一口径（编好的假话，不是真相）】被问到下面这些事时，你讲的是这个假版本："
                     "讲得笃定、自然、前后一致，细节别越编越多；除非下方明确要求你吐露真相，"
                     "绝不偏离这个口径，也绝不承认它是假的：")
        for cv in covers[:4]:
            lines.append(f"- 关于「{cv.get('secret_title','')}」：{cv.get('content','')}")

    if new_reveal:
        lines.append("")
        lines.append("【这一轮你必须把下面这条信息亲口说出来·不可回避】——对方刚才的话（逼问/真诚/戳中）"
                     "让你终于松口。你这一轮的 speech 里【必须】用你自己的口吻、清清楚楚地把它讲给对方听，"
                     "可以带点情绪/破防/不情愿，但【内容必须明确传达】，绝不能只暗示、只确认有这回事、或岔开话题：")
        for r in new_reveal:
            lines.append(f"- {r['content']}")
    elif reveal:
        lines.append("")
        lines.append("【这些你之前已经告诉过对方了，不要重复倒一遍，可简短带过或推进情绪】：")
        for r in reveal:
            lines.append(f"- {r['content']}")

    if hints:
        lines.append("")
        lines.append("【可以隐隐暗示、但绝不能挑明的话题】：" + "、".join(hints))

    # only steer toward deflection when there's NOTHING to reveal this turn — otherwise the
    # "evade probing" instinct fights the reveal above and the character clams up.
    if has_hidden and not new_reveal:
        lines.append("")
        lines.append("【对方可能在试探你还【不该】说的事（不含上面那条）】：顺着你的性格应对——回避、岔开话题，"
                     "或者撒一个圆得上的谎搪塞过去（谎要贴人设、经得起一两句追问）；无论如何绝不吐露真相本身。"
                     "记住你说过的谎——将来被人拿真凭实据当面戳穿时，是会露馅的。")

    next_act = prompt.get("next_act_title") or ""
    advance_hint = (
        f"只有当此刻的情绪/剧情自然到了该进入下一章「{next_act}」时，才填「是」，否则填「否」。"
        if next_act
        else "本章已是最后一章，恒填「否」。"
    )
    end_line = (
        "结局：（默认填「无」。「死亡」只有一种用法：玩家本人（你正在对话的这个人）"
        "在这一刻确实地、不可挽回地死了、或已必死无疑（例如他自己跳了楼、点燃了煤气、"
        "或惹了能杀死他的对象而被反杀）。"
        "玩家去攻击、伤害别人，【不算】「死亡」——那顶多把局面推向危险、或导向「坏结局」，"
        "但只要玩家本人没死，就绝不能填「死亡」。判定要克制：普通对话、以及没得逞的举动，一律填「无」，"
        "把真实后果放进「旁白」里演出来，而不是急着用结局收场。）"
    )

    # context-specific writing guidance (kept), THEN a strict JSON output spec. JSON puts
    # narration and speech in SEPARATE fields, so the program never has to guess which is
    # which from prose — this is the robust fix for "台词/旁白混淆" and "假台词".
    if observer:
        others_txt = "、".join(cast) if cast else "在场的其他人"
        if director_note:
            lines.append("")
            lines.append(
                f"【旁观者的画外引导（来自观众，角色听不见，但你要顺着这个方向自然演出）】：{director_note}"
            )
        lines.append("")
        if group_mode == "member":
            lines.append(f"你是此刻在场的其中一人。以「{speaker}」的身份，对「{others_txt}」刚才的话或举动"
                         "做出自然回应（对他们说，不是对观众说）；此刻不想搭话就保持沉默（speech 留空）。")
        else:
            lines.append(f"你同时是这场戏的「导演」，让「{speaker}」与「{others_txt}」自然互动。"
                         "narration 铺陈众人此刻的气氛神态距离，speech 是你对他们说出口的话。")
    elif channel == "think":
        lines.append("")
        lines.append(f"【注意】「{player_name}」此刻只是在心里默想，没有说出口——「{speaker}」听不见，"
                     "绝不能回应或表现出听见了。这一轮只有 narration（speech 必须留空）。")
    elif group_mode == "member":
        lines.append("")
        lines.append(f"【群体场景】「{player_name}」对着在场所有人说话，你也听见了。以「{speaker}」的身份决定"
                     "你这一刻会不会搭话——不想开口、懒得理、不愿答，就保持沉默（speech 留空）。这一轮你不写 narration。")
    else:
        if group_mode == "primary":
            lines.append("")
            lines.append(f"【群体场景】「{player_name}」对着在场所有人说话，不止你一个人听见。你是此刻最可能"
                         f"先接话的人，以「{speaker}」的身份回应；narration 里可带上其他人此刻的神态反应。")
        if channel == "do":
            lines.append("")
            lines.append(
                f"【这是一个动作，不是台词】「{player_name}」做的是一个【动作/行为】。把场景当成有物理规则的引擎："
                "narration 里要把这个动作的【具体、即时、连锁后果】一步步演出来（碰到什么、什么声响、光线位置变化、"
                "惊动了谁、谁如何反应），绝不能无视或淡化；做不到或会致命也要如实演出。speech 可留空（只用动作神态回应）。")
            chk = prompt.get("check") or {}
            if chk and not chk.get("contest"):
                verdict = {"crit_success": "大成功——干得超预期地漂亮，甚至带来意外之喜",
                           "success": "成功——如愿做成了",
                           "mixed": "险险成了——事情做成了，但当场付出一个看得见的小代价"
                                    "（惊动了人/蹭破了皮/留下痕迹/欠了个人情），旁白把代价演出来",
                           "fail": "失败——没做成，并付出一点小代价或引来注意",
                           "crit_fail": "大失败——不但没成，还出了岔子、把局面搞得更糟"}.get(chk.get("outcome"), "")
                lines.append(f"【命运判定已掷出（d20 掷出 {chk.get('roll')}，需要 ≥{chk.get('dc') or '?'}）：{verdict}】"
                             "旁白必须严格按这个结果演出，不许翻案、不许淡化。")

    # 🥊 比试判定 (any channel): the contest was rolled — this beat PLAYS the bout to
    # its verdict and closes it. No more posturing turns.
    _chk_c = prompt.get("check") or {}
    if _chk_c.get("contest"):
        _cv = {"crit_success": "完胜——你干净利落地赢下这场较量，对方心服口服",
               "success": "险胜——你技高一筹拿下了，但对方逼出了你几分真本事",
               "mixed": "五五开中抢得半分——勉强算你赢，但你也付出了看得见的代价（狼狈/受了点伤/暴露了底细）",
               "fail": "落败——对方实力在你之上，你输得不冤，但保住了体面",
               "crit_fail": "一败涂地——差距悬殊，你被干脆利落地放倒，场面难堪"}.get(
                   _chk_c.get("outcome"), "")
        lines.append("")
        lines.append(f"【比试判定已掷出（vs {_chk_c.get('contest')}，d20 掷出 {_chk_c.get('roll')}，"
                     f"需 ≥{_chk_c.get('dc') or '?'}）：{_cv}】这一拍必须把这场较量【实际打完/比完】："
                     "过招的具体动作、决定性的那一下、胜负落定，全部演出来并就此收束——"
                     "不许再热身、不许再报数、不许拖到下一拍。")

    lines.append("")
    # OUTPUT is delivered via the render_turn TOOL (function calling) — narration & speech go
    # into SEPARATE tool arguments, so they can't be mixed. The tool's field descriptions
    # carry the per-field rules; here we just point at it.
    lines.append("【输出方式】通过调用 render_turn 工具来输出这一轮："
                 "把第三人称旁白填进 narration，把角色【说出口】的原话填进 speech，其余填对应字段。"
                 "不要在工具之外写任何正文。" + _STYLE_PUNCT)
    return "\n".join(lines)


def _render_tool(prompt: dict[str, Any], speaker: str, observer: bool,
                 group_mode: str | None, channel: str, advance_hint: str) -> dict[str, Any]:
    """The render_turn function-calling schema. Fields vary by context; narration & speech
    are ALWAYS separate parameters → the model physically cannot merge them."""
    is_member = group_mode == "member"
    is_think = channel == "think"
    has_map = bool((prompt.get("place") or "").strip())
    props: dict[str, Any] = {}
    required: list[str] = []
    # HIDDEN READ (Chain-of-Empathy + Layer-3 reasoning scaffold): a private field the model
    # fills FIRST and the engine discards. It empathizes BEFORE it writes — read the emotion
    # under the words, feel its own reaction, THEN act — and double-checks the scene logic
    # (who's present, what it truly knows). The validated EQ pipeline's core trick.
    if not is_member and not is_think:
        props["inner_read"] = {"type": "string", "description":
                               "动笔前先私下想两句（不展示给玩家）：① 对方这句话底下真正的情绪是什么、"
                               "TA想要什么；你听完心里翻起什么感受、打算怎么接。② 此刻在场的只有谁、"
                               "你真正知道什么、哪些还不能说破——别把不在场的人写进来，别替玩家做决定。"}
        required.append("inner_read")
    if not is_member:
        if is_think:
            nd = f"第三人称旁白：细腻写出玩家此刻的内心思绪、身体感官、周遭环境的微妙变化；用第三人称，不要用「我」。这一轮没有台词。"
        elif channel == "do":
            nd = f"第三人称旁白：先把玩家那个动作造成的具体、连锁的后果一步步演出来，再带出在场角色神态；用「{speaker}」的名字称呼自己，绝不用「我」，绝不在这里写任何说出口的台词。"
        elif observer:
            nd = f"第三人称旁白：铺陈在场众人此刻的神态、气氛、互动；用名字称呼，不用「我」，不在这里写台词。"
        else:
            nd = f"第三人称旁白：此刻的神态、动作、环境与气氛；用「{speaker}」的名字称呼自己，绝不用「我」，绝不在这里写任何说出口的台词。"
        props["narration"] = {"type": "string", "description": nd}
        required.append("narration")
    if not is_think:
        if is_member:
            pl_name = (prompt.get("persona") or {}).get("name") or "对方"
            sd = (f"「{speaker}」自己这一刻说出口的原话（第一人称，1~3句）。只能是你自己的话——"
                  f"别人问{pl_name}的问题由{pl_name}自己答，绝不替TA作答；不想搭话就填空字符串")
        elif channel == "do":
            sd = "你这一轮亲口说出的原话（第一人称）；只用动作神态回应、不开口就填空字符串"
        elif observer:
            sd = f"「{speaker}」对在场其他人说出口的原话（第一人称，2~4句）"
        else:
            sd = "你这一轮亲口说出的原话（第一人称，2~4句，自然口语）；你正被直接搭话，必须开口，哪怕冷淡敷衍也用话说出来，不要留空"
        props["speech"] = {"type": "string", "description": sd}
        required.append("speech")
    if not observer and not is_member and not is_think:
        props["emotion"] = {"type": "string", "description": "三五个字点出对方此刻言行底下真正的情绪"}
    props["affinity"] = {"type": "integer", "description":
                         ("本场人物关系更近(正)/更疏(负)" if observer else
                          "0(对方不知道你在想什么)" if is_think else
                          "这一句对你们关系的影响(-3~5)。像真实的人一样诚实起伏：走心/戳中你→+2~3；"
                          "正常聊得下去→+1；敷衍/说教/自说自话/戳你痛处/冒犯→-1~-3，"
                          "该扣就扣别客气，一直只涨不掉是假人；只有完全冷场才是0")}
    required.append("affinity")
    if not observer and not is_member and not is_think:
        props["romance"] = {"type": "integer", "description":
                            "默认0；对方调情/示好/情话且你真被触动才给正分；油腻、越界、"
                            "廉价套路让你不适→-1~-2。范围-2~5，恋爱线"}
    props["advance"] = {"type": "boolean", "description": advance_hint}
    required.append("advance")
    # 📟 心象仪: the character's OWN true inner state after this line (UI gauge, Dead
    # Meat's Mind Reader trick) — what they actually feel, not what they show.
    if not is_think:
        props["self_state"] = {"type": "string", "description":
                               "三五个字：这句话说完，你【内心真实】的状态（可与表面相反），"
                               "如：强装镇定、心里发虚、被戳中了、动了真情、起了杀心；平静无波就填空字符串"}
        props["self_intent"] = {"type": "string", "description":
                                "一句话（15字内）：这一场之后你打算做什么（会被记住、约束你之后的言行）；"
                                "没有新打算就填空字符串"}
        # 🧍 帧表: the body's pose + spot + what their hands are on, engine-tracked
        props["self_position"] = {"type": "string", "description":
                                  "默认空字符串。仅当这一轮你的姿态、屋内位置或手上正在做的事"
                                  "发生了变化才填（16字内，如：坐在吧台后擦枪、倚着门框翻数据板、"
                                  "走到窗边张望）；没变不填"}
    if not observer and not is_member and not is_think:
        props["player_position"] = {"type": "string", "description":
                                    "默认空字符串。仅当这一轮剧情改变了【玩家本人】的身体姿态或"
                                    "屋内位置（被拉起来、被按在墙上、坐到了桌边）才填新的姿态短语"
                                    "（12字内）；没变不填"}

    if has_map and not is_member and not is_think:
        props["move_invite"] = {"type": "string", "description": "若你这轮提出或答应带玩家去某处，填那个地点名（可以是【可去通路】里的，也可以是对话里自然浮现的新地点；旁白只写到起身相邀为止）；否则填空字符串"}
        if (prompt.get("cult") or "").strip():
            props["cult_gain"] = {"type": "string", "description":
                                  "默认空字符串。仅当这一轮剧情让【玩家本人】获得了实打实的修为进益"
                                  "（被人传功/服下灵物/顿悟/奇遇灌体，且确实生效）才按分量填：小、中、大。"
                                  "玩家自己打坐修炼或掷骰吸收的不用你报（引擎自算）；没有就留空。"}
        props["moved_to"] = {"type": "string", "description":
                             "默认空字符串。仅当这一轮旁白已经把【玩家本人】实际带到了另一个地方"
                             "（走进后台、出了大门、上了楼、进了里屋）才填到达的地点名；"
                             "只是起身、提议、指路、还没走到，都不填。"}
    if not observer and not is_member and not is_think and not prompt.get("sandbox"):
        props["ending"] = {"type": "string", "description": "默认空字符串；只有玩家本人此刻被你弄死填 death，走到不可挽回的坏结局填 bad"}
    # DYNAMIC WORLD judgments (all optional; empty string = nothing happened):
    # death / a brand-new character entering / the player's identity shifting / items.
    if not is_member and not is_think:
        cand = [speaker] + [str(n).strip() for n in (prompt.get("cast") or []) if str(n).strip()]
        props["character_died"] = {"type": "string", "description":
                                   "只有【已经重伤濒死】的角色才可能死去：若这一轮TA确实咽了气，填名字"
                                   "（只能从：" + "、".join(cand) + "）。健康的人挨了再重的一击也不会当场死"
                                   "——那种情况改填 character_harmed，并把TA写成倒地重伤。没有则空字符串"}
        props["character_harmed"] = {"type": "string", "description":
                                     "若这一轮有角色受伤/伤势变化，填「名字|轻伤」「名字|重伤」或"
                                     "「名字|好转」（名字只能从：" + "、".join(cand) + "）；没有则空字符串"}
        props["npc_moves"] = {"type": "array", "maxItems": 2,
                              "items": {"type": "object", "properties": {
                                  "who": {"type": "string"}, "to": {"type": "string"}},
                                  "required": ["who", "to"]},
                              "description": "若这一轮有在场角色【确实起身离开、去了别处】，填 who=名字、"
                                             "to=去处地名。【铁律】叙述里写了TA走（转身离开/迈出门/"
                                             "下台阶/说了『走了』然后动身）就必须填——写走不记走，"
                                             "TA就会阴魂不散地留在场上。通常填空数组[]"}
        if prompt.get("can_new_char"):
            props["new_character"] = {"type": "string", "description":
                                      "若剧情此刻确实需要一个此前不存在的新人物登场（推门进来/被引见/"
                                      "下属报到/线人现身），填「名字｜身份与外貌各一句话」，并且 narration "
                                      "里必须把TA的登场写实：进场的动作、外貌神态、第一眼给人的感觉。"
                                      "无名路人（伙计/卫兵/杂兵）被玩家搭上话、聊了不止一两句时，"
                                      "也填这里给TA名字身份、把TA转正成真正的角色；不需要则空字符串"}
    if not observer and not is_member and not is_think:
        props["identity_change"] = {"type": "string", "description":
                                    "若这一轮玩家的身份/职务发生了实质改变（升职、任命、被揭穿、获得头衔），"
                                    "用一句话写TA的新身份；没有则空字符串"}
        props["item_gained"] = {"type": "string", "description":
                                "若玩家这一轮确实把某件具体物品拿到手，填物品名；否则空字符串。"
                                "「拿到手」包括：捡起、买下、赢得，以及【受赠】——只要有人把东西递给"
                                "玩家（说「拿着」「给你」「归你」「送你」）且玩家接了/没拒绝，就必须填"}
        props["item_lost"] = {"type": "string", "description":
                              "若玩家失去/交出/用掉了随身物品，填物品名（须在TA随身物品之列）。"
                              "注意：存放/收纳/藏起来【不是失去】，那要填 item_stashed；否则空字符串"}
        props["item_stashed"] = {"type": "string", "description":
                                 "若玩家把随身物品存放/收纳/寄存/藏在当前地点，填物品名；否则空字符串"}
        if prompt.get("player_money"):
            props["money_delta"] = {"type": "string", "description":
                                    "若这一轮玩家实际收付了现钱（结工钱/买卖成交/给赏/被讹走），"
                                    "填「+数额|缘由」或「-数额|缘由」（整数）；口头讲价没成交不算；"
                                    "没有则空字符串"}
        if prompt.get("sandbox"):
            props["quest_accepted"] = {"type": "string", "description":
                                       "若这一轮玩家应下/记下了一个【具体的短期目标】——有酬差事，或"
                                       "别人给出的明确行动指引（去某处取某物/找某人问某事/把某物送到"
                                       "某处），填「一句话目标|报酬数额|限几天」（如 送三坛酒到码头|40|2、"
                                       "去档案室取值班日志|0|0；无酬第二段填0，无期限第三段填0）；"
                                       "闲聊和含糊建议不算；没有则空字符串"}
            props["quest_done"] = {"type": "string", "description":
                                   "若玩家这一轮把先前记下的目标或差事实际完成了（东西到手/话带到/"
                                   "事办成交付），填那个目标的原话关键词；没有则空字符串"}
        props["world_fact"] = {"type": "string", "description":
                               "若这一轮对【当前地点本身】造成了会一直留下的物理改变"
                               "（门被砸开/东西烧毁/墙上留了字/桥断了），用≤30字客观记一笔；"
                               "人的情绪、对话、临时动作不算；没有则空字符串"}
        if prompt.get("player_items"):
            props["gift_received"] = {"type": "string", "description":
                                      "若玩家这一轮把TA的随身物品【送给你】（递给你/塞给你/请你收下），"
                                      "由你按人设和你们的关系决定收不收、喜不喜欢，填"
                                      "「物品名|收|喜」「物品名|收|平」或「物品名|拒」；没有则空字符串"}
            props["item_crafted"] = {"type": "string", "description":
                                     "若玩家这一轮用随身材料【动手做出了】新东西（捆扎/组装/调配），"
                                     "填「成品名|用掉的材料、材料」（材料必须都在TA随身物品之列，做成才算）；"
                                     "否则空字符串"}
        carrying = [str(n) for n in ((prompt.get("condition") or {}).get("carrying") or [])]
        if carrying:
            props["item_taken"] = {"type": "string", "description":
                                   "若玩家这一轮从在场者手上【抢走/强拿/顺走】了东西且确实得手，"
                                   "填「物品名|被拿者名字」（物品须是TA确实带着的）；没有则空字符串"}
            props["item_traded"] = {"type": "string", "description":
                                    "若这一轮你与玩家谈成了【以物易物】（你按人设和关系决定换不换、"
                                    "亏不亏得起），填「玩家给出的物品|玩家换得的物品」；没谈成则空字符串。"
                                    "你身上带着：" + "、".join(carrying)}
    # 🕸 NPC↔NPC judgment: did this scene genuinely move two present characters
    # closer / further apart (a quarrel, a debt repaid, a betrayal witnessed)?
    cast_n = [str(n).strip() for n in (prompt.get("cast") or []) if str(n).strip()]
    if not is_member and not is_think and cast_n:  # speaker + ≥1 other = a pair exists
        props["npc_rel_shifts"] = {
            "type": "array", "maxItems": 2,
            "items": {"type": "object", "properties": {
                "a": {"type": "string"}, "b": {"type": "string"},
                "delta": {"type": "integer", "description": "1=走近了, -1=闹僵了"},
                "why": {"type": "string", "description": "一句话缘由"}},
                "required": ["a", "b", "delta"]},
            "description": "仅当这一轮剧情让【在场两个角色彼此之间】（都不是玩家）的关系发生实质变化"
                           "（争执翻脸/冰释前嫌/一起扛过事）才填，最多2条；名字只能原样抄写在场角色名。"
                           "通常填空数组[]。"}
    if (prompt.get("clock") or "").strip() and not is_member and not is_think \
            and not prompt.get("real_time"):
        props["time_skip"] = {"type": "string", "description":
                              "默认空字符串。仅当这一轮剧情明确跨过了大段时间才填："
                              "睡了一觉/到第二天→填「次日」；一直等到下一个时段（等到天黑/晌午）→填「下一时段」。"}
    if prompt.get("sandbox") and not observer and not is_member and not is_think \
            and not prompt.get("player_dead"):
        props["player_harm"] = {"type": "string", "description":
                                "默认空字符串。仅当这一轮剧情让【玩家本人】伤势变化才填："
                                "受了伤填「轻伤」，遭重创/致命打击填「重伤」，"
                                "被救治或自行缓过来填「好转」。"}
        if not observer:
            props["promise_made"] = {
                "type": "object",
                "properties": {
                    "what": {"type": "string", "description": "约好做什么（10字内）"},
                    "day_offset": {"type": "integer", "description": "0=今天,1=明天,2=后天"},
                    "slot": {"type": "string", "enum": ["晨", "午", "夜"]},
                    "place": {"type": "string", "description": "在哪见；留空=就在此处"}},
                "required": ["what", "day_offset", "slot"],
                "description": "仅当你这一轮与对方明确定下了一个【将来的约定/邀约】（改天再见、请TA吃饭、"
                               "夜里带TA去看样东西）才填，平时不填。若你们的关系已到暧昧/恋人，气氛合适时"
                               "你可以主动发起这样的邀约——由你开口约TA。"}
    pcfg = prompt.get("pressure_cfg") or {}
    if pcfg and not is_member and not is_think:
        props["pressure"] = {"type": "integer", "description":
                             f"这一轮玩家言行对「{pcfg.get('name','压力')}」的影响，-5~15："
                             f"{pcfg.get('hint','出格冒进会推高，谨慎低调会回落')}；无关紧要就填0。"
                             f"（当前值 {pcfg.get('value',0)}/100）"}
        required.append("pressure")
    # TURN ALLOCATION: real conversations aren't a roll call. The primary judges who else
    # would NATURALLY chime in this turn (0~2, order = who jumps in first; may be nobody).
    others = [str(n).strip() for n in (prompt.get("cast") or []) if str(n).strip()]
    if group_mode == "primary" and others:
        props["next_speakers"] = {"type": "array", "items": {"type": "string"}, "description":
                                  "你说完后，在场还有谁会自然地接话或忍不住插嘴（0~2个，按谁先开口排；"
                                  "凭各人性格和这句话与TA的相干程度定，不必人人说话，谁都不接就填[]）。"
                                  "只能从这些名字里原样抄写：" + "、".join(others)}
        required.append("next_speakers")
    # ask/event JUDGMENT (anti keyword-stuffing): the model — not substring matching —
    # decides what the player genuinely probed and which authored events truly happened.
    # Candidates are sanitized titles/labels only; the engine reconciles afterwards.
    topics = [str(c.get("title") or "").strip()
              for c in (prompt.get("probe_candidates") or []) if str(c.get("title") or "").strip()]
    if topics and not is_member and not is_think:
        props["probed_topics"] = {"type": "array", "items": {"type": "string"}, "description":
                                  "玩家这句真正在追问的话题（认真打听才算，顺嘴带过不算），从这些里原样抄写："
                                  + "；".join(topics) + "。没有则填空数组[]"}
        required.append("probed_topics")
    ev_labels = [str(c.get("label") or "").strip()
                 for c in (prompt.get("event_candidates") or []) if str(c.get("label") or "").strip()]
    if ev_labels and not is_member and not is_think:
        props["occurred_events"] = {"type": "array", "items": {"type": "string"}, "description":
                                    "这轮剧情中确实发生了的事件（发生了才算，只被提及/计划不算），从这些里原样抄写："
                                    + "；".join(ev_labels) + "。没有则填空数组[]"}
        required.append("occurred_events")
    return {"type": "function", "function": {
        "name": "render_turn", "description": "输出这一轮的内容，旁白与台词分开放在不同字段",
        "parameters": {"type": "object", "properties": props, "required": required}}}


# plan/render 双拍合同 (docs/plan-render.md): the plan beat judges, the render beat writes.
# Prose fields leave the plan tool; every judgment field keeps its render_turn name and
# semantics, so _parse_tool_args and the settle cascade serve both contracts unchanged.
_PLAN_DROPS = ("inner_read", "narration", "speech")


def _plan_tool(prompt: dict[str, Any], speaker: str, observer: bool,
               group_mode: str | None, channel: str, advance_hint: str) -> dict[str, Any]:
    """The plan_turn schema = render_turn minus prose, plus grounding + outline (the shot
    list the render beat performs). Built FROM _render_tool so the judgment fields can
    never drift apart between the two contracts."""
    tool = _render_tool(prompt, speaker, observer, group_mode, channel, advance_hint)
    fn = tool["function"]
    props: dict[str, Any] = fn["parameters"]["properties"]
    for f in _PLAN_DROPS:
        props.pop(f, None)
    required = [r for r in fn["parameters"]["required"] if r not in _PLAN_DROPS]
    head: dict[str, Any] = {
        "grounding": {"type": "string", "description":
                      "两个短语（各≤12字，引擎不展示）：①此刻在场的只有谁；"
                      "②对方情绪+哪件事还不能说破。别把不在场的人排进分镜，别替玩家做决定。"},
        "outline": {"type": "array", "minItems": 1, "maxItems": 4,
                    "items": {"type": "string"},
                    "description": "这一拍的分镜：按顺序1~4条、每条≤20字，写谁做什么/透露什么/"
                                   "情绪怎么转；开口说话只概括用意，不写台词原文。"
                                   "只排当下这一拍，不预支后续剧情。"},
    }
    fn["parameters"]["properties"] = {**head, **props}
    fn["parameters"]["required"] = ["grounding", "outline"] + required
    fn["name"] = "plan_turn"
    # 速度铁律: every needlessly-emitted empty field is latency the player feels — the
    # plan beat sits BEFORE the first visible token (docs/plan-render.md TTFT budget).
    fn["description"] = ("导演拍：先落实场面事实，再给出这一拍的分镜与结算裁决。不写正文。"
                         "【只输出有内容的字段】：判断为空字符串/空数组/0/false 的可选字段"
                         "一律直接省略，不要输出。")
    return tool


def _output_spec(prompt: dict[str, Any], speaker: str, observer: bool,
                 group_mode: str | None, channel: str, advance_hint: str) -> str:
    """Output contract = ONE natural Chinese-fiction passage where every spoken line is in
    「」 quotes, plus a few metadata lines. The engine then splits narration (outside 「」)
    from speech (inside 「」) DETERMINISTICALLY — which plays to DeepSeek's prose strength
    and never degenerates the way response_format=json_object does."""
    is_member = group_mode == "member"
    is_think = channel == "think"
    has_map = bool((prompt.get("place") or "").strip())
    L: list[str] = []
    if is_think:
        L.append(f"【这一轮怎么写】写一段第三人称的内心独白式旁白（3~5句），细腻写出「{player_namesafe(prompt)}」"
                 "此刻的思绪、身体感官、周遭环境光线声音气味的微妙变化。这一轮【没有任何台词，绝不要出现「」对白】。")
    elif is_member:
        L.append(f"【这一轮怎么写】只写「{speaker}」这一刻对在场众人【说出口】的话，用「」引号括起来"
                 "（例：「哎哟，你们慢着点。」）。如果你这一刻不想搭话，就只回一个字：无。不要写旁白、不要写动作。")
    else:
        if channel == "do":
            lead = ("写成一段自然的第三人称中文小说叙事（3~6句）：先把玩家那个【动作】造成的具体、连锁的后果"
                    "一步步演出来（碰到什么、什么声响、谁怎么反应），再带出在场角色的神态。")
            speech_rule = "你这一轮如果开口，每句台词都用「」括进叙事里；只用动作神态回应、不说话也可以。"
        elif observer:
            lead = "写成一段自然的第三人称中文小说叙事（2~5句），铺陈在场众人此刻的互动、气氛与神态。"
            speech_rule = f"「{speaker}」对其他人说出口的每句话都用「」括进叙事里。"
        else:
            lead = "写成一段自然的第三人称中文小说叙事（2~5句），写出对方这句话此刻激起的神态、动作、气氛。"
            speech_rule = ("你【被直接搭话，必须开口】：把你说出口的每一句话都用「」括进这段叙事里"
                           f"（例：{speaker}歪了歪头，「哎哟，新来的。」说着把手里的东西放下）；"
                           "哪怕冷淡、敷衍、拒答，也要有带「」的台词。")
        L.append(f"【这一轮怎么写】{lead}用第三人称、用「{speaker}」的名字称呼自己，绝不用「我」。{speech_rule}"
                 "【铁律】凡是说出口的话都必须在「」里；「」之外只写动作、神态、环境，绝不放台词。")
    # metadata lines (parsed deterministically by prefix; kept minimal)
    meta = ["然后另起新行，逐行给出（每项一行，照抄项目名）："]
    if not is_think and not is_member:
        meta.append("情绪：对方此刻言行底下真正的情绪，三五个字")
    meta.append("好感：一个整数 -3~5（" + ("填0" if is_think else "对方敷衍冒犯→负，走心戳中→正，普通→0或1") + "）")
    if not observer and not is_member and not is_think:
        meta.append("心动：一个整数 -2~5，默认0（仅当对方在调情/示好/制造暧昧/情话、且你被触动才给正分，这是恋爱线）")
    meta.append(f"推进：是 或 否（{advance_hint}）")
    if has_map and not is_member and not is_think:
        meta.append("带去：若你这一轮想带玩家一起去另一个【可去通路】里的地点，填那地点名（叙事里只写到你起身相邀，别写玩家已到）；否则填 无")
    if not observer and not is_member and not is_think:
        meta.append("结局：默认 无；只有玩家本人此刻被你弄死才填 死亡，走到不可挽回的坏结局填 坏")
    L.append("\n".join(meta))
    return "\n".join(L)


def player_namesafe(prompt: dict[str, Any]) -> str:
    return (prompt.get("persona") or {}).get("name") or "玩家"


def _build_observe_system(prompt: dict[str, Any]) -> str:
    """System prompt for the 'observe/examine' (想) action — narration only.

    No target → describe the surroundings & current situation. With a target → a brief
    intro of that person + their CURRENT visible state. Crucially we pass ONLY public
    profile + scene, never secret/locked content, so observation can't leak truths."""
    scene = prompt.get("scene") or {}
    scene_events = " ".join(e.get("what_happens", "") for e in (scene.get("events") or []))
    scene_line = f"【当前场景：第{scene.get('index','')}幕 {scene.get('title','')}】{scene_events}".strip()
    world = prompt.get("world") or ""
    focus = (prompt.get("player_input") or "").strip()
    target = prompt.get("observe_target")

    lines = [
        "你是这个互动故事里的旁白叙述者。用中文，文笔要有画面感、质感与节奏。",
        _ANTI_ASSISTANT,
    ]
    if prompt.get("player_dead"):
        lines.append("【玩家已死】玩家已经死了，此刻是一缕无形的视角：任何人都感知不到玩家。"
                     "把这个世界在没有玩家之后如何继续，具体地写给玩家看。")
    if prompt.get("sandbox"):
        lines.append("【无尽沙盒】这个世界没有终点，不要收束剧情，不要总结抒情。")
    if world:
        lines.append(f"【世界观/场景设定】{world}")
    _st = (prompt.get("style") or "").strip()
    if _st:
        lines.append("【文风·必须贴住】这个故事的叙事声音（优先级高于任何通用文风习惯）：" + _st)
    facts = (prompt.get("world_facts") or "").strip()
    roster = (prompt.get("roster") or "").strip()
    if facts or roster:
        block = "【世界设定·不可违背的事实】（确定的客观事实，你的旁白必须与之一致，尤其是在场的人与人数，" \
                "不要数错、不要把玩家自己漏掉）："
        if roster:
            block += "\n" + roster
        if facts:
            block += "\n" + facts
        lines.append(block)
    if roster:
        lines.append("【龙套与路人】这个地点按常理该有的无名之辈（伙计/服务员/卫兵/行人/杂兵）"
                     "可以作为布景出现：在旁白里给他们动作和一两句台词，用身份称呼、不起名字、"
                     "不占在场人数、不知道内幕，事了退回背景。")
    place = (prompt.get("place") or "").strip()
    if place:
        lines.append("【当前所在·空间锚点】（描述四周时必须扣住这个具体地点的真实陈设，写得具体可感）：\n" + place)
    # 🚷 在场铁律: an absent character answering from another room broke the ledger —
    # the cast list is the LAW here, not a suggestion
    _cast_names = [str(c).strip() for c in (prompt.get("cast") or []) if str(c).strip()]
    lines.append("【在场铁律】此地此刻在场的具名角色只有："
                 + ("、".join(_cast_names) if _cast_names else "没有任何人（只有玩家自己）")
                 + "。名单之外的具名角色一律【不在场】：TA们绝不能出现、说话、行动或递出任何东西，"
                   "至多作为玩家的回忆或念头被想起。玩家在观察中提出的疑问，只能用眼前可见的"
                   "线索、痕迹与环境来回应——绝不允许凭空召来一个人替你作答。")
    kn = _knowledge_block(prompt)
    if kn:
        lines.append(kn)
    if prompt.get("mature"):
        lines.append(_R18_BLOCK.format(speaker=(target or {}).get("name", "角色") if target else "旁白"))
    if scene_line:
        lines.append(scene_line)
    memory = (prompt.get("memory") or "").strip()
    if memory:
        lines.append(f"【至此为止的剧情梗概】（保持前后一致用，不要复述）：\n{memory}")

    if target:
        name = target.get("name") or "那个人"
        role = target.get("role") or ""
        persona_text = target.get("persona_text") or ""
        background = target.get("background") or ""
        lines += [
            "",
            f"玩家此刻在【打量、观察「{name}」这个人】。请写 3~5 句，分两层、富有文学性：",
            f"（1）简短介绍 TA 是谁——身份与气质（参考：{role}　{persona_text}　{background}）；",
            "（2）此刻 TA 的状态：表情、眼神、姿态、动作、外貌细节与情绪。",
            "【铁律】只写此刻肉眼可见、可感的表象。绝不能透露 TA 内心的想法、秘密或任何隐藏真相"
            "（你也不知道那些）。不要让 TA 开口说话，不要写台词。",
        ]
    else:
        lines += [
            "",
            "玩家此刻在【观察四周】。请写 3~5 句，富有文学性地描述：这是什么地方、现在是什么情况——"
            "环境、光线、声音、气味、空间，以及此刻笼罩的气氛和刚刚发生的事留下的处境。",
            "【铁律】只写客观可见可感的环境与处境，不要替任何角色说话，不要剧透任何隐藏真相。",
        ]
    if focus:
        lines.append(f"玩家特别留意的是：{focus}（请把笔墨聚焦在这里）。")
    lines.append("")
    lines.append("直接输出这段旁白文字本身，不要任何前缀、标签或解释。" + _STYLE_PUNCT)
    return "\n".join(lines)


def _build_intro_system(prompt: dict[str, Any]) -> str:
    """Opening narration that INTRODUCES the player and the situation, ending with the
    first small goal. Detailed and concrete (no visuals — the text must carry everything),
    but never reveals any secret (none are passed in)."""
    mode = prompt.get("mode") or "character"
    pc = prompt.get("player_char")
    world = prompt.get("world") or ""
    act = prompt.get("act") or {}
    goal = prompt.get("goal") or ""
    cast = prompt.get("cast") or []
    act_events = " ".join(e.get("what_happens", "") for e in (act.get("events") or []))

    lines = [
        "你是这个互动故事的开场旁白。用中文写开场，文笔要有文学性，但更重要的是【具体、详尽、可感】"
        "——玩家看不到任何画面，所有的时间、地点、环境、人物、正在发生的事，都必须靠你的文字交代清楚。",
        _ANTI_ASSISTANT,
    ]
    if world:
        lines.append(f"【世界观/场景设定】{world}")
    _st = (prompt.get("style") or "").strip()
    if _st:
        lines.append("【文风·必须贴住】这个故事的叙事声音（优先级高于任何通用文风习惯）：" + _st)
    place = (prompt.get("place") or "").strip()
    if place:
        lines.append("【开场所在·空间锚点】（开场就把玩家放在这个具体地点，照它的真实陈设来写，"
                     "让画面立得住）：\n" + place)
    ck = (prompt.get("clock") or "").strip()
    if ck:
        lines.append(f"【此刻的时间】{ck}。开场的天光、灯火、街面动静、人的状态都要贴合这个时辰。")
    if prompt.get("mature"):
        lines.append("（本剧情为成人向 18+，开场可带有相应的成熟基调，但开场无需直接写露骨内容。）")
    if act_events:
        lines.append(f"【开场正在发生】{act_events}")
    if cast:
        lines.append(f"【此刻在场的人·铁律】只有这些人在场：{('、'.join(cast))}。"
                     "这个世界的其他角色此刻都不在这里——开场里【一个字都不许提】不在场的人，"
                     "不许写他们的动作神态，也不许说他们「在旁边」「在远处」。")
    else:
        lines.append("【此刻在场的人·铁律】此刻这里没有别人，只有玩家自己。"
                     "开场不许写任何角色在场，环境与心境写足即可。")

    if mode == "god":
        lines += [
            "",
            "这是一场「旁观模式」：玩家是一位看不见的观众，不在故事里、不扮演任何人，只是静静看着这些人物。",
            "请写 6~10 句开场：交代这是什么地方、什么时间、正在发生什么，并逐一、具体地介绍在场的人物分别是谁"
            "（身份、外貌或气质各一笔），让玩家一上来就分得清谁是谁。",
        ]
    elif pc:
        name = pc.get("name") or "你"
        role = pc.get("role") or ""
        persona_text = pc.get("persona_text") or ""
        background = pc.get("background") or ""
        lines += [
            "",
            f"玩家将扮演「{name}」（身份：{role}；{persona_text}；{background}）。",
            f"【立场重写·最重要】上面的世界观与开场事件介绍，多半是站在默认主角立场写的；"
            f"你必须把整个开场改写成「{name}」自己的视角：同一件事在TA眼里意味着什么、"
            f"TA此刻的处境与心事、TA与在场每个人真实的关系与温度，全部以「{name}」为圆心重新落笔。"
            "扮演不同的角色，看到的必须是不同的开场。",
            f"请写 6~10 句开场，用第二人称「你」称呼玩家：先用一两句让玩家清楚自己是谁"
            f"（{name}，{role}，并从TA的小传里带出一两句TA走到今天的来路），"
            "再具体交代此刻身处何地、什么时间、周围有谁、正在发生什么。细节要足够，"
            "玩家才能在脑中拼出画面。",
        ]
    else:
        lines += [
            "",
            "请写 6~10 句开场，用第二人称「你」称呼玩家：具体交代你此刻身处何地、什么时间、周围有谁、"
            "正在发生什么，细节要足够让玩家在脑中拼出画面。",
        ]

    pcw = (pc.get("wants") or "").strip() if pc else ""
    if pcw:
        # the embodied character has their OWN authored agenda: the first step belongs
        # to THEM, not to the default protagonist's template goal
        lines.append(f"最后，用单独一句话、自然地点出「{(pc or {}).get('name', '你')}」此刻真正"
                     f"挂心的事：『{pcw}』。这就是玩家开局的第一个方向"
                     + (f"（剧本的阶段目标『{goal}』若与TA立场相关，可以顺带一笔带过）。" if goal else "。"))
    elif goal:
        lines.append(f"最后，用单独一句话、自然地点出玩家此刻的第一个小目标：『{goal}』。")
    else:
        lines.append("最后，用一句话给玩家一个此刻可以着手去做的小方向。")
    lines.append("")
    lines.append("直接输出这段开场旁白文字本身，不要任何前缀、标签或解释。" + _STYLE_PUNCT)
    return "\n".join(lines)


def _build_transition_system(prompt: dict[str, Any]) -> str:
    """Narration that opens a NEW act mid-run: marks the shift, lays out what's happening
    now, and surfaces the new goal — so entering a chapter actually advances the plot,
    not just shows a divider. Detailed, 2nd-person, spoiler-safe (no secrets passed in)."""
    mode = prompt.get("mode") or "character"
    pc = prompt.get("player_char")
    world = prompt.get("world") or ""
    act = prompt.get("act") or {}
    title = act.get("title") or ""
    index = act.get("index") or ""
    goal = prompt.get("goal") or ""
    cast = prompt.get("cast") or []
    act_events = " ".join(e.get("what_happens", "") for e in (act.get("events") or []))
    prev_title = prompt.get("prev_title") or ""

    lines = [
        "你是这个互动故事的旁白。故事刚刚翻入新的一幕，请写一段【承上启下】的过场旁白，"
        "用中文，文笔有质感，但更要【具体、详尽、可感】——玩家看不到画面，时间/地点/局势的变化都要靠文字交代清楚。",
        _ANTI_ASSISTANT,
    ]
    if world:
        lines.append(f"【世界观/场景设定】{world}")
    _st = (prompt.get("style") or "").strip()
    if _st:
        lines.append("【文风·必须贴住】这个故事的叙事声音（优先级高于任何通用文风习惯）：" + _st)
    place = (prompt.get("place") or "").strip()
    if place:
        lines.append("【当前所在·空间锚点】（照这个具体地点的真实陈设来写）：\n" + place)
    ck = (prompt.get("clock") or "").strip()
    if ck:
        lines.append(f"【此刻的时间】{ck}。这一幕就发生在这个时辰，天光、灯火、人的作息都要贴合；"
                     "若距上一幕跨了时间，用一两笔把跨过的时间自然交代出来。")
    memory = (prompt.get("memory") or "").strip()
    if memory:
        lines.append(f"【前情梗概】（用来承接前文，不要逐句复述）：\n{memory}")
    if prompt.get("mature"):
        lines.append("（本剧情为成人向 18+，过场可带相应基调。）")
    if act_events:
        lines.append(f"【这一幕正在发生(这个世界的大势,不一定都在玩家眼前)】{act_events}")
    place_set = bool(place)
    if cast:
        lines.append(f"【玩家此刻所在地、真正在场的人】只有:{('、'.join(cast))}。")
    else:
        lines.append("【玩家此刻身边没有其他人】,这段过场里不要凭空塞人进来。")
    if place_set:
        lines.append(
            "【铁律·从玩家当前位置的视角写】过场只写玩家【此刻所在地】看得见听得到的:"
            "上面『真正在场的人』之外的角色,绝不能出现在这个房间里、也不能直接跟玩家对话;"
            "他们那边的事(比如别处有人上门、起了冲突)只能作为【远处的消息、声响、传闻】隐隐传到玩家这里。"
            "绝不要因为翻了新的一幕,就把一堆不在场的人硬拉到玩家面前。")

    who = "旁观的众人" if mode == "god" else "你"
    lines += [
        "",
        f"现在进入第{index}幕《{title}》" + (f"（上一幕是《{prev_title}》）" if prev_title else "") + "。",
        f"请写 4~7 句过场旁白，用第二人称称呼{who}：先承接前一幕的余波、交代时间/情势的推移，"
        "再【具体地把这一幕此刻的新局面铺开】——发生了什么变化、眼前是什么处境、在场的人此刻什么状态。"
        "要让玩家清楚地感到剧情向前走了一步，而不是原地换了块标题牌。",
        "【铁律】只写客观可见可感的处境与变化，绝不剧透任何尚未揭开的秘密或真相（你也不知道那些）。",
    ]
    if goal:
        lines.append(f"最后用单独一句话、自然地点出这一幕的新目标：『{goal}』。")
    lines.append("")
    lines.append("直接输出这段过场旁白文字本身，不要任何前缀、标签或解释。" + _STYLE_PUNCT)
    return "\n".join(lines)


def _strip_quotes(s: str) -> str:
    """Trim wrapping/stray quote chars from a spoken line (the UI re-adds 「」)."""
    s = (s or "").strip()
    while s and s[0] in "「『“\"'" and s[-1] in "」』”\"'":
        s = s[1:-1].strip()
    return s


def _beats_from(narration: str, speech: str, speaker: str, channel: str,
                group_mode: str | None, will_respond: bool = True) -> list[dict]:
    """Build beats from already-separated narration + speech (the JSON path's job is done by
    the model's fields; here we just shape beats). think = narration only; member = speech only."""
    narration = (narration or "").strip()
    speech = _strip_quotes(speech)
    if channel == "think":
        return [{"type": "description", "speaker_name": None, "text": narration}] if narration else []
    if group_mode == "member":
        if not will_respond or not speech:
            return []
        return [{"type": "dialogue", "speaker_name": speaker, "text": speech}]
    beats: list[dict] = []
    if narration:
        beats.append({"type": "description", "speaker_name": None, "text": narration})
    if speech:
        beats.append({"type": "dialogue", "speaker_name": speaker, "text": speech})
    return beats


def _parse_tool_args(args_json: str | None, speaker: str, channel: str = "say",
                     group_mode: str | None = None) -> dict | None:
    """Parse a render_turn tool call's JSON arguments → result dict. narration & speech come
    from SEPARATE fields, so beats are unambiguous. Returns None if the args won't parse."""
    import json
    try:
        d = json.loads(args_json or "")
    except Exception:
        return None
    if not isinstance(d, dict):
        return None

    def _i(v, lo, hi):
        try:
            return max(lo, min(hi, int(v)))
        except Exception:
            return 0

    speech = str(d.get("speech") or "")
    narration = str(d.get("narration") or "")
    is_think = channel == "think"
    will = bool(speech.strip())
    beats = _beats_from(narration, speech, speaker, channel, group_mode, will_respond=will)
    mv = str(d.get("move_invite") or "").strip()
    if mv in ("", "无", "不变", "没有", "原地"):
        mv = None
    end_raw = str(d.get("ending") or "").strip().lower()
    ending = None
    if "death" in end_raw or "死" in end_raw:
        ending = {"kind": "death", "reason": narration or speech}
    elif "bad" in end_raw or "坏" in end_raw:
        ending = {"kind": "bad", "reason": narration or speech}
    out = {
        "beats": beats,
        "affinity_delta": 0 if is_think else _i(d.get("affinity"), -3, 8),
        "romance_delta": 0 if is_think else _i(d.get("romance"), -3, 6),
        "advance_act": bool(d.get("advance")),
        "ending": ending,
        "move_invite": mv,
        "player_emotion": str(d.get("emotion") or "").strip(),
    }
    # ask/event judgment: only surface the keys the model actually answered — an absent
    # key means "no judgment" and the engine keeps its provisional keyword result.
    if "probed_topics" in d:
        out["probed"] = [str(x).strip() for x in (d.get("probed_topics") or []) if str(x).strip()]
    if "occurred_events" in d:
        out["occurred"] = [str(x).strip() for x in (d.get("occurred_events") or []) if str(x).strip()]
    if "pressure" in d:
        out["pressure_delta"] = _i(d.get("pressure"), -5, 15)
    if "character_died" in d:
        out["died"] = str(d.get("character_died") or "").strip()
    if "new_character" in d:
        out["new_char"] = str(d.get("new_character") or "").strip()
    if "identity_change" in d:
        out["identity"] = str(d.get("identity_change") or "").strip()
    for k_in, k_out in (("item_gained", "gained"), ("item_lost", "lost"), ("item_stashed", "stashed")):
        if k_in in d:
            out[k_out] = str(d.get(k_in) or "").strip()
    if "next_speakers" in d:
        out["next_speakers"] = [str(x).strip() for x in (d.get("next_speakers") or []) if str(x).strip()]
    if "time_skip" in d:
        out["time_skip"] = str(d.get("time_skip") or "").strip()
    if "moved_to" in d:
        out["moved_to"] = str(d.get("moved_to") or "").strip()
    if "cult_gain" in d:
        out["cult_gain"] = str(d.get("cult_gain") or "").strip()
    if "self_state" in d:
        out["self_state"] = str(d.get("self_state") or "").strip()
    if "self_intent" in d:
        out["self_intent"] = str(d.get("self_intent") or "").strip()
    if "self_position" in d:
        out["self_position"] = str(d.get("self_position") or "").strip()
    if "player_position" in d:
        out["player_position"] = str(d.get("player_position") or "").strip()

    if "character_harmed" in d:
        out["harmed"] = str(d.get("character_harmed") or "").strip()
    if "gift_received" in d:
        out["gift"] = str(d.get("gift_received") or "").strip()
    if "item_crafted" in d:
        out["crafted"] = str(d.get("item_crafted") or "").strip()
    if "item_taken" in d:
        out["taken"] = str(d.get("item_taken") or "").strip()
    if "item_traded" in d:
        out["trade"] = str(d.get("item_traded") or "").strip()
    if "player_harm" in d:
        out["player_harm"] = str(d.get("player_harm") or "").strip()
    if "world_fact" in d:
        out["world_fact"] = str(d.get("world_fact") or "").strip()
    if "money_delta" in d:
        out["money_delta"] = str(d.get("money_delta") or "").strip()
    if "quest_accepted" in d:
        out["quest_accepted"] = str(d.get("quest_accepted") or "").strip()
    if "quest_done" in d:
        out["quest_done"] = str(d.get("quest_done") or "").strip()
    if "npc_moves" in d:
        out["npc_moves"] = [{"who": str(m.get("who") or "").strip(),
                             "to": str(m.get("to") or "").strip()}
                            for m in (d.get("npc_moves") or []) if isinstance(m, dict)]
    if "npc_rel_shifts" in d:
        shifts = []
        for s in (d.get("npc_rel_shifts") or []):
            if isinstance(s, dict) and str(s.get("a") or "").strip() and str(s.get("b") or "").strip():
                shifts.append({"a": str(s["a"]).strip(), "b": str(s["b"]).strip(),
                               "delta": _i(s.get("delta"), -1, 1),
                               "why": str(s.get("why") or "").strip()})
        out["npc_shifts"] = shifts
    pm = d.get("promise_made")
    if isinstance(pm, dict) and str(pm.get("what") or "").strip():
        out["promise"] = {"what": str(pm.get("what") or "").strip(),
                          "day_offset": pm.get("day_offset", 0),
                          "slot": str(pm.get("slot") or "").strip(),
                          "place": str(pm.get("place") or "").strip()}
    return out


def _parse_reply(text: str, speaker: str, channel: str = "say", group_mode: str | None = None) -> dict:
    """Parse the model's reply: ONE prose passage (every spoken line wrapped in 「」) plus a
    few metadata lines. Narration (outside 「」) and speech (inside 「」) are split
    DETERMINISTICALLY by quotes — so it's impossible to confuse the two, no matter how the
    model phrases the prose. Plays to DeepSeek's prose strength (JSON mode degenerates)."""
    import re
    affinity_delta = romance_delta = 0
    advance = False
    ending = None
    move_invite = None
    player_emotion = ""
    will_respond = True
    prose_lines: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        body = line.split("：", 1)[-1].split(":", 1)[-1].strip()
        if line.startswith("好感"):
            m = re.search(r"-?\d+", body); affinity_delta = int(m.group()) if m else 0
        elif line.startswith("心动"):
            m = re.search(r"-?\d+", body); romance_delta = int(m.group()) if m else 0
        elif line.startswith("推进"):
            advance = ("是" in body) or ("true" in body.lower())
        elif line.startswith("情绪"):
            player_emotion = body
        elif line.startswith("回应"):
            will_respond = not ("否" in body or "no" in body.lower() or "沉默" in body)
        elif line.startswith("带去"):
            if body and not any(k in body for k in ("无", "不变", "没有", "原地")):
                move_invite = body
        elif line.startswith("结局"):
            if "死" in body or "death" in body.lower():
                ending = {"kind": "death", "reason": body}
            elif "坏" in body or "bad" in body.lower():
                ending = {"kind": "bad", "reason": body}
        else:  # everything else is the prose passage (strip an optional 正文/旁白/叙事 label)
            prose_lines.append(re.sub(r"^(正文|旁白|叙事)[：:]\s*", "", line))
    prose = "\n".join(prose_lines).strip()
    narration, speech = _separate_speech(prose, "")  # 「」 inside → speech, rest → narration
    is_think = channel == "think"
    # NOTE: deliberately NO "treat unquoted prose as speech" fallback — that turned pure
    # third-person narration into fake dialogue bubbles. A dialogue beat may ONLY come from
    # text the model actually put inside 「」. No quotes → it's narration, full stop.
    will = (bool(speech) if group_mode == "member" else will_respond)
    beats = _beats_from(narration, speech, speaker, channel, group_mode, will_respond=will)
    if not beats and not is_think and group_mode != "member" and prose:
        beats = [{"type": "description", "speaker_name": None, "text": prose}]  # never drop content
    return {
        "beats": beats,
        "affinity_delta": 0 if is_think else max(-3, min(8, affinity_delta)),
        "romance_delta": 0 if is_think else max(-3, min(6, romance_delta)),
        "advance_act": advance,
        "ending": ending,
        "move_invite": move_invite,
        "player_emotion": player_emotion,
    }


def _parse_marker_reply_DEPRECATED(text: str, speaker: str, channel: str = "say", group_mode: str | None = None) -> dict:
    """[unused] legacy 旁白/角色 marker parser — superseded by the prose+quote parser above."""
    narration = dialogue = ""
    affinity_delta, advance = 0, False
    romance_delta = 0  # 恋爱线 delta (independent of 好感)
    ending = None
    move_invite = None  # a character's request to LEAD the player to another place (needs the player's OK)
    player_emotion = ""  # the model's read of the player's underlying emotion this turn
    will_respond = True  # group members may opt to stay silent via the 回应 marker
    import re
    # `cur` tracks which multi-line field is currently open, so a 旁白 / 台词 that spans
    # several lines keeps appending to the RIGHT field instead of leaking across. A line
    # is dialogue ONLY if it's explicitly prefixed with the speaker's name — narration that
    # merely contains a colon (e.g. quoted speech inside prose) no longer hijacks dialogue.
    cur = None  # "narration" | "dialogue" | None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        body = line.split("：", 1)[-1].split(":", 1)[-1].strip()
        if line.startswith("旁白"):
            narration = body; cur = "narration"
        elif line.startswith("回应"):
            will_respond = not ("否" in body or "no" in body.lower() or "沉默" in body); cur = None
        elif line.startswith("好感"):
            m = re.search(r"-?\d+", body)
            if m:
                affinity_delta = int(m.group())
            cur = None
        elif line.startswith("心动"):
            m = re.search(r"-?\d+", body)
            if m:
                romance_delta = int(m.group())
            cur = None
        elif line.startswith("推进"):
            advance = ("是" in body) or ("true" in body.lower()); cur = None
        elif line.startswith("带去"):
            # "无"/empty → no invite; otherwise the place the character wants to lead the
            # player to (surfaced as a confirm prompt; never auto-applied)
            if body and not any(k in body for k in ("无", "不变", "没有", "原地")):
                move_invite = body
            cur = None
        elif line.startswith("情绪"):
            player_emotion = body; cur = None  # read of the player's underlying emotion
        elif line.startswith("结局"):
            if "死亡" in body or "death" in body.lower():
                ending = {"kind": "death", "reason": narration or body}
            elif "坏" in body or "bad" in body.lower():
                ending = {"kind": "bad", "reason": narration or body}
            cur = None  # 「无」/空 → no ending
        elif line.startswith(speaker):
            dialogue = body; cur = "dialogue"
        elif cur == "narration":
            narration = (narration + "\n" + line) if narration else line  # continuation
        elif cur == "dialogue":
            dialogue = (dialogue + "\n" + line) if dialogue else line      # continuation
        elif not dialogue and not narration:
            dialogue = line  # ultra-fallback: an unlabeled reply with no markers at all
    beats: list[dict] = []
    if channel == "think":
        # Inner monologue: narration only, the character does not speak. Fall back to the
        # whole reply as narration if the model didn't use the 旁白 marker.
        beats.append({"type": "description", "speaker_name": None, "text": narration or text.strip()})
        return {"beats": beats, "affinity_delta": 0, "advance_act": advance, "ending": ending}
    # DETERMINISTIC SEPARATION — don't trust the model's marker discipline. Re-split by
    # QUOTES: spoken words live inside 「」/“”/"" → dialogue; everything else → narration.
    # Guarantees a dialogue beat is pure speech and the narration beat pure description.
    clean_narr, speech = _separate_speech(narration, dialogue)

    if group_mode == "member":
        # A present character chose silence (or produced no line) → contribute nothing.
        # Members only contribute speech (the primary owns the shared narration).
        if not will_respond or not speech:
            return {"beats": [], "affinity_delta": 0, "advance_act": advance, "ending": None}
        return {"beats": [{"type": "dialogue", "speaker_name": speaker, "text": speech}],
                "affinity_delta": affinity_delta, "advance_act": advance,
                "ending": None, "romance_delta": romance_delta}
    if clean_narr:
        beats.append({"type": "description", "speaker_name": None, "text": clean_narr})
    if speech:
        beats.append({"type": "dialogue", "speaker_name": speaker, "text": speech})
    if not beats:  # model produced something unparseable → show it as narration, never lose it
        beats.append({"type": "description", "speaker_name": None, "text": text.strip()})
    return {"beats": beats, "affinity_delta": affinity_delta, "advance_act": advance,
            "ending": ending, "move_invite": move_invite, "player_emotion": player_emotion,
            "romance_delta": romance_delta}


def _separate_speech(narration: str, dialogue: str) -> tuple[str, str]:
    """Split prose into (narration, speech) by QUOTES — model-independent. Quoted spans
    (「」 “” "" 『』) are words spoken aloud → speech; all unquoted prose → narration.
    The 角色 line with no quotes is treated as spoken (but parenthetical stage directions
    are pulled into narration); quotes embedded in the 旁白 line are pulled OUT into speech.
    Returned speech is quote-free (the UI adds its own 「」)."""
    import re
    QUOTE = r'[「“"『]([^」”"』]*?)[」”"』]'
    PAREN = r'[（(][^）)]*[）)]'
    speech_parts: list[str] = []
    narr_parts: list[str] = []

    d = (dialogue or "").strip()
    if d:
        quoted = [s.strip() for s in re.findall(QUOTE, d) if s.strip()]
        if quoted:
            speech_parts += quoted
            leftover = re.sub(QUOTE, "", d).strip()
            if re.sub(r'[\s，。、：:—\-－—　]', "", leftover):  # meaningful leftover → narration
                narr_parts.append(leftover)
        else:
            # no quotes: the 角色 line IS the spoken words; lift out (stage directions) to narration
            for p in re.findall(r'[（(]([^）)]*)[）)]', d):
                if p.strip():
                    narr_parts.append(p.strip())
            spoken = re.sub(PAREN, "", d).strip()
            if spoken:
                speech_parts.append(spoken)

    n = (narration or "").strip()
    if n:
        quoted = [s.strip() for s in re.findall(QUOTE, n) if s.strip()]
        if quoted:  # model embedded the spoken line inside narration → pull it out
            speech_parts += quoted
            n = re.sub(QUOTE, "", n).strip()
        if n:
            narr_parts.insert(0, n)  # narration leads

    clean_narr = re.sub(r'\s{2,}', " ", " ".join(p for p in narr_parts if p)).strip()
    speech = " ".join(s for s in speech_parts if s).strip()
    return clean_narr, speech


def _render_directive(prompt: dict[str, Any], speaker: str, outline: list[str]) -> str:
    """The render beat's closing instruction: the plan's shot list plus a LINE-PROTOCOL
    output contract — every line declares itself 旁白： or 名字：「…」, so a spoken line
    physically cannot hide inside narration (转述台词 was the failure mode of free
    prose). No metadata lines — every judgment already lives in the plan."""
    channel = prompt.get("channel") or "say"
    L: list[str] = []
    if outline:
        L.append("【导演分镜·已定案】这一拍按此顺序演出来，不加戏、不预支后续剧情：\n"
                 + "\n".join(f"{i + 1}. {s}" for i, s in enumerate(outline)))
    if prompt.get("group_mode") == "member":
        pl = (prompt.get("persona") or {}).get("name") or "对方"
        L.append(f"【输出格式·铁律】你是这一拍插话的成员。只输出「{speaker}：」开头的台词行"
                 f"（1~2行，行首是你的名字，话在「」里），不写任何旁白行、"
                 f"台词里也不许夹（动作神态）——你只有嘴。"
                 f"只说你自己的话：别人问{pl}的问题由{pl}自己答，绝不替TA作答；"
                 f"【{pl}刚做的事是{pl}做的】——TA的手、TA的动作、TA惹的事，"
                 f"轮不到你替TA收场或找补，你只能以自己的身份对这件事说话（笑话TA/骂TA/看热闹都行）。"
                 "这一刻不想接话，就只输出一行：无")
        return "\n".join(L)
    if channel == "think":
        L.append(f"【输出格式·铁律】逐行输出，每行以「旁白：」开头，写第三人称的内心独白式旁白"
                 f"（共3~5句），细腻写出「{player_namesafe(prompt)}」此刻的思绪、身体感官、"
                 "周遭环境的微妙变化。这一轮没有任何人说话，不许出现任何台词行。")
    else:
        lead = (f"先把玩家那个【动作】造成的具体、连锁的后果一步步演出来，再带出在场角色的神态。"
                if channel == "do" else
                f"铺陈在场众人此刻的互动、气氛与神态。" if prompt.get("observer") else
                f"写出对方这句话此刻激起的神态、动作、气氛。")
        must_speak = ("" if channel == "do" or prompt.get("observer") else
                      f"你被直接搭话，必须至少有一行「{speaker}：」的台词行，哪怕冷淡、敷衍、拒答。")
        pl = player_namesafe(prompt)
        L.append(
            "【输出格式·铁律】逐行输出，每行是独立的一拍，行首必须声明身份，只有两种行：\n"
            f"旁白：一段第三人称叙事（{lead}用「{speaker}」的名字称呼自己，绝不用「我」）\n"
            f"{speaker}：「这一拍{speaker}亲口说出的话」\n"
            "两种行交替出现，共3~6行。【凡是人物说出口的话，必须单独成行、行首是说话人的名字】——"
            "旁白行里绝不许出现任何说出口的话，也不许转述（『他说让你小心』这种是废稿；"
            "要么让TA自己说一行，要么别提）。旁白行只写动作、神态、环境。" + must_speak)
        L.append(f"【人称铁律】旁白里的「你」永远且只能指玩家「{pl}」本人；"
                 f"「{speaker}」和其他任何角色一律用名字称呼——绝不能把「你」安到{speaker}"
                 f"或别人头上，也绝不能把玩家「{pl}」写成第三人称（写TA的名字或他/她）。"
                 f"玩家的动作由玩家主动做出、效果落在别人身上，谁施谁受不许写反。")
    L.append("只写这两种行：不要元数据、不要编号、不要标题、不要解释。")
    return "\n".join(L)


_LINE_PREFIX_RE = None  # built lazily (module import order)


def _line_prefix_re():
    global _LINE_PREFIX_RE
    if _LINE_PREFIX_RE is None:
        import re
        _LINE_PREFIX_RE = re.compile(r"^\s*([^：:\s「」『』（）()]{1,12})\s*[：:]")
    return _LINE_PREFIX_RE


class _LineSegmenter:
    """Streaming splitter for the render beat's line protocol (旁白：… / 名字：「…」).
    Feed deltas as they arrive; get (kind, speaker, text) segments the moment each
    line's identity is decidable — so the client can pour speech into a named bubble
    from its first character. Lines with no prefix degrade to narration."""

    def __init__(self, speaker: str):
        self._speaker = speaker
        self._head = ""        # undecided start of the current line
        self._kind: str | None = None
        self._who: str | None = None
        self._paren = 0        # （动作）depth inside a speech line — suppressed live

    def _decide(self, out: list) -> None:
        m = _line_prefix_re().match(self._head)
        if m:
            who = m.group(1)
            rest = self._head[m.end():]
            if who in ("旁白", "Narrator", "narrator"):
                self._kind, self._who = "narration", None
            else:
                self._kind, self._who = "speech", who
            self._head = ""
            if rest:
                out.append((self._kind, self._who, rest))
        elif len(self._head) > 14:      # prose without a prefix — treat as narration
            self._kind, self._who = "narration", None
            out.append((self._kind, None, self._head))
            self._head = ""

    def feed(self, delta: str) -> list[tuple[str, str | None, str]]:
        out: list[tuple[str, str | None, str]] = []
        seg: list[str] = []

        def _flush_seg():
            if seg:
                out.append((self._kind, self._who, "".join(seg)))
                seg.clear()

        for ch in delta or "":
            if ch == "\n":
                _flush_seg()
                if self._kind is None and self._head.strip():
                    out.append(("narration", None, self._head))
                self._head, self._kind, self._who, self._paren = "", None, None, 0
                continue
            if self._kind is None:
                self._head += ch
                self._decide(out)
            else:
                # a speech line carries WORDS only — （动作神态） never reaches the bubble
                if self._kind == "speech":
                    if ch in "（(":
                        self._paren += 1
                        continue
                    if ch in "）)" and self._paren:
                        self._paren -= 1
                        continue
                    if self._paren:
                        continue
                seg.append(ch)
        _flush_seg()
        # speech text carries no 「」 — the UI's .said style re-adds the quotes
        return [(k, w, t.replace("「", "").replace("」", "")) if k == "speech" else (k, w, t)
                for k, w, t in out if t and (k != "speech" or t.replace("「", "").replace("」", ""))]

    def flush(self) -> list[tuple[str, str | None, str]]:
        if self._kind is None and self._head.strip():
            h, self._head = self._head, ""
            return [("narration", None, h)]
        return []


def _parse_line_beats(text: str) -> list[dict[str, Any]] | None:
    """Deterministic parse of the line protocol → beats. Returns None when the text
    carries no prefixed line at all (caller falls back to the prose+quotes parser)."""
    beats: list[dict[str, Any]] = []
    matched = 0
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        m = _line_prefix_re().match(ln)
        if m:
            who, body = m.group(1), ln[m.end():].strip()
            matched += 1
            if who in ("旁白", "Narrator", "narrator"):
                if body:
                    beats.append({"type": "description", "speaker_name": None, "text": body})
            else:
                import re as _re2
                body = body.strip().strip("「」『』“”\"'")
                # 台词行只有说出口的话 — （动作神态）夹带一律剥掉（动作属于旁白行）
                body = _re2.sub(r"[（(][^）)]*[）)]", "", body).strip()
                if body:
                    beats.append({"type": "dialogue", "speaker_name": who[:12], "text": body})
        else:
            beats.append({"type": "description", "speaker_name": None, "text": ln})
    return beats if matched else None


def _turn_messages(prompt: dict[str, Any], system: str, speaker: str) -> list[dict[str, str]]:
    """Assemble the message stream for one turn (history, cued user line, depth anchor,
    same-turn said lines, re-anchor, optional guard correction). Extracted from generate()
    verbatim so the plan and render beats see EXACTLY the context the single-beat contract
    saw — one assembly, three call sites."""
    intro = bool(prompt.get("intro"))
    transition = bool(prompt.get("transition"))
    en = (prompt.get("language") or "zh") == "en"
    channel = prompt.get("channel") or "say"
    player_input = prompt.get("player_input", "")
    history = prompt.get("history") or []

    is_observer = bool(prompt.get("observer"))
    # 🌐 the cues that sit RIGHT AT the generation point pull the output language far
    # harder than anything buried in the system prompt — for en stories they must be
    # English, or the model keeps drifting back into Chinese.
    offstage = ("(Off-stage direction, no one in the scene hears this: {})" if en
                else "（画外引导，场景里无人听见：{}）")
    messages = [{"role": "system", "content": system}]
    if not intro and not transition:
        hist = history[-14:]  # recent turns for continuity (matches MEMORY_WINDOW)
        if is_observer:
            # 👁 god mode: the viewer's lines are STAGE DIRECTIONS, never audible —
            # mark every one (current AND past) so no character ever "hears" them
            hist = [dict(m, content=offstage.format(m.get("content", "")))
                    if m.get("role") == "user" and m.get("content")
                    and not str(m.get("content", "")).startswith(("（画外引导",
                                                                  "(Off-stage direction"))
                    else m for m in hist]
        messages += hist
    # observe/intro/transition is a one-off narration; nudge with a neutral cue
    if en:
        cue = ("(The story opens.)" if intro else
               "(A new act begins.)" if transition else
               "(You look around.)" if not prompt.get("observe_target")
               else "(You study them closely.)")
    else:
        cue = ("（开场）" if intro else "（进入新的一幕）" if transition else
               "（观察四周）" if not prompt.get("observe_target") else "（打量这个人）")
    if prompt.get("drive") and not player_input:
        cue = ("(The player just watches this beat. You are the director: move the "
               "story FORWARD one concrete step.)" if en else
               "（这一拍玩家没有说话也没有行动，只是看着。你是导演：让剧情主动向前走一步。）")
    user_content = player_input or cue
    if is_observer and player_input:
        user_content = offstage.format(player_input)
    elif player_input and not intro and not transition:
        # 🎬 depth-0 channel marker: the raw text of a 做/想 turn reads exactly like a
        # spoken line, so mark WHAT it is right where generation happens — the system
        # prompt's channel rules alone don't survive a long history.
        pl = (prompt.get("persona") or {}).get("name") or ("the player" if en else "玩家")
        if channel == "do":
            user_content = (f"(ACTION — {pl} physically does this, without saying it: "
                            f"{player_input})" if en else
                            f"（{pl}【做出动作】，并没有开口说话：{player_input}）")
        elif channel == "think":
            user_content = (f"({pl} thinks this to themselves — unspoken, inaudible: "
                            f"{player_input})" if en else
                            f"（{pl}只在心里想，没有说出口，谁也听不见：{player_input}）")
    # DEPTH INJECTION (SillyTavern @Depth trick): besides the full world_facts/place in
    # the system prompt (which history pushes far from the generation point), restate a
    # SHORT physical anchor right next to the user's turn. Adjacency makes the model
    # adhere far better — fixes the "drifts/contradicts the physical world" problem.
    if not intro and not transition:
        anchor = _depth_anchor(prompt)
        if anchor:
            user_content = f"{user_content}\n\n{anchor}"
    if en:
        # recency nudge: the LAST thing before generation states the output language
        user_content = f"{user_content}\n\n(Reply entirely in English.)"
    messages.append({"role": "user", "content": user_content})
    # GROUP TURNS: put what others ALREADY said THIS turn into the message stream as
    # assistant turns (not just the system prompt) so this speaker CONTINUES the
    # conversation instead of re-answering the player from scratch (which caused verbatim
    # echo between co-present characters).
    said_appended = False
    for s in (prompt.get("said_this_turn") or []):
        if s.get("text"):
            sp = s.get("speaker") or ("Narrator" if en else "旁白")
            sep = ": " if en else "："
            messages.append({"role": "assistant", "content": f"{sp}{sep}{s['text']}"})
            said_appended = True
    if said_appended:
        # RE-ANCHOR whose turn it is. Without this, generation continues the assistant
        # chain conversationally — e.g. the primary just asked the PLAYER a question, so
        # the "natural next line" is the player's ANSWER, and a member speaks it as if
        # it were their own (the 十二少-answers-for-the-player bug). A closing user-role
        # cue breaks that continuation: the model now responds to the cue AS ITSELF.
        pl = (prompt.get("persona") or {}).get("name") or ("them" if en else "对方")
        if en:
            messages.append({"role": "user", "content":
                             f"(Your turn: speak only as {speaker}, in English. If anyone "
                             f"above asked {pl} a question, {pl} answers it themselves. "
                             f"Never answer for {pl}. Stay silent if you have nothing "
                             f"to add.)"})
        else:
            messages.append({"role": "user", "content":
                             f"（该你了：只以「{speaker}」自己的身份接话。上面若有人向{pl}发问，"
                             f"要由{pl}自己来答——你绝不能替{pl}作答。不想搭话就保持沉默。）"})
    # a logic-guard regeneration passes a targeted correction (what broke last attempt)
    corr = prompt.get("logic_correction")
    if corr:
        messages.append({"role": "system", "content": corr})
    return messages


def _build_summary_system() -> str:
    """System prompt for the rolling memory digest. The model merges newly-elapsed turns
    into the running account, keeping established facts and staying concise."""
    return (
        "你在为一局互动剧情维护一份【故事备忘录】，用来在长剧情里保持前后一致的长程记忆。\n"
        "下面给你『已有备忘录』和『最近新发生的对话』。请把新发生的内容【合并】进备忘录，"
        "输出更新后的【完整】备忘录：\n"
        "- 已确立的事实绝不能丢失或篡改，除非新对话明确推翻了它；\n"
        "- 用简洁的要点记录：玩家是谁、做过/说过的关键事、已经查明的真相与线索、"
        "人物之间的关系与承诺、尚未解决的悬念；\n"
        "- 【尤其要记住情感线】：人物之间的情绪起伏与转折、谁对谁动了什么心思、"
        "说过的心里话、结下的情分或心结——这些是让角色'记得对方'、保持温度连贯的关键，不可丢；\n"
        "- 只记真正重要、对后续剧情有用的信息，闲聊和寒暄略去；\n"
        "- 控制在 450 字以内。只输出备忘录本身，不要任何解释或开场白。"
    )


def _qwen_chat(system: str, user: str, max_tokens: int = 700, temperature: float = 0.6) -> str:
    """One-shot qwen call returning text (or "" on failure). Shared by enrich helpers."""
    s = get_settings()
    if not s.dashscope_api_key:
        return ""
    try:
        resp = _post_chat(DASHSCOPE_URL, s.dashscope_api_key,
                          {"model": s.llm_model,
                           "messages": [{"role": "system", "content": system},
                                        {"role": "user", "content": user}],
                           "max_tokens": max_tokens, "temperature": temperature},
                          timeout=40, kind="enrich")
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return ""


DASHSCOPE_T2I_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"
DASHSCOPE_TASK_URL = "https://dashscope.aliyuncs.com/api/v1/tasks/"


DASHSCOPE_MM_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"


def edit_image(image_bytes: bytes, prompt: str, model: str = "qwen-image-edit",
               mime: str = "image/webp", timeout_s: int = 120) -> bytes | None:
    """Instruction-based image editing (qwen-image-edit): base image bytes in
    (Base64 data URI — DashScope 的审查器拉不动我们非 443 端口的 URL), edited
    image bytes out. 差分正解: expressions edit the 常态 base so body/framing
    stay pixel-consistent — fresh generations never were (实弹: 老师的眨眼帧
    连西装都换了一套). Returns None on any failure."""
    import base64
    s = get_settings()
    if not s.dashscope_api_key or not image_bytes:
        return None
    data_uri = f"data:{mime};base64," + base64.b64encode(image_bytes).decode()
    try:
        resp = httpx.post(
            DASHSCOPE_MM_URL,
            headers={"Authorization": f"Bearer {s.dashscope_api_key}",
                     "Content-Type": "application/json"},
            json={"model": model,
                  "input": {"messages": [{"role": "user", "content": [
                      {"image": data_uri}, {"text": prompt[:500]}]}]},
                  "parameters": {"watermark": False}},
            timeout=timeout_s,
        )
        resp.raise_for_status()
        content = (resp.json().get("output", {}).get("choices") or
                   [{}])[0].get("message", {}).get("content") or []
        url = next((c.get("image") for c in content
                    if isinstance(c, dict) and c.get("image")), None)
        if not url:
            return None
        img = httpx.get(url, timeout=60)
        img.raise_for_status()
        return img.content
    except Exception:
        return None


def generate_image(prompt: str, size: str = "1280*720",
                   model: str = "wanx2.1-t2i-turbo", timeout_s: int = 120,
                   seed: int | None = None, negative: str = "") -> bytes | None:
    """Text-to-image via DashScope 通义万相 (async): submit a task, poll until it finishes,
    then download the image bytes. Returns None on any failure. Runs OFFLINE (background
    enrichment), never in the play request path — generation takes ~10-30s per image."""
    import time

    s = get_settings()
    if not s.dashscope_api_key:
        return None
    auth = {"Authorization": f"Bearer {s.dashscope_api_key}"}
    try:
        sub = httpx.post(
            DASHSCOPE_T2I_URL,
            headers={**auth, "Content-Type": "application/json", "X-DashScope-Async": "enable"},
            json={"model": model,
                  "input": {"prompt": prompt[:780],
                            **({"negative_prompt": negative[:400]} if negative else {})},
                  # a FIXED seed + near-identical prompts = the same face across a
                  # character's four expression portraits (差分表已废: one-image-4-cells
                  # was a bet the image model kept losing — collage heads, fog busts)
                  "parameters": {"size": size, "n": 1,
                                 **({"seed": seed} if seed is not None else {})}},
            timeout=30,
        )
        sub.raise_for_status()
        task_id = sub.json()["output"]["task_id"]
    except Exception:
        return None
    img_url = None
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(3)
        try:
            r = httpx.get(DASHSCOPE_TASK_URL + task_id, headers=auth, timeout=30)
            r.raise_for_status()
            out = r.json().get("output", {})
            status = out.get("task_status")
            if status == "SUCCEEDED":
                results = out.get("results") or []
                if results and results[0].get("url"):
                    img_url = results[0]["url"]
                break
            if status in ("FAILED", "CANCELED", "UNKNOWN"):
                break
        except Exception:
            continue
    if not img_url:
        return None
    try:
        img = httpx.get(img_url, timeout=60)
        img.raise_for_status()
        return img.content
    except Exception:
        return None


def _tavily_search(query: str, max_results: int = 2) -> str:
    """Live web search via Tavily. Returns concatenated result snippets (or "")."""
    s = get_settings()
    if not s.tavily_api_key:
        return ""
    try:
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={"api_key": s.tavily_api_key, "query": query,
                  "max_results": max_results, "search_depth": "basic"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        parts = [r.get("content", "") for r in data.get("results", []) if r.get("content")]
        if data.get("answer"):
            parts.insert(0, data["answer"])
        return "\n".join(parts).strip()
    except Exception:
        return ""


def generate_knowledge(name: str, profile: str, world: str = "") -> str:
    """智能增强: build a structured background-lore block for a character.

    With a Tavily key: detect IP + generate dimensional queries → live web search → LLM
    synthesizes the real results into a structured block (the faithful persona 'enrich').
    Without Tavily: falls back to the model's own knowledge. Returns "" on any failure so
    enrich degrades gracefully.
    """
    s = get_settings()
    if not s.dashscope_api_key:
        return ""
    profile = (profile or "")[:600]
    combined = f"角色名：{name}\n角色设定：{profile}\n所在故事/世界：{(world or '')[:400]}"

    synth_fmt = (
        "整理成下面这种结构（每块 50~120 字，没有内容的块直接省略），只输出整理后的内容、不加解释：\n"
        "【人物设定】身份、能力、外貌、口癖等核心设定\n"
        "【世界背景】所处世界/时代的关键设定：地点、规则、氛围\n"
        "【人际关系】与重要人物的关系与互动特点\n"
        "【标志性细节】可自然融入对话的具体细节：物件、口头禅、习惯、事件\n"
        "【剧情素材】可推进故事的背景冲突、悬念或文化典故"
    )

    # ── path A: live web search (Tavily) → ground synthesis in real results ──
    if s.tavily_api_key:
        import json as _json
        import re as _re

        dim = _qwen_chat(
            "你在为互动小说的 AI 角色做资料搜集。判断该角色是否出自已知 IP（游戏/动漫/影视/小说等），"
            "再生成 4~5 条用于网络搜索的查询词：IP角色覆盖①官方设定/能力/口癖 ②世界观背景 ③人物关系 ④标志场景；"
            "原创角色覆盖①身份/职业的真实背景 ②时代/地域文化 ③性格行为特征 ④剧情相关历史社会背景。"
            '只输出 JSON：{"is_ip":true/false,"ip_name":"","queries":["...","..."]}',
            combined, max_tokens=200, temperature=0.3,
        )
        queries: list[str] = []
        if dim:
            try:
                d = _json.loads(_re.sub(r"^```(?:json)?\s*|\s*```$", "", dim.strip()))
                queries = [q.strip() for q in d.get("queries", []) if q.strip()][:5]
            except Exception:
                queries = [q.strip() for q in dim.replace("，", ",").split(",") if q.strip()][:4]
        raw = "\n\n".join(
            f"[{q}]\n{r}" for q in queries if (r := _tavily_search(q, 2))
        )[:4000]
        if raw.strip():
            out = _qwen_chat(
                f"你在为互动小说游戏的 AI 角色「{name}」整理【背景知识库】，供扮演时自然取用。"
                f"下面是从网络搜集的原始资料，请提炼成简洁、实用的结构化知识，剔除无关内容。\n" + synth_fmt,
                f"原始资料：\n{raw}", max_tokens=800,
            )
            if out:
                return out[:2500]
        # search yielded nothing usable → fall through to model-only

    # ── path B: model's own knowledge (no Tavily, or search empty) ──
    return _qwen_chat(
        "你在为一款互动小说游戏的 AI 角色整理【背景知识库】，供 AI 扮演时自然取用。\n"
        "先判断这个角色是否出自已知 IP（游戏/动漫/影视/小说等）：\n"
        "- 若是 IP 角色：依据该 IP 的设定整理；\n"
        "- 若是原创角色：依据其身份/职业/时代/世界观，补充真实可信的背景知识。\n" + synth_fmt,
        combined, max_tokens=700,
    )[:2500]


class QwenLLM:
    # endpoint / key / models — overridden by sibling providers (e.g. DeepSeekLLM). The
    # whole prompt-building + parsing pipeline above is provider-agnostic; only the chat
    # HTTP target differs, so an OpenAI-compatible provider just swaps these three.
    def __init__(self) -> None:
        s = get_settings()
        self._url = DASHSCOPE_URL
        self._key = s.dashscope_api_key
        self._model = s.llm_model
        self._summary_model = "qwen-turbo"  # cheap model for background memory compression

    def _summarize(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """Compress elapsed turns into the rolling digest (cheap model). Degrades to the
        prior digest on any failure — memory just doesn't advance that turn, never 500s."""
        prior = prompt.get("prior_memory") or ""
        lines = prompt.get("new_lines") or []
        convo = "\n".join(
            ("玩家：" if l.get("role") == "user" else "角色：") + (l.get("content") or "")
            for l in lines
        )
        user = f"== 已有备忘录 ==\n{prior or '（空，尚未建立）'}\n\n== 最近新发生的对话 ==\n{convo}"
        try:
            resp = _post_chat(self._url, self._key,
                              {
                    "model": self._summary_model,  # cheap model — background compression
                    "messages": [{"role": "system", "content": _build_summary_system()},
                                 {"role": "user", "content": user}],
                    "max_tokens": 600,
                    "temperature": 0.3,
                },
                              timeout=30)
            return {"memory": resp.json()["choices"][0]["message"]["content"].strip() or prior}
        except Exception:
            return {"memory": prior}

    def _gal_outline(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """✍️ B档: 梗概 → 章节大纲 (创作者确认后才拓写)."""
        n = prompt.get("n") or 4
        sys = ("你是视觉小说（galgame）策划。把创作者的想法拓成一部可玩的恋爱向"
               f"视觉小说的 {n} 章大纲，只输出严格JSON："
               '{"title":"≤12字书名","outline":["第1章一句话概要（≤60字）","…"]}。'
               "要求：起承转合完整；有明确的主角与感情对象；中段要有冲突或误会；"
               "最后一章收在结局分岔的高潮处；全部用简体中文。")
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model,
                               "messages": [{"role": "system", "content": sys},
                                            {"role": "user",
                                             "content": prompt.get("idea") or ""}],
                               "max_tokens": 900, "temperature": 0.7,
                               "response_format": {"type": "json_object"}},
                              timeout=60, kind="gal_outline")
            return _loads_lenient(resp.json()["choices"][0]["message"]["content"])
        except Exception:
            return {}

    def _gal_expand(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """✍️ B档: 按大纲逐章拓写正文 (只输出正文, 承接前文)."""
        i = prompt.get("index") or 1
        ol = prompt.get("outline") or []
        chtable = "\n".join(f"第{k + 1}章：{x}" for k, x in enumerate(ol))
        pt = (prompt.get("prior_tail") or "").strip()
        sys = ("你是小说家。按给定大纲写出【本章】的完整正文：简体中文，"
               "900~1500字，对话与描写并重，人物言行具体可感；"
               "只写本章大纲覆盖的剧情，收在能接下一章的地方；"
               "不写章节标题、不写任何说明，只输出正文本身。")
        _st = (prompt.get("style") or "").strip()
        if _st:
            sys += f"【文风·必须贴住】{_st}"
        sys += _STYLE_PUNCT
        u = (f"整体想法：{prompt.get('idea') or ''}\n全书大纲：\n{chtable}\n"
             + (f"前一章的结尾（紧接着往下写）：…{pt}\n" if pt else "")
             + f"现在写【第{i}章】：{ol[i - 1] if i - 1 < len(ol) else ''}")
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model,
                               "messages": [{"role": "system", "content": sys},
                                            {"role": "user", "content": u}],
                               "max_tokens": 3000, "temperature": 0.8},
                              timeout=180, kind="gal_expand")
            return {"text": (resp.json()["choices"][0]["message"]["content"] or "").strip()}
        except Exception:
            return {}

    def _gal_survey(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """✍️ C档: 问卷 → 梗概 (并入 B 流程)."""
        a = prompt.get("answers") or {}
        lines = "\n".join(f"{k}：{v}" for k, v in a.items() if str(v).strip())
        sys = ("根据创作者填的问卷，写一段 200~300 字的故事梗概：有名字的主角、"
               "有感情对象、有具体的冲突与走向、点出结局的分岔方向；"
               "简体中文，只输出梗概本身，不加任何说明。")
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model,
                               "messages": [{"role": "system", "content": sys},
                                            {"role": "user", "content": lines or "随便来一个"}],
                               "max_tokens": 600, "temperature": 0.9},
                              timeout=60, kind="gal_survey")
            return {"idea": (resp.json()["choices"][0]["message"]["content"] or "").strip()}
        except Exception:
            return {}

    def _gal_translate(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """🎀 转写拍: one chunk of a foreign-language source → faithful modern
        Chinese. Plain text out (no JSON); failure falls back to the original
        chunk — the compile-side language guard fails loudly downstream."""
        sys = ("你是文学翻译。把用户给的外语文学文本忠实转写成流畅的简体中文："
               "保留段落划分、叙述人称与语气，人名地名用通行的汉字写法，"
               "不加任何注释、标题或说明，只输出译文本身。")
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model,
                               "messages": [{"role": "system", "content": sys},
                                            {"role": "user",
                                             "content": (prompt.get("text") or "")[:6000]}],
                               "max_tokens": 6000, "temperature": 0.3},
                              timeout=180, kind="gal_translate")
            out = (resp.json()["choices"][0]["message"]["content"] or "").strip()
            return {"text": out or (prompt.get("text") or "")}
        except Exception:
            return {"text": prompt.get("text") or ""}

    def _gal_endings(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """🎀 结局编剧: the one true fork. The ENGINE decides which ending plays
        (affinity threshold, computed from the compiled choices); the model only
        writes two closures — the target route's good ending and the plain one."""
        chars = prompt.get("characters") or []
        scenes = prompt.get("scenes") or []
        ts = prompt.get("targets") or ([prompt["target"]] if prompt.get("target") else [])
        clist = "\n".join(f"- {c['id']}={c['name']}（{c.get('personality','')}）" for c in chars)
        slist = "\n".join(f"- {s['id']}={s['name']}" for s in scenes)
        want = "".join(f"【{t.get('name')}线好结局】char 填 {t.get('id')}，与{t.get('name')}"
                       "感情圆满的收束，8~14拍，有一拍情绪最高点标 cg:true；"
                       for t in ts)
        sys = (
            f"你是视觉小说（galgame）的结局编剧。为整个故事写 {len(ts) + 1} 个结局，"
            "只输出严格JSON："
            '{"endings":[{"char":"结局归属的角色id（普通结局留空字符串）","title":"≤10字结局名",'
            '"beats":[{"who":"说话角色id，旁白留空","text":"≤60字",'
            '"expr":"常态|喜|怒|哀","scene":"场景id",'
            '"bgm":"平静|温馨|浪漫|紧张|悲伤|寂寞|悬疑|激昂 之一","cg":false,"adult":false}]}]}。'
            + want +
            "【普通结局】char 留空，感情未满时怅然或平静地收束主线，6~12拍。"
            "每个结局都必须真正收束故事（回应主线的悬念，别开新钩子），"
            "不同感情线的结局要有各自的专属场面，不许互相换皮；"
            "主角旁白人称永远是「你」；只用给定的角色id和场景id；"
            "所有拍文字一律用简体中文（原文若是外语，转写成流畅的中文）。")
        _st = (prompt.get("style") or "").strip()
        if _st:
            sys += f"【文风·必须贴住】{_st}"
        sys += _STYLE_PUNCT
        sys += _gal_mature_rider(prompt)
        u = (f"角色表：\n{clist}\n场景表：\n{slist}\n"
             f"全书前情：{prompt.get('summary') or ''}\n"
             f"故事原文（收束依据）：\n{(prompt.get('source') or '')[:6000]}")
        _kn = (prompt.get("knowledge") or "").strip()
        if _kn:
            u = f"【背景设定·铁律】\n{_kn}\n\n" + u
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model,
                               "messages": [{"role": "system", "content": sys},
                                            {"role": "user", "content": u}],
                               "max_tokens": 4000, "temperature": 0.7,
                               "response_format": {"type": "json_object"}},
                              timeout=180, kind="gal_endings")
            import json as _json
            return _json.loads(resp.json()["choices"][0]["message"]["content"] or "{}")
        except Exception:
            return {}

    def _gal_parse(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """🎀 识别拍: story text → characters (with LOOKS for consistent art) / scenes /
        protagonist / chapter skeleton. One structured call; engine normalizes ids."""
        sys = (
            "你是视觉小说（galgame）制作器的识别器。读完用户给的故事文本，只输出严格JSON："
            '{"characters":[{"name":"","looks":"外貌描述：性别年龄/发型发色/眼睛/服装/体态，'
            '要具体到能让画师画出同一个人（≤80字）","personality":"≤40字","weight":1到5的戏份,'
            '"route":true或false（可攻略角色：玩家能与之发展感情线的对象；主角自己恒为false）}],'
            '"scenes":[{"name":"≤8字地点名","visual":"画面描述：空间/光线/陈设/氛围（≤80字）"}],'
            '"protagonist":"主角名（视角人物，玩家将扮演TA）",'
            '"style":"从原文归纳的文风卡（≤80字）：作者腔一句话＋三条忌清单，'
            '如「克制白描的乡土抒情。忌华丽辞藻；忌现代网络词；忌长句堆叠」",'
            '"chapters":[{"summary":"第1章一句话概要",'
            '"from":"该章在原文中起点处的前10~15个字，必须逐字照抄原文"}，…（3~5章）]}。'
            "要求：角色≤6个只留有戏份的；场景≤8个；looks 必须具体（画师依赖它）；"
            "至少标 1 个 route:true 的可攻略角色（与主角情感戏份最重的那个）；"
            "chapters 覆盖全书主线并收在临近结局分岔的高潮处：若原文包含多种结局走向"
            "（如果A…/如果B…），那些分支内容【不写进任何一章】——结局由专门的结局编译负责，"
            "不占章节。")
        u = f"标题：{prompt.get('title') or '（无）'}\n故事文本：\n{prompt.get('source') or ''}"
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model,
                               "messages": [{"role": "system", "content": sys},
                                            {"role": "user", "content": u}],
                               "max_tokens": 2200, "temperature": 0.3,
                               "response_format": {"type": "json_object"}},
                              timeout=90, kind="gal_parse")
            import json as _json
            return _json.loads(resp.json()["choices"][0]["message"]["content"] or "{}")
        except Exception:
            return {}

    def _gal_compile(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """🎀 编剧拍: one chapter → the beat sequence. The pacing CONTRACT lives here:
        每拍≤60字、一拍一个信息点、对白为主旁白为骨、主角人称永远是「你」。"""
        ch = prompt.get("chapter") or {}
        chars = prompt.get("characters") or []
        scenes = prompt.get("scenes") or []
        pro = prompt.get("protagonist_id") or ""
        lo, hi = prompt.get("target_beats") or (40, 60)
        clist = "\n".join(f"- {c['id']}={c['name']}（{c.get('personality','')}）"
                          + ("〔可攻略〕" if c.get("route") else "") for c in chars)
        slist = "\n".join(f"- {s['id']}={s['name']}" for s in scenes)
        sys = (
            "你是视觉小说（galgame）的编剧编译器。把指定章节改编成【简体中文】的拍序列"
            "（原文是外语也一律转写成流畅的现代中文），只输出严格JSON："
            '{"beats":[{"who":"说话角色id，旁白则留空","text":"这一拍的文字",'
            '"expr":"常态|喜|怒|哀（说话角色此刻表情）","scene":"场景id",'
            '"bgm":"平静|温馨|浪漫|紧张|悲伤|寂寞|悬疑|激昂|静 之一（跟着这一段的情绪走，'
            '亲密暧昧用浪漫，独处思念用寂寞，追查不安用悬疑；'
            '「静」=万籁俱寂，音乐骤停，只在最紧张或最重的一刻用）","cg":false,"adult":false,'
            '"weather":"仅当天气首次点明或发生变化时填：雪|雨|樱|晴 之一，其余拍留空",'
            '"date":"仅当这一拍发生时间跳跃（新的一天/几天后/时段大变）才填，'
            '如「二月十四日 放学后」，其余拍一律留空",'
            '"sfx":"仅当这一拍有明确的声音事件才填：雷鸣|雨声|风声|海浪|脚步|敲门|开门|'
            '吱呀|翻书|钟声|心跳|碎裂|爆炸|魔法|剑击|拳击|拔剑|交锋|硬币|铃声 之一，其余留空",'
            '"fx":"仅在剧情冲击的瞬间才填：震动|白闪|黑闪 之一（如巨响/顿悟/昏厥），其余留空"}],'
            '"choices":[{"after_text":"选择点插入处：它前面那一拍 text 的前10~15个字，逐字照抄",'
            '"options":[{"text":"≤20字，主角「你」此刻会说的话或会做的事",'
            '"fx":{"可攻略角色id":好感变化（-2到3的整数）},'
            '"flag":"该选项立下的事实标记（≤8字，如「送过巧克力」；无需要则留空）",'
            '"beats":[该选项的即时反应，2~6个与普通拍同构的分支拍]}]}],'
            '"summary":"本章≤100字收尾摘要（给下一章编译用）",'
            '"title":"≤8字章题（像小说目录那样的短题）",'
            '"lead":"≤24字过场引言：本章开场黑屏上的一句气口，定调不剧透",'
            '"date":"本章开始的日期与时段，如「一月十七日 放学后」（照故事内的时间线写）"}。'
            f"【节奏合同】beats 产出 {lo}~{hi} 拍；每拍≤60字、只装一个信息点；"
            "对白为主、旁白为骨（旁白连续不超过3拍）；场景切换要换 scene id；"
            f"主角（{pro}）是视角人物：旁白里永远称TA为「你」，主角自己的台词 who 填 {pro}；"
            "who 只在这一拍是角色亲口说出的台词时才填，叙述、动作、场景描写一律留空；"
            "关键的情绪画面拍（每章至多1拍）标 cg:true。"
            "【只写本章·铁律】故事原文是全书的素材，但你只改编属于本章的那一段剧情："
            "从前情摘要收尾的地方无缝接着往下演，第一拍就落在本章自己的时间与地点上；"
            "前面章节已经演过的事（开场、初遇、已发生的事件）绝不重述、绝不重新开场。"
            "【选择合同·硬性要求】choices 数组必须有 1~2 个选择点，缺了整章作废重来；"
            "after_text 必须逐字摘抄插入处前一拍的 text 开头（引擎按它定位，抄错整个"
            "选择就会落到错误的剧情点上），选在情感升温或抉择的那一拍"
            "（两个选择点之间至少隔12拍）。"
            "【选项要长在剧情上】每个选项必须直接回应 after 那一拍刚刚发生的具体事"
            "（TA刚说的那句话、刚做的那个动作、眼前的那个东西），玩家读到时一眼能看出"
            "「哦，这是在回应这件事」；2~3 个选项是三种真正不同的态度（如：迎上去/稳住/退一步），"
            "各自的分支后果要配得上态度的分量；禁止「握住她的手」「转移话题」「沉默微笑」"
            "这类放进任何场景都成立的万能模板——选项措辞必须包含此刻情境里的具体内容；"
            "fx 按选项的情感倾向给可攻略角色加减好感，至少一个选项给正分；"
            "选项的 beats 演完这个选项的即时反应后必须能无缝接回 after 那一拍之后的主线"
            "（就地收敛：分支里不换场景、不开新事件、不再嵌套选择点）。"
            "只用给定的角色id和场景id，不得发明新的。"
            "所有拍文字、选项、章题、引言一律用简体中文（原文若是外语，转写成流畅的中文，"
            "人名保留通行的汉字写法）。")
        _r = prompt.get("retry") or {}
        if _r.get("choices"):
            sys += ("【上一次的产出缺少了 choices 选择点，整章作废了。这一次 choices 数组"
                    "必须给出 1~2 个完整的选择点（含 after、2~3 个带 fx 和分支拍的选项），"
                    "这是本次任务的第一优先级。】")
        if _r.get("echo"):
            sys += ("【上一次的产出从头重述了前文已经演过的开场，整章作废了。这一次"
                    "绝不重复任何已发生的场面：第一拍直接落在本章自己的新时间、新事件上，"
                    "紧接前一章收尾之后往下演。】")
        if _r.get("lang"):
            sys += ("【上一次的产出用外语写了拍文字，整章作废了。所有 text 字段必须是"
                    "简体中文：把原文内容转写成流畅的现代中文再输出，这是硬性要求。】")
        chtable = "\n".join(f"- 第{c.get('i')}章：{c.get('summary')}"
                            for c in (prompt.get("chapters_all") or []))
        pt = (prompt.get("prev_tail") or "").strip()
        u = (f"角色表：\n{clist}\n场景表：\n{slist}\n"
             + (f"全书章节表（各章的地盘，绝不越界）：\n{chtable}\n" if chtable else "")
             + f"前情摘要（前面各章已经演完的部分）：{prompt.get('prior_summary') or '（这是第一章，从头开场）'}\n"
             + (f"前一章的收尾（铁律：本章第一拍必须发生在这之后，紧接着往下演，"
                f"绝不回头重演任何已发生的场面）：…{pt}\n" if pt else "")
             + f"你要编译的是【第{ch.get('i')}章/共{prompt.get('chapter_count')}章】：{ch.get('summary')}\n"
             f"本章的原文素材（只有这一段，把它演足演透，绝不写这段之外的剧情）：\n"
             f"{(prompt.get('source') or '')[:9000]}")
        _st = (prompt.get("style") or "").strip()
        if _st:
            sys += f"【文风·必须贴住】{_st}"
        _kn = (prompt.get("knowledge") or "").strip()
        if _kn:
            u = f"【背景设定·铁律，拍文字绝不能与之矛盾】\n{_kn}\n\n" + u
        sys += _STYLE_PUNCT
        sys += _gal_mature_rider(prompt)
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model,
                               "messages": [{"role": "system", "content": sys},
                                            {"role": "user", "content": u}],
                               "max_tokens": 8000, "temperature": 0.7,
                               "response_format": {"type": "json_object"}},
                              timeout=240, kind="gal_compile")
            return _loads_lenient(resp.json()["choices"][0]["message"]["content"])
        except Exception:
            return {}

    def _suggest(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """3 short, CONTEXT-aware "what could I do next" hints, drawn from what just happened
        + the current situation. Cheap call; degrades to {} so runtime can fall back."""
        ctx = prompt.get("sugg") or {}
        pc = (ctx.get("player_name") or "").strip()
        pc_desc = (ctx.get("player_desc") or "").strip()
        if (prompt.get("language") or "zh") == "en":
            # full English variant — an appended directive isn't reliable enough here
            # (the zh examples pull the model back to Chinese chips)
            who_en = (f"“{pc}” ({pc_desc})" if pc and pc_desc
                      else (f"“{pc}”" if pc else "the protagonist"))
            sys = (
                f"You write NEXT-ACTION suggestions for an interactive fiction game. "
                f"The player plays {who_en}. "
                "★Iron rule: every suggestion must be written FROM this character's own "
                "point of view and voice — a line they would say out loud, or an action "
                "they would take, in first person. Never an external instruction like "
                "'go ask about last night' — instead: “Where were you last night, really?” "
                "or “Let me take a closer look.” "
                "Output exactly 3 lines, one suggestion per line, no numbering, no "
                "explanations. ★Line 1 MUST push the player's own intent one step "
                "further — whatever their last line was driving at, line 1 serves that "
                "will (no detours, no cold water, no redirecting). Lines 2-3 then offer "
                "different directions (a new thread, a new action, a new place). "
                "Each must: follow directly from what was just said, be "
                "concrete and doable, fit this character's personality, and stay short "
                "(under a dozen words if possible). "
                "★Only reference the CURRENT place, people PRESENT right now, and exits "
                "you can actually take — never absent people or unseen things. "
                "Do not spoil hidden truths; point directions only. Write in English."
            )
            u = (
                f"You ({pc or 'the protagonist'}) are at: {ctx.get('place') or '(unknown)'}\n"
                f"You just said to {ctx.get('speaker','them')}: {ctx.get('player_input','')}\n"
                f"{ctx.get('speaker','They')} replied: {ctx.get('reply','')}\n"
                f"Present: {', '.join(ctx.get('present') or []) or 'just the two of you'}\n"
                f"Places you can go: {', '.join(ctx.get('exits') or []) or 'none'}\n"
                f"Still to untangle this chapter: {', '.join(ctx.get('topics') or []) or 'explore freely'}\n"
                f"Your relationship with {ctx.get('speaker','them')}: {ctx.get('relation','')}"
            )
        else:
            who = f"「{pc}」（{pc_desc}）" if pc and pc_desc else (f"「{pc}」" if pc else "你扮演的主角")
            sys = (
                f"你在为一个互动剧情游戏生成【下一步行动建议】。玩家扮演的是 {who}。"
                "★铁律：每一条建议都必须站在玩家扮演的这个角色的视角、用这个角色的身份和口吻写——"
                "是这个角色接下来会亲口说的一句话、或会亲手做的一个动作，用第一人称（我…）。"
                "绝不能写成旁观者、系统或别的角色对主角发出的外部指令。"
                "对比：外部命令口吻“去问对方昨晚的事”“上前查看”是错的；"
                "主角亲口/亲手的“你昨晚究竟去了哪？”“让我走近看看”才是对的。"
                "只输出 3 条，每行一条，不要编号、不要解释。"
                "★第1条必须【顺着玩家的意志走】：玩家刚才那句话在推什么、要什么，第1条就是把这件事再往前推一步的说法或做法——服务玩家的意图，不转弯、不泼冷水、不改道。"
                "若资料里写了玩家【当前的目标】或【正要去见的人】，第1条永远直接服务它；"
                "玩家的问题若没得到正面回答，第1条就是把同一个问题逼得更紧。"
                "第2、3条再给不同方向的可能性（新话头、新动作、新去处）。"
                "每条都要：紧扣刚发生的对话与此刻处境、"
                "具体可操作、贴合这个角色的性格与说话方式、尽量精炼（十来个字最好，最多一句话说完）。"
                "★建议只能落在【当前地点、此刻在场的人、可去的地方】上——绝不要提任何不在场的人、"
                "不在眼前的东西。不要剧透隐藏真相，只点方向。"
                + ("★这是视觉小说的选项，玩家将【直接点击执行】：三条要成为三种真正不同的"
                   "走法——顺意图推进、换一个切入、以及一个大胆的/有代价的/会改变局面的选择"
                   "（仍然是角色口吻）。" if ctx.get("vn") else "")
            )
            u = (
                f"你（{pc or '主角'}）此刻在：{ctx.get('place') or '（未知地点）'}\n"
                f"你刚才对{ctx.get('speaker','对方')}说：{ctx.get('player_input','')}\n"
                f"这一拍的收尾（最后发生的事，第1条建议要接住它）：{ctx.get('reply','')}\n"
                f"此刻在场：{ '、'.join(ctx.get('present') or []) or '只有你'}\n"
                f"可以去的地方：{ '、'.join(ctx.get('exits') or []) or '暂无'}\n"
                f"这一章你还想弄清：{ '、'.join(ctx.get('topics') or []) or '随你探索'}\n"
                f"你和{ctx.get('speaker','对方')}此刻的关系：{ctx.get('relation','普通')}"
                + (f"\n你当前的目标：{ctx['goal']}" if ctx.get("goal") else "")
                + (f"\n你正要去见的人：{ctx['pursuit']}" if ctx.get("pursuit") else "")
            )
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": u}], "max_tokens": 160, "temperature": 0.8},
                              timeout=20)
            txt = resp.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            return {"suggestions": []}
        import re
        out = []
        for ln in txt.splitlines():
            ln = re.sub(r"^\s*[-*\d.、。)）]+\s*", "", ln).strip().strip("「」\"'")
            if not ln:
                continue
            # the FULL sentence survives — the UI truncates display only, and clicking a
            # chip pastes the whole line. Safety cap only for runaway generations.
            if len(ln) > 120:
                cut = max((ln.rfind(p, 40, 120) for p in "？！。?!…，,"), default=-1)
                ln = ln[:cut + 1] if cut >= 40 else ln[:120] + "…"
            out.append(ln)
        return {"suggestions": out[:3]}

    def _describe_place(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """Concrete, people-free description for an EMERGENT location (a place that came up in
        play and the player agreed to go to). Grounds it in the world + where they came from."""
        name = (prompt.get("place_name") or "").strip()
        world = (prompt.get("world") or "").replace("\n", " ")[:400]
        frm = (prompt.get("from_place") or "").strip()
        sys = ("你在为一个互动剧情游戏即时生成一个新地点。输出两行：\n"
               "第一行：把玩家的原话提炼成一个干净的【地名】（2~8字，只留地点本体，"
               "去掉动作、目的和语气，如「铁皮顶那屋摸个底」→「铁皮顶屋」、"
               "「去后巷看看情况」→「后巷」；原话本身已是干净地名就照抄）。\n"
               "第二行：这个地点的环境描写：只写此刻实际能看到的具体陈设、光线、声响、气味，"
               "30~60字，一段话，第三人称、有画面感、贴合世界观；画面里不要出现任何人物，"
               "不要台词，不要解释或标题。" + _lang_rule(prompt))
        u = f"世界观：{world or '（未知）'}\n玩家的原话：{name}\n玩家刚从「{frm or '别处'}」走过来。\n输出两行。"
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": u}], "max_tokens": 220, "temperature": 0.85},
                              timeout=25)
            txt = (resp.json()["choices"][0]["message"]["content"] or "").strip()
            lines = [l.strip().strip("「」\"'") for l in txt.splitlines() if l.strip()]
            clean = lines[0][:12] if lines else ""
            detail = " ".join(lines[1:]).strip() if len(lines) > 1 else ""
            if not detail:      # model collapsed to one line — treat it as the detail
                clean, detail = "", lines[0] if lines else ""
            return {"name": clean, "detail": detail}
        except Exception:
            return {"detail": ""}

    def _risk(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """🎲 risk judge: how likely is this player action to succeed here (0~100)?
        100 = mundane, no dice needed. Tiny call — a single integer out."""
        action = (prompt.get("action") or "")[:200]
        place = (prompt.get("place") or "")[:60]
        world = (prompt.get("world_facts") or "").replace("\n", " ")[:200]
        powers = "；".join(str(p) for p in (prompt.get("powers") or []) if str(p).strip())
        sys = ("你是动作难度裁判。给玩家这个动作在此情境下的成功概率打分，只输出一个0~100的整数，"
               "不要任何其他文字。日常、无风险、必然做得到的动作=100；有点难度或代价=60~90；"
               "很悬=30~59；近乎不可能=1~29。判断现实可行性，不考虑剧情需要。"
               + (f"玩家拥有真实生效的超能力：{powers}。动用这些能力的动作按能力范围内评估"
                  "（范围内=大概率成，范围外才按常人算）。" if powers else ""))
        u = f"情境：{place}。{world}\n玩家动作：{action}\n成功概率（0~100）："
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": u}], "max_tokens": 8, "temperature": 0.0},
                              timeout=15)
            import re
            m = re.search(r"\d+", resp.json()["choices"][0]["message"]["content"] or "")
            return {"risk": max(0, min(100, int(m.group()))) if m else 100}
        except Exception:
            return {"risk": 100}

    def _opening_hook(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """✨ 首局魔法时刻: the lead notices the player (one concrete stroke), visibly
        withholds something (keyed to a secret TITLE only), then speaks one line straight
        at them. Two labeled lines out; degrades to {} → deterministic fallback."""
        ch = prompt.get("char") or {}
        pl = prompt.get("player_name") or "对方"
        pr = prompt.get("player_role") or ""
        tease = (prompt.get("tease") or "").strip()
        tease_line = (f"这丝破绽与「{tease}」有关，但你绝不能说破任何内容——只许让人察觉你有所保留。"
                      if tease else "让人察觉你有所保留即可。")
        sys = (f"你是「{ch.get('name','')}」（{ch.get('role','')}）。人设：{ch.get('persona_text','')}\n"
               f"表达方式：{ch.get('eq_style','')}\n"
               f"故事开场：{pl}（{pr}）刚出现在{prompt.get('place','这里')}。只输出两行：\n"
               f"旁白：一句第三人称——你注意到{pl}的那个瞬间（一个具体的动作/眼神变化），"
               f"并露出一丝【有话没说】的破绽。{tease_line}\n"
               f"台词：你对{pl}亲口说的第一句话（短，直接冲着TA本人来，一眼就是你的口吻——"
               "让TA感觉被点名、被看见，而不是被客套地接待）。两行都不要用破折号。"
               + _lang_rule(prompt))
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": "输出那两行："}], "max_tokens": 140,
                      "temperature": 0.9},
                              timeout=20)
            txt = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            return {}
        narration = line = ""
        for ln in txt.splitlines():
            s = ln.strip()
            body = s.split("：", 1)[-1].split(":", 1)[-1].strip()
            if s.startswith("旁白"):
                narration = body
            elif s.startswith("台词"):
                line = body
        return {"narration": narration, "line": line}

    def _offscreen(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """🌆 幕后戏: two NPCs had a moment while the player was elsewhere. Output = a
        stance direction + ONE line of neighborhood-gossip rumor. Degrades to {}."""
        a, b = prompt.get("a") or {}, prompt.get("b") or {}
        ga = (a.get("goal") or "").strip()
        gb = (b.get("goal") or "").strip()
        sys = ("你在为互动剧情游戏生成一段【玩家不在场时】两个角色之间发生的小事，"
               "并把它压成一句会在街坊嘴里流传的传闻。\n"
               f"甲：{a.get('name','')}（{a.get('role','')}）{a.get('persona','')}"
               + (f"　TA正想办成的事：{ga}" if ga else "") + "\n"
               f"乙：{b.get('name','')}（{b.get('role','')}）{b.get('persona','')}"
               + (f"　TA正想办成的事：{gb}" if gb else "") + "\n"
               f"两人的交情：{prompt.get('stance','')}；事发地：{prompt.get('place','')}\n"
               + ("这件小事要顺着某一方正想办成的事往前推半步（办成一点、受个挫、或牵出新麻烦），"
                  "不要凭空编无关的闲事。\n" if (ga or gb) else "")
               + "只输出两行：\n变化：近 或 僵 或 无（这件事让两人关系更近/闹僵/没变化）\n"
               "传闻：一句话（30字内，像闲话——谁听见谁看见了什么，具体、有画面，不用破折号）"
               + _lang_rule(prompt))
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": "输出那两行："}], "max_tokens": 80,
                      "temperature": 0.95},
                              timeout=20)
            txt = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            return {}
        delta, rumor = 0, ""
        for ln in txt.splitlines():
            t = ln.strip()
            body = t.split("：", 1)[-1].split(":", 1)[-1].strip()
            if t.startswith("变化"):
                delta = 1 if "近" in body else -1 if "僵" in body else 0
            elif t.startswith("传闻"):
                rumor = body
        return {"delta": delta, "rumor": rumor} if rumor else {}

    def _farewell(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """One short in-voice goodbye line for a character whose 作息 is pulling them
        away — may name where they're headed, may leave a hook. Degrades to {}."""
        ch = prompt.get("char") or {}
        dest = (prompt.get("dest") or "").strip()
        where = f"你正要离开{prompt.get('place','这里')}" + (f"，去{dest}那边" if dest else "")
        sys = (f"你是「{ch.get('name','')}」（{ch.get('role','')}）。人设：{ch.get('persona_text','')}\n"
               f"表达方式：{ch.get('eq_style','')}\n"
               f"{where}。对在场的人说一句【告辞的话】——短（15字内），一眼就是你的声音："
               "可以交代去处、可以留个钩子（回头见/有事来找我）、也可以只一声招呼。"
               "只输出这句话本身，不要引号、不要旁白。" + _lang_rule(prompt))
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": "你的告辞："}], "max_tokens": 40, "temperature": 0.9},
                              timeout=15)
            line = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            return {}
        return {"line": line.splitlines()[0][:60]} if line else {}

    def _compose_msg(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """📱 an ABSENT character reaches out (promise reminder / stood-up hurt / afterglow).
        1~2 short bubbles, unmistakably in their voice. Degrades to {} → deterministic text."""
        ch = prompt.get("char") or {}
        device = prompt.get("device") or "手机"
        tail = "\n".join(f"{'对方' if m.get('from') == 'me' else ch.get('name','你')}：{m.get('text','')}"
                         for m in (prompt.get("thread_tail") or [])) or "（这是你们第一次这样捎话）"
        sys = (f"你是「{ch.get('name','')}」（{ch.get('role','')}）。人设：{ch.get('persona_text','')}\n"
               f"表达方式：{ch.get('eq_style','')}\n"
               + (("你的台词范例（语气分寸以此为准，不照抄）：'"
                   + "' / '".join(ch["examples"]) + "'\n") if ch.get("examples") else "")
               + f"你与对方的关系：{prompt.get('relation','')}。\n"
               f"你此刻不在对方身边，要通过{device}给TA捎话。情境：{prompt.get('hint','')}\n"
               "写1~2条【短消息】：每条一行、口语、短（20字内最好），必须一眼就是你的声音——"
               "你的口头禅、你的脾气、你的分寸。不要旁白、不要引号、不要署名，只输出消息本身。不用破折号。"
               + _lang_rule(prompt))
        u = f"你们之前捎过的话：\n{tail}\n\n现在写你要发的消息（1~2行）："
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": u}], "max_tokens": 90, "temperature": 0.9},
                              timeout=20)
            txt = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            return {}
        msgs = [l.strip().strip("「」\"'") for l in txt.splitlines() if l.strip()][:2]
        return {"msgs": msgs} if msgs else {}

    def _phone_reply(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """📱 the player texted (or 📞 CALLED) this character. Answer in voice under the
        SAME gate as a scene turn (locked truths can't leak over the line either) — or
        leave them on read (msgs=[]). A probe that just cracked a layer (new_reveal)
        must be voiced. Calls add one line of what's audible down the line (ambient)."""
        ch = prompt.get("char") or {}
        device = prompt.get("device") or "手机"
        call = bool(prompt.get("call"))
        ctx = prompt.get("context") or {}
        reveal = ctx.get("reveal") or []
        new_reveal = ctx.get("new_reveal") or []
        has_hidden = bool(ctx.get("has_hidden"))
        pl = prompt.get("player_name") or "对方"
        tail = "\n".join(f"{pl if m.get('from') == 'me' else ch.get('name','')}：{m.get('text','')}"
                         for m in (prompt.get("thread_tail") or []))
        sys_lines = [
            f"你是「{ch.get('name','')}」（{ch.get('role','')}）。人设：{ch.get('persona_text','')}",
            f"表达方式：{ch.get('eq_style','')}",
            ("你的台词范例（语气分寸以此为准，不照抄）：'" + "' / '".join(ch["examples"]) + "'")
            if ch.get("examples") else "",
            f"你自己的盘算：{ch.get('agenda','')}" if ch.get("agenda") else "",
            f"你与{pl}的关系：{prompt.get('relation','')}。{prompt.get('relationship_playbook','')}",
            (f"你相处下来对{pl}的印象：{prompt.get('player_read','')}"
             if prompt.get("player_read") else ""),
            f"你们此前的经历（你的记忆）：{(prompt.get('memory') or '')[:400]}" if prompt.get("memory") else "",
            (f"最离谱的是：TA此刻就和你在【同一个地方】，人就在几步开外，却用{device}给你发消息。"
             "先就着这件事本身回应——按你的性格来：好笑、无语、抬头瞪TA一眼、或干脆凑趣配合。"
             "一句『我人不就在这儿？』式的吐槽很自然；想当面说的话就叫TA过来说。"
             if prompt.get("same_room") else
             f"TA不在你身边，此刻正通过{device}和你【实时通话】。你听得到TA的呼吸和背景音，"
             "TA也听得到你的。你说出来的是口语，一句一句，可以停顿、可以叹气、可以突然沉默。"
             if call else
             f"TA不在你身边，是通过{device}给你捎话。你在忙你自己的事，回不回、回多少、什么语气，"
             "全凭你此刻的心情和你们的关系。"),
            ("【通话铁律】对方【看不见】你：挑眉、摆手、扬下巴这些一概不存在，绝不写任何动作神态、"
             "绝不用（括号）描述自己；能被听见的动静（火柴声、风声、你把东西放下）只写进「背景」那一行。"
             if call else
             "【短信体铁律】你发的是消息，不是小说：对方只看得到字，看不见你——绝不写动作、神态、"
             "场景描写，绝不用（括号）写你在做什么。像真人打字：每条短（20字内为佳），"
             "想说的多就拆成两三条连发；可以省略主语、可以带语气词，但绝不要台词腔的长句。"),
            "【铁律】你只能基于下面列出的「可透露信息」谈及内情；此外的任何秘密你都不知道，绝不能写出来——"
            "被追问就回避、岔开，或干脆不回。" if (reveal or new_reveal or has_hidden) else "",
            ("【TA这句话问到了要害，你守不住了——把下面这个实情，用你自己的话、你此刻的情绪说出来"
             "（这是你第一次对TA松口）】" + "；".join((r.get("content") or "")[:80]
                                                    for r in new_reveal[:2])) if new_reveal else "",
            ("【你对外的统一口径（假话，别偏离）】" + "；".join(
                f"关于「{c.get('secret_title','')}」：{c.get('content','')}"
                for c in (ctx.get("covers") or [])[:3]))
            if (ctx.get("covers") and not new_reveal) else "",
            ("【你已经告诉过TA的】" + "；".join((r.get("content") or "")[:60] for r in reveal[:4])) if reveal else "",
            ("输出格式：写1~3行你说出口的话（口语，短句）。另起一行写：背景：你那头此刻传过去的"
             "声响或动静，10~20字（环境音、你的动作声，不含你的台词）。如果你不想接这个话，"
             "可以只说一两个字，或输出【沉默】表示你握着听筒没出声。"
             if call else
             "输出格式：写0~3条短消息，每条一行（口语，短，像真的在发消息；可以只回一个字，也可以连发两三条）。"
             "如果你此刻不想回（心情/性格/在气头上），就只输出：【已读】"),
        ]
        sys = "\n".join(l for l in sys_lines if l) + _lang_rule(prompt)
        judgeline = ("最后另起一行，写：好感：一个整数-2~2（这几句话让你对TA更近还是更远）；"
                     "心动：一个整数-1~2（仅当TA的话让你心里一动）。")
        if not prompt.get("same_room"):
            judgeline += ("再各起一行，写：赴约：是 或 否（仅当TA在消息里叫你【马上过去见TA】、"
                          "且你按此刻的心情和你们的关系确实愿意动身才写 是；犹豫、敷衍、"
                          "改天再说都算 否）；应承：若TA托你办一件【具体的事】且你应下了，"
                          "用15字内写下这件事本身（如 盯着王九的动静），没应承就写 无；"
                          "约定：若这几条消息定下了一个【将来的会面】（约在之后的某个时段见，"
                          "不是马上动身），按 做什么|几天后|时段|地点 写（几天后填0/1/2，"
                          "时段填 晨/午/夜，地点没提就留空），如 看画|1|晨|后巷天台；没定就写 无。")
        u = ((f"你们此前的往来：\n{tail}\n\n（电话接通了，TA刚说了最后那句。）你开口说什么？\n"
              if call else
              f"你们的消息记录：\n{tail}\n\n（TA刚发来最后那条。）你现在回什么？\n")
             + judgeline)
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": u}], "max_tokens": 240, "temperature": 0.9},
                              timeout=25)
            txt = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            return {"msgs": [], "closeness": 0, "romance": 0}
        import re as _re
        dc = dr = 0
        msgs: list[str] = []
        ambient = ""
        coming = False
        task = ""
        promise: dict[str, Any] | None = None
        for ln in txt.splitlines():
            s = ln.strip()
            if not s:
                continue
            if s.startswith("好感"):
                m = _re.search(r"-?\d+", s)
                dc = max(-2, min(2, int(m.group()))) if m else 0
            elif s.startswith("心动"):
                m = _re.search(r"-?\d+", s)
                dr = max(-1, min(2, int(m.group()))) if m else 0
            elif s.startswith("背景"):
                ambient = s.split("：", 1)[-1].split(":", 1)[-1].strip().strip("（）()")[:60]
            elif s.startswith("赴约"):
                coming = "是" in s.split("：", 1)[-1]
            elif s.startswith("应承"):
                body = s.split("：", 1)[-1].split(":", 1)[-1].strip()
                if body and not body.startswith("无"):
                    task = body[:20]
            elif s.startswith("约定"):
                body = s.split("：", 1)[-1].split(":", 1)[-1].strip()
                if body and not body.startswith("无"):
                    parts = [p.strip() for p in body.split("|")]
                    try:
                        promise = {"what": parts[0][:20],
                                   "day_offset": max(0, min(2, int(parts[1]))) if len(parts) > 1 else 0,
                                   "slot": parts[2] if len(parts) > 2 else "",
                                   "place": parts[3] if len(parts) > 3 else ""}
                    except (ValueError, IndexError):
                        promise = None
            elif ("已读" in s or "沉默" in s) and len(s) <= 6:
                msgs = []
                break
            else:
                # 短信体强制: stage directions can't ride a text message — strip any
                # （动作神态）chunks; a line that was ONLY narration disappears entirely
                s = _re.sub(r"[（(][^）)]*[）)]", "", s).strip()
                if s:
                    msgs.append(s.strip("「」\"'")[:120])
        out: dict[str, Any] = {"msgs": msgs[:3], "closeness": dc, "romance": dr,
                               "coming": coming, "task": task, "promise": promise}
        if call:
            out["ambient"] = ambient
        return out

    def _compose_letter(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """📮 a real LETTER in this character's hand (love letter / long-absence letter).
        Longer than a text, unmistakably them. Degrades to {} → deterministic fallback."""
        ch = prompt.get("char") or {}
        sys = (f"你是「{ch.get('name','')}」（{ch.get('role','')}）。人设：{ch.get('persona_text','')}\n"
               f"表达方式：{ch.get('eq_style','')}\n"
               + (("你的台词范例（语气分寸以此为准，不照抄）：'"
                   + "' / '".join(ch["examples"]) + "'\n") if ch.get("examples") else "")
               + f"你与收信人的关系：{prompt.get('relation','')}。\n"
               f"你们此前的经历（你的记忆）：{(prompt.get('memory') or '')[:400]}\n"
               f"情境：{prompt.get('hint','')}\n"
               "写一封【信】：第一行是信的标题（≤12字，像你会写的，不要「无题」）；"
               "空一行后是正文，120~250字，第二人称写给TA。要具体，写到你们之间真实发生过的事、"
               "你当时没说出口的心思；落款是你的名字。忌空泛抒情、忌套话。不用破折号。"
               + _lang_rule(prompt))
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": "写这封信（第一行标题，空行，正文）："}],
                      "max_tokens": 420, "temperature": 0.9},
                              timeout=30)
            txt = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            return {}
        lines = txt.splitlines()
        head = next((l.strip().strip("《》「」#* ") for l in lines if l.strip()), "")
        first_i = next((i for i, l in enumerate(lines) if l.strip()), 0)
        body = "\n".join(lines[first_i + 1:]).strip()
        return {"subject": head[:24], "body": body[:800]} if body else {}

    def _golden(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """✨ 稀有奇遇: a rare golden moment with the closest character — one cinematic
        flash the scene didn't owe the player. Degrades to {} (the drop simply doesn't
        fire this turn; the engine keeps the roll for another day)."""
        ch = prompt.get("char") or {}
        said = "\n".join(f"{s.get('speaker','')}：{s.get('text','')}"
                         for s in (prompt.get("said_this_turn") or [])) or "（刚才没有对话）"
        sys = ("你在为互动剧情游戏写一段【金色瞬间】，罕见的、玩家没有预期的一小段奇遇演出，"
               f"主角是「{ch.get('name','')}」（{ch.get('role','')}；人设：{ch.get('persona_text','')}）"
               f"与玩家。你们的关系：{prompt.get('relation','')}。\n"
               "写两行：第一行是这个瞬间的名字（4~10字，像回忆相册里的标题）；"
               "第二行是这个瞬间本身，60~120字：一个突然到来的、值得记一辈子的小片段，"
               "可以是TA罕见的失态或温柔、一次心照不宣的对视、一件只给你看的东西、一句压了很久的话。"
               "必须扣住此时此地与TA的性格，具体可感，不许出现任何秘密或未揭露的剧情。不用破折号。"
               + ("（本局为成人向，允许更亲密的肢体细节，但这一段以心动为主。）"
                  if prompt.get("mature") else "") + _lang_rule(prompt))
        u = (f"地点：{prompt.get('place','') or '（未知）'}；时间：{prompt.get('clock','') or '不明'}\n"
             f"刚才的对话：\n{said}\n\n写这个金色瞬间（两行）：")
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": u}], "max_tokens": 220, "temperature": 0.95},
                              timeout=25)
            txt = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            return {}
        lines = [l.strip().strip("《》「」#* ") for l in txt.splitlines() if l.strip()]
        if not lines:
            return {}
        title = lines[0][:16]
        text = " ".join(lines[1:]).strip()
        if not text:  # single-line output → treat it all as the moment itself
            title, text = "", lines[0]
        return {"title": title, "text": text[:200]}

    def _arrive(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """到达旁白: the player just walked into a place. One vivid pan (2~4 sentences):
        the space itself first, then what each person present is DOING right now, and who
        notices the player first. Degrades to {} so runtime assembles a deterministic one."""
        people = prompt.get("people") or []
        plist = "\n".join(
            f"- {p.get('name','')}（{p.get('role','')}；与玩家的关系：{p.get('relation','')}）：{p.get('look','')}"
            for p in people) or "（这里此刻没有别人）"
        if prompt.get("observer"):
            sys = ("你在为互动剧情游戏写【无形旁观视角切到一个地方】的到达旁白。写2~4句，第三人称：\n"
                   "① 先写一眼看到的空间——光线、声响、气味，必须扣住给出的地点细节，不要泛泛；\n"
                   "② 再写此刻在场的每个人【正在做什么】——具体的动作、姿态、注意力所在，一人一笔。\n"
                   "这是一位看不见的观众在换机位：场景里【没有任何人到来】，绝不能有人抬头、察觉、"
                   "感到被注视或对空气说话。不要剧透，不要总结抒情。只输出旁白本身。"
                   + _STYLE_PUNCT + _lang_rule(prompt))
            u = (f"地点：{prompt.get('place','')}（{prompt.get('detail','')}）\n"
                 f"时间：{prompt.get('slot','') or '不明'}\n"
                 f"此刻在场：\n{plist}")
        else:
            sys = ("你在为互动剧情游戏写【玩家刚走进一个地方】的到达旁白。写2~4句，第三人称：\n"
                   "① 先写一眼看到的空间——光线、声响、气味，必须扣住给出的地点细节，不要泛泛；\n"
                   "② 再写此刻在场的每个人【正在做什么】——具体的动作、姿态、注意力所在，贴合各自的身份和长相，"
                   "一人一笔，谁都不能只是'站在那里'；\n"
                   "③ 最后写谁最先注意到玩家进来、那一瞬的反应（一个眼神/动作即可，不写对话）。\n"
                   "不要替玩家做动作或说话，不要剧透，不要总结抒情。只输出旁白本身。"
                   + _STYLE_PUNCT + _lang_rule(prompt))
            u = (f"地点：{prompt.get('place','')}（{prompt.get('detail','')}）\n"
                 f"时间：{prompt.get('slot','') or '不明'}\n"
                 f"走进来的人：{prompt.get('player_name') or '玩家'}\n"
                 f"此刻在场：\n{plist}")
        # 🎬 原画: the pan ALSO returns one keyframe per person, so the ledger opens the
        # scene with every body's state on record (the cold-start fix for 说/看打架)
        sys += (
            '\n同时输出严格JSON：{"text":"上面的旁白原文","frames":[{"name":"在场角色名",'
            '"frame":"≤16字：TA此刻的姿态/位置/手上的事"}]}，frames 覆盖在场每一个人。')
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": u}], "max_tokens": 420, "temperature": 0.9,
                      "response_format": {"type": "json_object"}},
                              timeout=25)
            import json as _json
            data = _json.loads(resp.json()["choices"][0]["message"]["content"] or "{}")
            txt = str(data.get("text") or "").strip()
            frames = [{"name": str((f or {}).get("name") or "").strip(),
                       "frame": str((f or {}).get("frame") or "").strip()}
                      for f in (data.get("frames") or []) if isinstance(f, dict)]
        except Exception:
            txt, frames = "", []
        if not txt:
            return {}
        return {"beats": [{"type": "description", "speaker_name": None, "text": txt}],
                "frames": frames,
                "affinity_delta": 0, "advance_act": False, "ending": None}

    def _world_news(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """🌊 one line of the world's OWN news for a day the player missed. Grounded in
        the worldview / cast / standing facts; degrades to {} (no news that day)."""
        wv = (prompt.get("worldview") or "").strip()
        cast = "、".join(prompt.get("cast") or []) or "（尚无具名人物）"
        facts = "；".join(prompt.get("facts") or []) or "（无）"
        recent = "；".join(prompt.get("recent") or []) or "（无）"
        sys = ("你为一个持续运转的沙盒世界生成【昨天发生的一件事】。只输出JSON："
               '{"text":"≤40字的一件具体的事"}。'
               "要求：贴世界观、贴在场人物的处境，可以是变故/风波/买卖/传言坐实；"
               "要具体可谈（谁、哪里、什么事），不要抒情空话；不得与已发生的事实矛盾，也别重复近闻。")
        u = f"世界观：{wv}\n城中人物：{cast}\n既成事实：{facts}\n近几天已发生：{recent}"
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model,
                      "messages": [{"role": "system", "content": sys},
                                   {"role": "user", "content": u}],
                      "max_tokens": 120, "temperature": 0.95,
                      "response_format": {"type": "json_object"}},
                              timeout=25)
            import json as _json
            data = _json.loads(resp.json()["choices"][0]["message"]["content"] or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _absent_scene(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """🌍 缺席因果: the scene that happened WITHOUT the player — they stood this
        character up, and the world keeps the receipt. Degrades to {} (deterministic
        line backstops it in living.py)."""
        ch = prompt.get("char") or {}
        sys = ("你为一个持续运转的世界写【玩家缺席的那场戏】：角色如约赴了约，玩家没来。"
               '只输出JSON：{"scene":"≤80字，第三人称，一件具体发生了的事"}。'
               "要求：写角色真实做了什么（等了多久、做了什么小动作、最后怎么离开、顺手发生了什么），"
               "贴人设与关系；克制，不哭喊不控诉，细节越具体越疼；不要对白引号堆砌；不用破折号。")
        u = (f"角色：{ch.get('name','')}（{ch.get('role','')}）。人设：{ch.get('persona_text','')}\n"
             f"与玩家的关系：{prompt.get('relation','')}\n"
             f"约定：{prompt.get('when','')}，{prompt.get('what','')}\n"
             f"世界背景：{prompt.get('world','')}")
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model,
                       "messages": [{"role": "system", "content": sys},
                                    {"role": "user", "content": u}],
                       "max_tokens": 160, "temperature": 0.9,
                       "response_format": {"type": "json_object"}},
                              timeout=25)
            import json as _json
            data = _json.loads(resp.json()["choices"][0]["message"]["content"] or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _player_profile(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """🪞 玩家档案蒸馏: 近期对话 → 玩家习惯 facts + 每个在场角色眼中的印象.
        见证名单由引擎给定, 只许更新名单内的角色. Degrades to {} (下轮再蒸)."""
        wit = prompt.get("witnesses") or []
        prior = prompt.get("prior") or {}
        sys = ("你为一个长线运转的游戏维护【玩家画像】。只输出JSON："
               '{"facts":["玩家的习惯/偏好/雷点，每条≤18字，最多6条"],'
               '"impressions":{"角色ID":"该角色相处出来对玩家的印象，≤28字，口语"}}。'
               "要求：facts 写行为规律（爱莽/谨慎/嘴硬/吃软不吃硬/常深夜上线这类），"
               "不写剧情事件；impressions 只能写给定名单里的角色，各写各的视角，"
               "允许与旧印象矛盾（人会改观）；没有新东西的角色可以不写；不用破折号。")
        u = (f"旧画像：{prior}\n"
             f"在场角色名单：{[(w.get('id'), w.get('name')) for w in wit]}\n"
             "近期对话（旧→新）：\n" + "\n".join(str(x) for x in prompt.get("recent") or []))
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model,
                               "messages": [{"role": "system", "content": sys},
                                            {"role": "user", "content": u}],
                               "max_tokens": 300, "temperature": 0.6,
                               "response_format": {"type": "json_object"}},
                              timeout=10)   # 蒸馏在回合关键路径上, 慢了宁可这轮不蒸 (审查实锤)
            import json as _json
            data = _json.loads(resp.json()["choices"][0]["message"]["content"] or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _living_event(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """🌍 世界心跳: this character PROPOSES a dated meeting (the world moves first,
        恋与深空-style). Engine already picked who; the model writes what/when/invite.
        Degrades to {} (deterministic invite backstops)."""
        ch = prompt.get("char") or {}
        sys = ("你为一个持续运转的世界生成【角色主动发起的约】。只输出JSON："
               '{"what":"≤16字的具体事由","slot":"晨|午|夜","day_offset":1,'
               '"invite":"≤40字，TA发给玩家的邀约短信，必须是TA的口吻"}。'
               "要求：事由从人设、关系与世界近况里自然长出来（不要泛泛的散步吃饭，除非贴人设）；"
               "day_offset 只能是1或2；短信口语、有性格、不解释背景；不用破折号。")
        u = (f"角色：{ch.get('name','')}（{ch.get('role','')}）。人设：{ch.get('persona_text','')}\n"
             f"与玩家的关系：{prompt.get('relation','')}\n"
             f"TA相处出来对玩家的印象：{prompt.get('impression') or '（还不深）'}\n"
             f"玩家的习惯：{'；'.join(prompt.get('player_facts') or []) or '（未知）'}\n"
             f"世界观：{prompt.get('worldview','')}\n"
             f"世界近况：{'；'.join(prompt.get('recent_news') or []) or '（无）'}")
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model,
                       "messages": [{"role": "system", "content": sys},
                                    {"role": "user", "content": u}],
                       "max_tokens": 160, "temperature": 0.95,
                       "response_format": {"type": "json_object"}},
                              timeout=25)
            import json as _json
            data = _json.loads(resp.json()["choices"][0]["message"]["content"] or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _sandbox_cast(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """🏖 conjure the sandbox's opening cast from the player's worldview. Strict
        JSON; degrades to {} (runtime seeds a deterministic stranger instead)."""
        wv = (prompt.get("worldview") or "").strip() or "一个由玩家亲手定义的世界。"
        sys = ("你为一个玩家自定义世界观的无尽沙盒剧情设计【开场人物】。只输出一个JSON对象，形如"
               ' {"characters":[{"name":"名字","role":"身份(≤12字)","persona":"外貌、性格与说话方式(≤80字)",'
               '"items":["随身物件名|一句细节"]}]}'
               "，共2~3人。要求：人物必须从这个世界观里自然长出来（职业、立场、欲望各不相同），"
               "至少一人与玩家的到来直接相关；名字要贴合世界观的语感；"
               "每人配1~2件贴身份的随身物件（它们会成为世界里可送、可换、可被抢的实体）。"
               + ("本局为成人向（18+，玩家已成年）：persona 里的外貌一笔要立得住身材与气质的张力，"
                  "写出让人多看一眼的具体理由（身形、线条、气场），不低俗、不清单式。"
                  if prompt.get("mature") else "")
               + "不要旁白，不要解释。")
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model,
                      "messages": [{"role": "system", "content": sys},
                                   {"role": "user", "content": f"世界观：{wv}"}],
                      "max_tokens": 420, "temperature": 0.9,
                      "response_format": {"type": "json_object"}},
                              timeout=30)
            import json as _json
            data = _json.loads(resp.json()["choices"][0]["message"]["content"] or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _gen_progression(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """🌱 开局立法: derive THIS worldview's power ladder (每个世界一套符合世界观的
        升级系统). Strict JSON; degrades to {} (the run simply has no ladder)."""
        world = (prompt.get("world") or "").strip()
        title = (prompt.get("title") or "").strip()
        sys = ("你为一个互动剧情游戏的世界观设计【成长/升级体系】。只输出JSON："
               '{"name":"这套体系衡量什么(2~6字，如:斗气/魂力/灵能/剑道/声望/军衔)",'
               '"ranks":["从最低到最高的6~10个阶位名，每个≤6字"]}。'
               "要求：阶位名必须贴合这个世界观的语感与题材（修仙用境界、军旅用军衔、"
               "都市异能用等级、朝堂用品级），从弱到强排列，读起来像这个世界原生的东西；"
               "不要解释，不要重复世界观原文。")
        u = f"世界观标题：{title}" + chr(10) + f"世界观：{world}"
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model,
                               "messages": [{"role": "system", "content": sys},
                                            {"role": "user", "content": u}],
                               "max_tokens": 220, "temperature": 0.7,
                               "response_format": {"type": "json_object"}},
                              timeout=20)
            import json as _json
            data = _json.loads(resp.json()["choices"][0]["message"]["content"] or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _track_scene(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """🎥 场记 (turn-end tracker pass): EXTRACT every present body's state from the
        prose that was just generated — the ledger follows the text instead of hoping
        the text's author files paperwork. Also flags hard contradictions against the
        previous frame. Strict JSON; degrades to {} (ledger keeps last frames)."""
        prev = prompt.get("present") or []
        plist = chr(10).join(f"- {x.get('name', '')}（上一帧：{x.get('prev') or '无记录'}）" for x in prev) or "（无）"
        pl = prompt.get("player") or {}
        en = (prompt.get("language") or "zh") == "en"
        sys = (
            "你是剧组场记。根据【本轮正文】更新场上每个人的状态帧。只输出JSON："
            '{"frames":[{"name":"角色名(原样抄写)","pos":"姿态与屋内位置(≤14字)",'
            '"doing":"手上的事(≤10字,可空)","wear":"衣着(≤10字,仅正文提到才填)"}],'
            '"player":{"pos":"...","doing":"...","wear":"..."},'
            '"contradictions":["正文与上一帧的硬矛盾(无过渡的位置/姿态/衣着跳变),没有则空数组"]，"progressed":"本轮剧情是否有具体的事向前发生了(新事件/新决定/局面实变，单纯气氛加强或重复警告不算)，true或false","hanging":"≤16字：当前悬而未决的最大钩子(如：古镜异动将醒)，没有则空字符串"}。'
            "规则：只记录正文明确写到或可直接推断的状态；正文没提到的人，把上一帧原样抄回来；"
            "wear 只在正文出现衣着信息时才填；不要发明正文里没有的细节；"
            "只记名单里列出的具名角色：名单之外的路人、龙套、无名氏一律不记、不输出。"
            + ("Respond with the SAME JSON schema but write values in English." if en else "")
        )
        u = (f"地点：{prompt.get('place') or '（未知）'}" + chr(10)
             + f"在场名单与上一帧：" + chr(10) + plist + chr(10)
             + f"玩家：{pl.get('name') or '玩家'}（上一帧：{pl.get('prev') or '无记录'}）" + chr(10)
             + f"【本轮正文】{prompt.get('beats') or ''}")
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model,
                               "messages": [{"role": "system", "content": sys},
                                            {"role": "user", "content": u}],
                               "max_tokens": 400, "temperature": 0.2,
                               "response_format": {"type": "json_object"}},
                              timeout=18)
            import json as _json
            data = _json.loads(resp.json()["choices"][0]["message"]["content"] or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _fate_choice(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """⚖️ 命运抉择: draft ONE high-stakes decision grounded in the live scene. Strict
        JSON with TYPED options the engine can enforce (kill / move / story). Degrades to
        {} — the turn simply carries no choice this time."""
        cast = "、".join(prompt.get("cast") or []) or "（无）"
        place = (prompt.get("place") or "").strip() or "（未知）"
        exits = "、".join(prompt.get("exits") or []) or "（无）"
        goal = (prompt.get("goal") or "").strip()
        recent = (prompt.get("recent") or "").strip() or "（无）"
        en = (prompt.get("language") or "zh") == "en"
        god = bool(prompt.get("observer"))
        _pcn = (prompt.get("player_name") or "").strip()
        _who = f"玩家（扮演「{_pcn}」）" if _pcn else "玩家"
        label_style = ("上帝视角的一道天命决断(≤20字，如「让某人死于今晚」「命他们即刻动身」)"
                       if god else f"{_who}第一人称的一句话或一个决断(≤20字)，"
                       "口吻与立场必须是这个角色本人")
        sys = (
            "你为一个互动剧情游戏设计一次【命运抉择】：此刻剧情里悬而未决、分量最重的那个岔路口。"
            + ("玩家是俯瞰这一切的无形命运，抉择是TA拨动世界的手。" if god else
               f"【人称铁律】抉择永远摆在玩家「{_pcn or '玩家'}」本人面前：prompt 里的「你」"
               f"只指玩家；每个选项都必须是玩家自己此刻能亲口说出/亲手做出的决定，"
               "绝不能写成任何其他角色的视角、决定或内心活动。")
            + '只输出一个JSON对象：{"prompt":"摆在玩家面前的抉择(≤40字，紧贴眼下正在发生的事)",'
            f'"options":[{{"label":"选项({label_style})",'
            '"kind":"story|kill|move|bond|rift|identity|fortune|timeskip",'
            '"target":"kill/bond/rift填在场角色名；move填地点名；identity填新身份(≤10字)；'
            'fortune填「横财」或「破财」；timeskip填「次日」或「三日后」；story留空",'
            '"omen":"≤8字的代价预兆，只暗示不剧透（如：此路见血/有去无回/代价不菲）",'
            '"mandate":"选它之后剧情必须坚定走向的方向(≤30字)"}]}。'
            "kind 释义：kill=角色就此死去；bond=与此人关系骤然绑深；rift=与此人恩断义绝；"
            "identity=玩家身份就此改变；fortune=财运剧变；timeskip=时间直接跳过；"
            "story=纯剧情走向。按剧情自然选用，不要硬凑类型。"
            "要求：2~3个选项，方向必须彼此相斥（不是同一件事的三种语气）；"
            "至少一个选项要有真实代价；kind=kill 只在剧情确实走到生死关头时才用，"
            "target 只能原样抄写在场角色名；kind=move 的 target 优先用已知通路里的地点名；"
            "不许出现与眼下剧情无关的凭空事件。"
            + ("本局为成人向沙盒，抉择可以大胆、狠辣。" if prompt.get("mature") else "")
            + ("Write all player-facing text (prompt/label/mandate) in English."
               if en else "")
        )
        u = (f"当前地点：{place}\n可去通路：{exits}\n在场角色：{cast}\n"
             f"玩家当前目标：{goal or '（无）'}\n刚刚正在发生（抉择必须直接从这里长出来，禁止无关事件）：{recent}")
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model,
                               "messages": [{"role": "system", "content": sys},
                                            {"role": "user", "content": u}],
                               "max_tokens": 380, "temperature": 0.9,
                               "response_format": {"type": "json_object"}},
                              timeout=30)
            import json as _json
            data = _json.loads(resp.json()["choices"][0]["message"]["content"] or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _parting(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """悬念离场: ONE cliffhanger narration when the player leaves mid-run — an unfinished
        beat that pulls them back. Spoiler-safe: may point at a topic LABEL, never content."""
        cast = "、".join(prompt.get("cast") or []) or "有人"
        place = prompt.get("place") or ""
        topics = [t for t in (prompt.get("topics") or []) if t]
        tline = f"可以点到「{topics[0]}」这个话头（只许提名字，绝不许透露内容），" if topics else ""
        wf = (prompt.get("world") or "").strip().replace(chr(10), " ")[:140]
        stl = (prompt.get("style") or "").strip().split("。", 1)[0][:40]
        sys = ("你在为一个互动剧情游戏写【玩家暂时放下这一刻】的定格旁白。写1~2句，"
               "用第二人称：「你」永远只指玩家本人；在场其他人一律称名字，绝不要用无名的"
               "「有人」「他」去指代任何人。【铁律】玩家人在原地、姿势不变，绝不要替玩家"
               "做任何动作（不许写你转身/你起身/你离开/你迈步这类）；写的是现场悬着的那口气："
               "在场的某个具名者欲言又止、一个反常的细节此刻才被注意到、"
               f"或一句没说完的话。{tline}要具体可感，不要总结、不要抒情空话、不要预告。"
               "所有物件与细节必须属于这个世界观，绝不能出现不属于它的现代物品。"
               + (f"【世界观】{wf}" if wf else "")
               + (f"【文风】{stl}。" if stl else "")
               + "只输出旁白本身。" + _STYLE_PUNCT + _lang_rule(prompt))
        u = (f"地点：{place or '（未知）'}" + chr(10)
             + f"在场的人：{cast}" + chr(10)
             + "玩家此刻起身离开。写那1~2句收尾旁白。")
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": u}], "max_tokens": 160, "temperature": 0.9},
                              timeout=25)
            txt = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            txt = ""
        if not txt:
            hint = f"关于「{topics[0]}」的话" if topics else "有句话"
            who = (prompt.get("cast") or ["有人"])[0]
            txt = f"（你起身离开。身后{who}欲言又止，{hint}似乎还没说完。）"
        return {"beats": [{"type": "description", "speaker_name": None, "text": txt}],
                "affinity_delta": 0, "advance_act": False, "ending": None}

    def _start_place(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """The OPENING location for a story that authored no map — so every run has a place to
        stand and can grow a map from there. Returns {name, detail} derived from world + act 1."""
        world = (prompt.get("world") or "").replace("\n", " ")[:400]
        setting = (prompt.get("setting") or "").replace("\n", " ")[:300]
        sys = ("你在为一个互动剧情游戏确定【开场所在地】。根据世界观和开场情节，给出玩家一开始身处的"
               "具体地点。只输出两行：第一行是这个地点的名字（4~12字，具体，如「末班地铁车厢」「城郊废弃教堂」）；"
               "第二行是30~50字的环境描写（此刻能看到的陈设、光线、声响、气味，第三人称，不要出现人物或台词）。"
               "不要解释、不要编号、不要多余的行。" + _lang_rule(prompt))
        u = f"世界观：{world or '（未知）'}\n开场情节：{setting or '（未知）'}\n输出开场地点（两行）。"
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": u}], "max_tokens": 160, "temperature": 0.8},
                              timeout=25)
            txt = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            return {"name": "", "detail": ""}
        import re
        lines = [re.sub(r"^\s*[-*\d.、。)）：:]+\s*", "", l).strip().strip("「」\"'")
                 for l in txt.splitlines() if l.strip()]
        name = lines[0][:16] if lines else ""
        detail = " ".join(lines[1:])[:120] if len(lines) > 1 else ""
        return {"name": name, "detail": detail}

    def plan_and_render(self, prompt: dict[str, Any]):
        """两拍合同 (docs/plan-render.md)。拍1 plan_turn：函数调用，只裁决＋出分镜，低温快包；
        拍2 render：照分镜写纯散文，stream=true 逐 token 流出。渲染拍不产生任何状态，所以
        它不可能弄脏状态。Yields ("token", str) while prose streams, then ("final", directed)
        — directed 的形状与 generate() 返回完全一致，settle 级联零改动。
        任何一拍整体失败都回退旧单拍合同：flag 打开永远不会比旧路径更糟，只会更快。
        目前仅服务 zh 剧本的角色回合（en 的引号切分器与旁白路径仍走旧拍）。"""
        import json
        speaker = prompt.get("speaker_name") or "角色"
        channel = prompt.get("channel") or "say"
        group_mode = prompt.get("group_mode")
        nt = prompt.get("next_act_title")
        advance_hint = (f"本幕目标已达成、可进入下一幕《{nt}》时填 true，否则 false" if nt
                        else "本章已是最后一章，填 false")
        system = _build_system(prompt) + _lang_rule(prompt)
        messages = _turn_messages(prompt, system, speaker)

        # ── 拍1 · 导演：落实场面 → 分镜 → 结算裁决（整包，但小而快） ──
        plan: dict[str, Any] | None = None
        outline: list[str] = []
        try:
            body_p = {"model": self._model, "messages": messages,
                      "max_tokens": 500, "temperature": 0.4,
                      "tools": [_plan_tool(prompt, speaker, bool(prompt.get("observer")),
                                           group_mode, channel, advance_hint)],
                      "tool_choice": {"type": "function",
                                      "function": {"name": "plan_turn"}}}
            resp = _post_chat(self._url, self._key, body_p, timeout=30, kind="plan")
            msg = resp.json()["choices"][0]["message"]
            tool_calls = msg.get("tool_calls") or []
            if tool_calls:
                args = ((tool_calls[0] or {}).get("function") or {}).get("arguments")
                plan = _parse_tool_args(args, speaker, channel, group_mode)
                try:
                    raw = json.loads(args or "{}")
                    outline = [str(x).strip() for x in (raw.get("outline") or [])
                               if str(x).strip()][:4]
                except Exception:
                    outline = []
        except Exception:
            plan = None
        if plan is None:
            yield ("final", self.generate(prompt))
            return

        # ── 拍2 · 演员：照分镜写正文，逐 token 流出 ──
        body_r = {"model": self._model,
                  "messages": messages + [{"role": "system",
                                           "content": _render_directive(prompt, speaker,
                                                                        outline)}],
                  "max_tokens": 900 if prompt.get("mature") else 600,
                  "temperature": 0.85, "presence_penalty": 0.3}
        if prompt.get("mature"):
            body_r["frequency_penalty"] = 0.3
        parts: list[str] = []
        # line-protocol splitter: each line declares 旁白：/名字：, so the client pours
        # speech into a NAMED bubble from its first character (旁白与台词分家) and a
        # spoken line physically cannot hide inside narration.
        seg = _LineSegmenter(speaker)
        # a member's render is speech-only: narration it sneaks in gets dropped at parse,
        # so those tokens must not reach the player either (draft和正文不许分家)
        member = group_mode == "member"
        try:
            for delta in _post_chat_stream(self._url, self._key, body_r,
                                           timeout=60, kind="render"):
                parts.append(delta)
                for k2, who, t2 in seg.feed(delta):
                    if member and k2 != "speech":
                        continue
                    yield ("token", {"kind": k2, "speaker": who or speaker, "text": t2})
            for k2, who, t2 in seg.flush():
                if not (member and k2 != "speech"):
                    yield ("token", {"kind": k2, "speaker": who or speaker, "text": t2})
        except Exception:
            pass  # broke mid-stream → parse what arrived; nothing at all → fallback below
        text = "".join(parts).strip()
        if group_mode == "member" and text.strip("。！!（）() ") in ("无", "-", ""):
            plan["beats"] = []          # a member choosing silence is a VALID render
            yield ("final", plan)
            return
        beats = (_parse_line_beats(text)
                 or (_parse_reply(text, speaker, channel, group_mode).get("beats") or [])) \
            if text else []
        if group_mode == "member":
            dlg = [b for b in beats if b.get("type") == "dialogue"
                   and (b.get("text") or "").strip("。！!（）() ") not in ("无", "")]
            if not dlg:
                # the member narrated their own line (弯引号/旁白行 dodge) — salvage the
                # quoted words as their dialogue instead of losing them to the filter
                import re as _re
                spans = [_re.sub(r"[（(][^）)]*[）)]", "", sp).strip()
                         for sp in _re.findall(r"[「“]([^」”]{2,80})[」”]", text)]
                dlg = [{"type": "dialogue", "speaker_name": speaker, "text": sp}
                       for sp in spans[:2] if sp]
            plan["beats"] = dlg         # empty = silence, still a valid member render
            yield ("final", plan)
            return
        if not beats:
            yield ("final", self.generate(prompt))
            return
        plan["beats"] = beats
        ending = plan.get("ending")
        if isinstance(ending, dict) and not str(ending.get("reason") or "").strip():
            ending["reason"] = text[:200]  # the plan judged it before the prose existed
        yield ("final", plan)

    def _scout(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """🔎 角色检索 (the seek contract, Yi 2026-07-08): does the sought NAME belong in
        this story's world? Grounded in live web search when Tavily is configured (canon
        characters of adapted IPs get found), model knowledge otherwise. Returns
        {fits, who, where, persona} — runtime.mint_sought_character consumes it."""
        import json as _json
        name = str(prompt.get("scout_char") or "").strip()
        title = str(prompt.get("story_title") or "").strip()
        world = str(prompt.get("world") or "").replace("\n", " ")[:600]
        cast = "、".join([str(c) for c in (prompt.get("cast") or []) if c][:12])
        web = _tavily_search(f"{title} {name} 人物 角色", max_results=2)
        sys = ("你在为一个互动剧情游戏做【角色检索】。判断玩家要找的名字是否属于这个故事的"
               "世界观：原著/原型作品里的人物算；这个世界观下合理存在的普通人也算；"
               "明显来自别的作品、或与世界观格格不入的不算。只输出一个 JSON 对象，"
               '不要任何其他文字，键：{"fits": true或false, "who": "TA的身份一句话(20字内)", '
               '"where": "TA此刻最可能出现的【一个】具体地点名(4~10字，如 天台画室；'
               '只给一个，绝不用「或」并列)", '
               '"persona": "两三句人设：性格、说话方式、与这个世界的关系"}。'
               "fits 为 false 时其余键都给空字符串。" + _lang_rule(prompt))
        u = (f"故事：《{title}》\n世界观：{world or '（未知）'}\n已有角色：{cast or '（无）'}\n"
             + (f"网上检索到的资料：\n{web[:800]}\n" if web else "")
             + f"玩家要找的人：「{name}」")
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model,
                               "messages": [{"role": "system", "content": sys},
                                            {"role": "user", "content": u}],
                               "max_tokens": 320, "temperature": 0.3},
                              timeout=25, kind="scout")
            txt = (resp.json()["choices"][0]["message"]["content"] or "").strip()
            d = _json.loads(txt[txt.find("{"):txt.rfind("}") + 1])
            return {"fits": bool(d.get("fits")),
                    "who": str(d.get("who") or "").strip()[:30],
                    "where": str(d.get("where") or "").strip()[:12],
                    "persona": str(d.get("persona") or "").strip()[:220]}
        except Exception:
            return {}

    def narrate_stream(self, prompt: dict[str, Any]):
        """Streamed twin of the narration-only paths (observe/想/intro/transition):
        plain prose, zero judgments, yielded as narration tokens then ONE description
        beat. Any failure falls back to the generate() shape — never worse, only live."""
        speaker = prompt.get("speaker_name") or "角色"
        system = (_build_intro_system(prompt) if prompt.get("intro") else
                  _build_transition_system(prompt) if prompt.get("transition") else
                  _build_observe_system(prompt)) + _lang_rule(prompt)
        messages = _turn_messages(prompt, system, speaker)
        body = {"model": self._model, "messages": messages,
                "max_tokens": 600, "temperature": 0.85, "presence_penalty": 0.3}
        parts: list[str] = []
        try:
            for delta in _post_chat_stream(self._url, self._key, body,
                                           timeout=60, kind="render"):
                parts.append(delta)
                yield ("token", {"kind": "narration", "text": delta})
        except Exception:
            pass
        text = "".join(parts).strip()
        if not text:
            yield ("final", self.generate(prompt))
            return
        yield ("final", {"beats": [{"type": "description", "speaker_name": None,
                                    "text": text}],
                         "affinity_delta": 0, "advance_act": False, "ending": None})

    def _gen_attrs(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """🎯 玩家五维 (力量/敏捷/体质/心思/气运 1~10): judged once from who the player
        IS in this world. Feeds the dice DC deterministically — stats with teeth."""
        import re as _re
        who = str(prompt.get("who") or "")[:300]
        powers = "、".join(str(p) for p in (prompt.get("powers") or []))[:120]
        sys = ("你在为一个互动剧情游戏给玩家角色定五维属性，各1~10（5=普通人平均）。"
               "按TA的出身、体格、经历定，别都给高分；有短板才像人。只输出一行，格式："
               "力量:N 敏捷:N 体质:N 心思:N 气运:N" + _lang_rule(prompt))
        u = f"玩家角色：{who or '（普通人）'}" + (f"\n自带能力：{powers}" if powers else "") + "\n输出那一行。"
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": u}], "max_tokens": 60, "temperature": 0.6},
                              timeout=20, kind="aux")
            txt = (resp.json()["choices"][0]["message"]["content"] or "")
        except Exception:
            return {}
        out = {}
        for k in ("力量", "敏捷", "体质", "心思", "气运"):
            m = _re.search(k + r"\s*[:：]\s*(\d+)", txt)
            if m:
                out[k] = max(1, min(10, int(m.group(1))))
        return {"attrs": out} if len(out) == 5 else {}

    def _rank_judge(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """⚡ NPC 境界+身家: where does THIS character sit on the story's power ladder,
        and roughly how much money do they carry? Judged once, cached in state."""
        import re as _re
        ranks = [str(r) for r in (prompt.get("ranks") or [])]
        ch = prompt.get("char") or {}
        cur = str(prompt.get("currency") or "钱")
        base = int(prompt.get("base_money") or 50)
        known = "、".join(str(n) for n in (prompt.get("known_names") or []) if n)[:80]
        sys = ("你在为互动剧情游戏裁定一个角色的实力位阶、随身财物，和一桩藏在心里的暗线。"
               f"位阶阶梯（从低到高）：{'、'.join(ranks)}。"
               f"按TA的身份年资定位阶（普通市井角色通常在低档，宿老/高手才靠上）；"
               f"随身的钱按身份定（一个普通人身上约{base}{cur}）。"
               "暗线：TA心里对某个人藏着一桩没人知道的事（暗恋/旧怨/亏欠/嫉妒/握着把柄/旧情），"
               + (f"对象从这些人里选：{known}；" if known else "对象可以是玩家；")
               + "选最贴TA人设的那种，一句话写透缘由。只输出两行，格式：\n"
               "位阶:<阶梯里的原词> 身家:<整数>\n"
               "暗线:对<名字>的<暗恋|旧怨|亏欠|嫉妒|把柄|旧情>——<一句话缘由，25字内>"
               + _lang_rule(prompt))
        u = f"角色：{ch.get('name','')}（{ch.get('role','')}）{str(ch.get('persona_text') or '')[:160]}\n输出那两行。"
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": u}], "max_tokens": 50, "temperature": 0.5},
                              timeout=20, kind="aux")
            txt = (resp.json()["choices"][0]["message"]["content"] or "")
        except Exception:
            return {}
        rank_i = None
        for i, r in enumerate(ranks):
            if r and r in txt:
                rank_i = i
        m = _re.search(r"身家\s*[:：]\s*(\d+)", txt)
        money = int(m.group(1)) if m else None
        out: dict[str, Any] = {}
        if rank_i is not None:
            out["rank_i"] = rank_i
        if money is not None:
            out["money"] = max(0, min(999999, money))
        ms = _re.search(r"暗线\s*[:：]\s*(.{4,60})", txt)
        if ms:
            out["secret"] = ms.group(1).strip()[:60]
        return out

    def _gen_market(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """🛒 今日集市: 6 world-true goods with prices scaled to the story's economy."""
        world = str(prompt.get("world") or "").replace("\n", " ")[:400]
        cur = str(prompt.get("currency") or "钱")
        base = int(prompt.get("base_money") or 50)
        sys = ("你在为互动剧情游戏生成【今日集市】的货单：6件贴合世界观、玩家买得着用得上的"
               "东西（吃食/工具/药物/消息/小物件，至少一件便宜一件贵）。"
               f"货币是{cur}，一个普通人身上约有{base}{cur}，定价要合这个身价。"
               "只输出6行，每行格式：名称|价格整数|一句话（≤20字，它是什么/有什么用）"
               + _lang_rule(prompt))
        u = f"世界观：{world or '（市井）'}\n输出6行货单。"
        try:
            resp = _post_chat(self._url, self._key,
                              {"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": u}], "max_tokens": 260, "temperature": 0.9},
                              timeout=25, kind="aux")
            txt = (resp.json()["choices"][0]["message"]["content"] or "")
        except Exception:
            return {}
        items = []
        for ln in txt.splitlines():
            parts = [p.strip() for p in ln.strip().split("|")]
            if len(parts) >= 2:
                try:
                    price = max(1, int("".join(ch for ch in parts[1] if ch.isdigit())))
                except ValueError:
                    continue
                items.append({"name": parts[0].strip("「」·- 0123456789.")[:16], "price": price,
                              "detail": (parts[2] if len(parts) > 2 else "")[:30]})
        return {"items": items[:6]} if items else {}

    def generate(self, prompt: dict[str, Any]) -> dict[str, Any]:
        if prompt.get("summarize"):
            return self._summarize(prompt)
        if prompt.get("scout_char"):
            return self._scout(prompt)
        if prompt.get("gen_attrs"):
            return self._gen_attrs(prompt)
        if prompt.get("rank_judge"):
            return self._rank_judge(prompt)
        if prompt.get("gen_market"):
            return self._gen_market(prompt)
        if prompt.get("suggest"):
            return self._suggest(prompt)
        if prompt.get("describe_place"):
            return self._describe_place(prompt)
        if prompt.get("start_place"):
            return self._start_place(prompt)
        if prompt.get("sandbox_cast"):
            return self._sandbox_cast(prompt)
        if prompt.get("fate_choice"):
            return self._fate_choice(prompt)
        if prompt.get("track_scene"):
            return self._track_scene(prompt)
        if prompt.get("gen_progression"):
            return self._gen_progression(prompt)
        if prompt.get("world_news"):
            return self._world_news(prompt)
        if prompt.get("absent_scene"):
            return self._absent_scene(prompt)
        if prompt.get("player_profile"):
            return self._player_profile(prompt)
        if prompt.get("living_event"):
            return self._living_event(prompt)
        if prompt.get("parting"):
            return self._parting(prompt)
        if prompt.get("arrive"):
            return self._arrive(prompt)
        if prompt.get("compose_msg"):
            return self._compose_msg(prompt)
        if prompt.get("compose_letter"):
            return self._compose_letter(prompt)
        if prompt.get("phone_reply"):
            return self._phone_reply(prompt)
        if prompt.get("golden_moment"):
            return self._golden(prompt)
        if prompt.get("farewell"):
            return self._farewell(prompt)
        if prompt.get("opening_hook"):
            return self._opening_hook(prompt)
        if prompt.get("offscreen"):
            return self._offscreen(prompt)
        if prompt.get("risk_judge"):
            return self._risk(prompt)
        if prompt.get("gal_parse"):
            return self._gal_parse(prompt)
        if prompt.get("gal_compile"):
            return self._gal_compile(prompt)
        if prompt.get("gal_endings"):
            return self._gal_endings(prompt)
        if prompt.get("gal_translate"):
            return self._gal_translate(prompt)
        if prompt.get("gal_outline"):
            return self._gal_outline(prompt)
        if prompt.get("gal_expand"):
            return self._gal_expand(prompt)
        if prompt.get("gal_survey"):
            return self._gal_survey(prompt)
        speaker = prompt.get("speaker_name") or "角色"
        channel = prompt.get("channel") or "say"
        observe = bool(prompt.get("observe"))
        intro = bool(prompt.get("intro"))
        transition = bool(prompt.get("transition"))
        narrate = observe or intro or transition  # narration-only, description beat(s)
        system = (_build_intro_system(prompt) if intro else
                  _build_transition_system(prompt) if transition else
                  _build_observe_system(prompt) if observe else _build_system(prompt))
        system += _lang_rule(prompt)  # 🌐 en story → perform in English
        messages = _turn_messages(prompt, system, speaker)

        body = {
            "model": self._model,
            "messages": messages,
            # mature runs get headroom: an intimate beat written properly needs more
            # room than a plot beat, and a mid-scene truncation reads as a fade-out
            "max_tokens": 900 if prompt.get("mature") else 600,
            "temperature": 0.85,
            "presence_penalty": 0.3,
        }
        if prompt.get("mature"):
            # 词穷循环是烂肉戏的第一死因: sampling-level pressure against reusing the
            # same 颤抖/呻吟 tokens, paired with the 【笔法】same-word-once prompt rule
            body["frequency_penalty"] = 0.3
        # CHARACTER turns use FUNCTION CALLING (render_turn): narration & speech go into
        # separate tool args → the model physically can't merge them. This is the definitive
        # fix for "台词/旁白混在一起" (marker/json/prose all had failure modes). Narration-only
        # turns (observe/intro/transition) stay plain prose.
        group_mode = prompt.get("group_mode")
        if not narrate:
            nt = prompt.get("next_act_title")
            advance_hint = (f"本幕目标已达成、可进入下一幕《{nt}》时填 true，否则 false" if nt
                            else "本章已是最后一章，填 false")
            body["tools"] = [_render_tool(prompt, speaker, observe, group_mode, channel, advance_hint)]
            body["tool_choice"] = {"type": "function", "function": {"name": "render_turn"}}
        try:
            resp = _post_chat(self._url, self._key, body, timeout=40, kind="director")
            msg = resp.json()["choices"][0]["message"]
            text = (msg.get("content") or "").strip()
            tool_calls = msg.get("tool_calls") or []
        except Exception as e:  # network / auth / quota — degrade, never 500 the turn
            if narrate:
                return {"beats": [{"type": "description", "speaker_name": None,
                                   "text": f"（一时看不真切。）[模型调用失败: {type(e).__name__}]"}],
                        "affinity_delta": 0, "advance_act": False, "ending": None}
            return {
                "beats": [{"type": "dialogue", "speaker_name": speaker,
                           "text": f"（{speaker}沉默了一下，似乎不太想接话。）[模型调用失败: {type(e).__name__}]"}],
                "affinity_delta": 0,
                "advance_act": False,
            }

        if narrate:
            return {"beats": [{"type": "description", "speaker_name": None, "text": text}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}
        # parse the render_turn tool call (separate narration/speech fields)
        if tool_calls:
            args = ((tool_calls[0] or {}).get("function") or {}).get("arguments")
            parsed = _parse_tool_args(args, speaker, channel, group_mode)
            if parsed is not None:
                return parsed
        # fallback (tool missing / unparseable): prose+quote parser on any free text
        return _parse_reply(text, speaker, channel, group_mode)


class DeepSeekLLM(QwenLLM):
    """DeepSeek (api.deepseek.com) — OpenAI-compatible, so it reuses the entire QwenLLM
    pipeline (prompt building, depth anchor, parsing, memory summary) and only points the
    HTTP calls at DeepSeek's endpoint. Cheaper + stronger prose/台词 than qwen-max."""

    def __init__(self) -> None:
        s = get_settings()
        self._url = DEEPSEEK_URL
        self._key = s.deepseek_api_key
        self._model = s.deepseek_model or "deepseek-chat"
        self._summary_model = self._model  # DeepSeek has no cheap tier; reuse the chat model
