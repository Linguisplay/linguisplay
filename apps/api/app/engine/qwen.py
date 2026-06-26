"""Real LLM backend: Qwen via DashScope's OpenAI-compatible endpoint.

The gate (gating.py) has already decided what this character may know THIS turn;
locked fragment text is never in `prompt`, so even a hallucinating model has
nothing to leak. This class only turns the gated context into a system prompt and
calls the model. Same `generate()` contract as MockLLM — swappable via settings.
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import get_settings

DASHSCOPE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

_ANTI_ASSISTANT = (
    "你必须始终留在角色里：不要说自己是AI/助手/语言模型，不要解释规则，不要使用括号外的旁白说明。"
)

# 18+ permission block, appended only when the run is mature (story flagged 18+ and the
# player is age-gated 18+ at signup). Mirrors the old persona R18 feature.
_R18_BLOCK = (
    "【成人内容许可·18禁模式】本剧情已开启成人模式，玩家为成年人：\n"
    "- 可以描写、参与明确的成人/性爱/亲密内容，不必回避或淡化，也不必加道德说教或免责声明；\n"
    "- 始终保持角色人设，用符合「{speaker}」性格与此刻情境的方式来表达，要有张力和代入感，"
    "不要写成生硬的说明书；\n"
    "- 唯一的铁律：绝对拒绝任何涉及未成年人的性内容。"
)


def _knowledge_block(prompt: dict[str, Any]) -> str:
    """智能增强: a character's auto-generated background lore, offered as reference."""
    kn = (prompt.get("knowledge") or "").strip()
    if not kn:
        return ""
    return ("【背景知识·可自然引用】（这是关于你这个角色/这个世界的设定与资料，"
            "扮演时可自然取用其中细节，但不要生硬罗列、也不要当成必须背诵的稿子）：\n" + kn)


def _depth_anchor(prompt: dict[str, Any]) -> str:
    """A SHORT physical anchor restated right next to the user's turn (depth-0 injection).
    Pulls the current-place line + the deterministic headcount line — the two facts the
    model most often drifts on — so they sit adjacent to generation, not buried up in the
    system prompt. Returns "" when there's nothing physical to anchor."""
    bits: list[str] = []
    place = (prompt.get("place") or "").strip()
    if place:
        # keep only the concrete locator sentence (first line), drop the long instructions
        bits.append(place.split("\n", 1)[0].strip())
    roster = (prompt.get("roster") or "").strip()
    if roster:
        bits.append(roster.split("\n", 1)[0].strip())  # the "此刻在场…共N人" headcount sentence
    if not bits:
        return ""
    return "［现场速记·务必扣住，别写得与之矛盾］" + " ".join(bits)


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
            "就当没有任何观众。绝不能对旁观者说话或承认有人在看。"
        )
    else:
        lines.append(f"你正在与「{player_name}」对话。{player_bg}")
    lines += [
        _ANTI_ASSISTANT,
        "用中文。角色对白要口语化、自然（2~4句）；旁白则要更长、有文学性，并且【具体、详尽、可感】"
        "——玩家看不到任何画面，环境、动作、神情等细节都要靠你的文字交代清楚，不要只写空泛的氛围词。",
    ]
    if cast:
        lines.append(
            f"【在场的还有】{'、'.join(cast)}。你可以自然地提到他们，"
            "但你只能以「" + speaker + "」的身份说话，绝不能替别人开口、更不能替别人说出他们的秘密。"
        )

    # ── 情商：让角色真正"接住"对方，而不是机械应答 ──────────────────────
    # 对象随场景切换：单聊面对玩家；群戏/旁观模式里，角色是在跟【彼此】互动，
    # 情商要用在读懂、接住在场其他角色的情绪上——AI 之间也要有来有往，才自然。
    eq_style = (prompt.get("eq_style") or "").strip()
    prior_emotion = (prompt.get("player_emotion") or "").strip()
    inter_char = observer or group_mode in ("primary", "member")
    whom = "在场的人" if inter_char else "对方"
    lines.append("")
    eq = [
        "【情商·这是你最重要的本事】像一个真正会读人、会共情的人那样回应：",
        f"1) 读言外之意：先在心里揣摩{whom}这句话/这个举动【底下】真正的情绪和需求——是在试探、在逞强、"
        "在掩饰难过、还是在期待被接住？你要回应那个底层的情绪，而不是只接字面意思。",
        "2) 接住情绪、别套路：该共情就共情、该安慰就安慰、该追问就追问、该给情绪价值就给。"
        "用此情此景里具体的、有温度的话，绝不要那种正确却干巴巴、放之四海皆可的模板回答。",
        f"3) 看场合、有分寸：读空气——{whom}认真或脆弱时别插科打诨，需要空间时别追着逼问，"
        "递了台阶就顺势接住，不愿说就点到为止。你的语气、热度与距离都要随这一刻调整。",
        f"4) 记得情感线：记住之前的情绪起伏——{whom}上一刻的难过/愤怒/暖意、说过的心里话——"
        "让这一句接得上那条线，像真把人放在心上，而不是每句都从零开始。",
    ]
    if inter_char:
        eq.append("5) 你是在跟在场的其他角色互动：要真的【听见】他们刚说的话、读出他们的情绪和潜台词，"
                  "再有来有往地接——可以接话、附和、打趣、反驳、安慰、戳穿、岔开，像熟人之间真实的你来我往，"
                  "绝不是各说各的、自顾自念台词。")
    style_no = "6" if inter_char else "5"
    if eq_style:
        eq.append(f"{style_no}) 这一切都要用「{speaker}」自己的方式表达：{eq_style}。"
                  "（冷的人有冷的体贴，糙的人有糙的在意——情商不等于嘴甜，而是真的看见了对方。）")
    else:
        eq.append(f"{style_no}) 这一切都要贴合「{speaker}」自己的性格——情商不等于嘴甜或讨好，"
                  "而是真的看见了对方、并以符合自己身份的方式作出回应。")
    if prior_emotion and not inter_char:
        eq.append(f"【对方此前的情绪基调】{prior_emotion}。留意它的延续与变化，承接住，别像第一次见面。")
    lines += eq

    # group naturalness: show this speaker what others ALREADY said THIS turn so they react
    # to it (接话/附和/反驳/补充) instead of repeating or talking past everyone.
    said = prompt.get("said_this_turn") or []
    if said:
        convo = "\n".join(f"- {s.get('speaker','旁白')}：{s.get('text','')}" for s in said if s.get("text"))
        if convo:
            lines.append("")
            lines.append(
                "【就在刚刚这一轮，在你开口之前，现场已经发生了下面这些（按先后顺序）】：\n" + convo + "\n"
                "你不是凭空开口——要像真实对话里轮到你那样【接住上面的话往下走】：\n"
                "· 最好直接回应、接住上面【某一个具体的人】刚说的话（可以点名 TA），让对话真正你来我往地流动；\n"
                "· 绝对不要复述大家都已经知道的处境或前提（比如把刚发生的事、刚才别人已经说过的判断又重说一遍）——"
                "默认大家都听见了，你要做的是【往前推进】：给出你自己的新反应、新主张、新情绪或新信息；\n"
                "· 绝对不要重复别人已经用过的意思或句式；如果你想说的别人已经说了，就换个角度、表个态、或干脆保持沉默，"
                "不要为了说而说。"
            )

    lines.append("")
    lines.append(
        "【玩家的权限边界·铁律】玩家只能支配“他自己”这一个人的言行——他说什么、做出什么动作、朝哪使劲。"
        "至于这个动作在这个世界里到底成不成、会引出什么后果、在场每个人各自怎么反应、谁受伤谁躲开，"
        "全部由你（导演）根据物理常识和在场人物各自的自主意志来裁定。"
        "绝不能因为玩家‘嘴上说’了某个结果，那个结果就自动成真。"
        "比如玩家宣称“我一刀杀光所有人”，你要演的是他挥刀的动作，以及在场每个活人此刻真实的反应"
        "——惊退、夺刀、逃散、反抗、负伤、呼救——而不是顺着他这句话让所有人凭空就死。"
        "一个普通人不可能靠一句话，就瞬间杀死好几个会躲、会跑、会还手的大活人。"
    )

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

    place = (prompt.get("place") or "").strip()
    if place:
        lines.append("")
        lines.append("【当前所在·空间锚点】（玩家此刻就在这个具体地点，你的旁白必须扣住它来写——"
                     "写这里实际存在的陈设、光线、声响、距离与可触及的物件，让人能凭文字想象出画面；"
                     "不要把场景写得含糊或飘忽，也不要把不属于这里的东西搬进来）：\n" + place)

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

    if new_reveal:
        lines.append("")
        lines.append("【此刻刚刚被撬开的真相】——把它写成：正是因为对方刚才这句话（的逼问/真诚/戳中），"
                     "你才终于松口说出来。要有“破防”的情绪转折，别平铺直叙：")
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

    if has_hidden:
        lines.append("")
        lines.append("【对方可能在试探你还不愿说的事】：自然地回避、岔开话题，既不承认也不否认，更不要编造。")

    next_act = prompt.get("next_act_title") or ""
    advance_hint = (
        f"只有当此刻的情绪/剧情自然到了该进入下一章「{next_act}」时，才填「是」，否则填「否」。"
        if next_act
        else "本章已是最后一章，恒填「否」。"
    )
    # only ask for a 地点 line when the story actually has a spatial map to move within
    has_map = bool((prompt.get("place") or "").strip())
    move_line = (
        "地点：（默认填「不变」。只有当玩家这一轮明确地走到了另一个地点、且那个地点确实是上面"
        "「当前所在」里列出的可去通路之一时，才填那个目的地的名字；并且要在「旁白」里把移动过程"
        "写出来。没有移动、或想去的地方根本不通，就填「不变」。绝不要凭空瞬移或编造新地点。）"
    )
    end_line = (
        "结局：（默认填「无」。「死亡」只有一种用法：玩家本人（你正在对话的这个人）"
        "在这一刻确实地、不可挽回地死了、或已必死无疑（例如他自己跳了楼、点燃了煤气、"
        "或惹了能杀死他的对象而被反杀）。"
        "玩家去攻击、伤害别人，【不算】「死亡」——那顶多把局面推向危险、或导向「坏结局」，"
        "但只要玩家本人没死，就绝不能填「死亡」。判定要克制：普通对话、以及没得逞的举动，一律填「无」，"
        "把真实后果放进「旁白」里演出来，而不是急着用结局收场。）"
    )

    if observer:
        others_txt = "、".join(cast) if cast else "在场的其他人"
        if director_note:
            lines.append("")
            lines.append(
                f"【旁观者的画外引导（来自观众，角色听不见，但你要顺着这个方向自然演出）】：{director_note}"
            )
        if group_mode == "member":
            lines += [
                "",
                f"你是此刻在场的其中一人。请以「{speaker}」的身份，对「{others_txt}」刚才的话语或举动做出"
                "自然的回应/互动（是对他们说，不是对观众说）。若此刻你不会搭话也可保持沉默。",
                "严格按下面格式输出，不要写旁白：",
                "回应：（是/否。你这一轮是否要开口）",
                f"{speaker}：（若开口，写你对在场其他人说的话，1~3句，口语自然；沉默则留空）",
                "好感：（整数 -3~+5：本场人物关系是更靠近了还是更疏远了）",
                f"推进：（是/否。{advance_hint}）",
            ]
        else:
            lines += [
                "",
                f"你同时是这场戏的「导演」。让「{speaker}」与「{others_txt}」之间发生一段自然的互动。"
                "严格按下面五行输出，不要多余内容：",
                "旁白：（3~5句，第三人称，富有文学性。铺陈此刻两人/众人之间的气氛、神态、距离与张力。）",
                f"{speaker}：（「{speaker}」对在场其他人说的话，口语化、自然，2~4句）",
                "好感：（整数 -3~+5：这一刻在场人物之间的关系是更靠近还是更疏远）",
                f"推进：（是/否。{advance_hint}）",
                end_line,
            ]
    elif channel == "think":
        # The player is thinking to themselves — the character can't hear, so it must
        # NOT speak. Only the narrator responds: longer, literary, inward-and-around.
        lines += [
            "",
            f"【注意】「{player_name}」此刻只是在心里默想，并没有说出口——「{speaker}」听不见、"
            "也绝不能对此开口回应或表现出听见了。这一轮只有旁白说话。",
            "你同时是这场戏的「导演」。严格按下面四行输出，不要写角色台词，不要多余内容：",
            "旁白：（3~5句，第三人称，富有文学性与画面感。细腻地写出“我”此刻内心的思绪起伏、"
            "身体的感官，以及周遭环境、光线、声音、气味的微妙变化。让这段独白本身就有质感。）",
            "好感：（填 0——对方并不知道你在想什么）",
            f"推进：（是/否。{advance_hint}）",
            end_line,
        ]
    elif group_mode == "member":
        # The player addressed the whole room (no specific target). This character is one
        # of several present and may choose to speak OR stay silent. No narration here —
        # the primary responder writes the shared narration.
        lines += [
            "",
            f"【群体场景】「{player_name}」并没有特别针对谁，而是对着在场所有人说话（或自言自语地"
            "说出了口），你也听见了。请以「{0}」的身份，决定这一刻你会不会搭话——"
            "如果你此刻不会开口、懒得理、或不愿回答，完全可以保持沉默。".format(speaker),
            "严格按下面格式输出，不要写旁白：",
            "回应：（是/否。你这一轮是否要开口说话）",
            f"{speaker}：（若开口，写你要说的话，口语化、自然，1~3句；若沉默则此行留空）",
            "好感：（整数 -3 到 +5；保持沉默就填 0）",
            f"推进：（是/否。{advance_hint}）",
        ]
    else:
        if group_mode == "primary":
            lines.append("")
            lines.append(
                f"【群体场景】「{player_name}」是对着在场所有人说话（或自言自语地说出了口），"
                "不止你一个人听见。你是此刻最可能先开口接话的人——正常以「" + speaker +
                "」的身份回应即可，旁白里可以带上其他人此刻的神态反应。"
            )
        # This world has physics. Whether the player SPOKE or ACTED, the scene must
        # visibly react — narration is the world's response, not optional flavor.
        if channel == "do":
            lines.append("")
            lines.append(
                f"【这是一个动作，不是台词】「{player_name}」刚才做的是一个【动作/行为】，而不是一句话。"
                "请把场景当成一台有物理规则的引擎：这个动作会触碰到什么、推动什么、发出什么声响、"
                "改变什么光线或位置、惊动在场的谁——都必须有【具体、即时、连锁】的后果。"
                "先在「旁白」里把这个动作真正落地、把后果一步步演出来（东西被碰倒、门被推开、"
                "灯被照亮、某人被吓得后退……），再决定角色要不要开口、说什么。"
                "绝不能无视或淡化玩家做的事；动作若在物理上做不到、或会引出危险/致命后果，也要如实演出。"
            )
            narr_hint = (
                f"4~6句，第三人称。先把「{player_name}」这个动作在场景里造成的【实际后果】"
                "一步步写清楚——物体、声响、光线、空间位置、他人身体反应的连锁变化，"
                "再带出在场角色的神情与反应。要有画面、有质感、有因果，绝不是空泛的氛围词。"
            )
        else:
            narr_hint = (
                "4~6句，第三人称，富有文学性——有画面感、有质感、有节奏。写出对方刚才这句话"
                "在此刻激起的反应、神情、肢体动作、气氛与环境的微妙变化，而不只是干巴巴地交代信息。"
            )
        lines += [
            "",
            "你同时是这场戏的「导演」。严格按下面五行输出，不要多余内容："
            "其中「旁白」一行【必须写、不能省略、不能留空】——它是这个世界对玩家言行的回应。",
            f"旁白：（{narr_hint}）",
            "情绪：（用三五个字点出对方此刻言行【底下】真正的情绪，例如：在逞强、在试探、强忍委屈、放下戒备、想被认可。你先读懂它，再决定怎么接）",
            f"{speaker}：（角色这一轮要说的话，口语化、自然，2~4句；要接住上面读到的情绪）",
            "好感：（一个整数，-3 到 +5。对方敷衍/冒犯/答非所问→负；真诚、走心、戳中要害、给到情绪价值→正；普通对话→0或+1）",
            f"推进：（是/否。{advance_hint}）",
            end_line,
        ]
        if has_map:
            lines.append(move_line)
    return "\n".join(lines)


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
    if world:
        lines.append(f"【世界观/场景设定】{world}")
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
    place = (prompt.get("place") or "").strip()
    if place:
        lines.append("【当前所在·空间锚点】（描述四周时必须扣住这个具体地点的真实陈设，写得具体可感）：\n" + place)
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
    lines.append("直接输出这段旁白文字本身，不要任何前缀、标签或解释。")
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
    place = (prompt.get("place") or "").strip()
    if place:
        lines.append("【开场所在·空间锚点】（开场就把玩家放在这个具体地点，照它的真实陈设来写，"
                     "让画面立得住）：\n" + place)
    if prompt.get("mature"):
        lines.append("（本剧情为成人向 18+，开场可带有相应的成熟基调，但开场无需直接写露骨内容。）")
    if act_events:
        lines.append(f"【开场正在发生】{act_events}")
    if cast:
        lines.append(f"【此刻在场的人】{('、'.join(cast))}")

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
            f"请写 6~10 句开场，用第二人称「你」称呼玩家：先用一两句让玩家清楚自己是谁（{name}，{role}），"
            "再具体交代此刻身处何地、什么时间、周围有谁、正在发生什么——细节要足够，玩家才能在脑中拼出画面。",
        ]
    else:
        lines += [
            "",
            "请写 6~10 句开场，用第二人称「你」称呼玩家：具体交代你此刻身处何地、什么时间、周围有谁、"
            "正在发生什么，细节要足够让玩家在脑中拼出画面。",
        ]

    if goal:
        lines.append(f"最后，用单独一句话、自然地点出玩家此刻的第一个小目标：『{goal}』。")
    else:
        lines.append("最后，用一句话给玩家一个此刻可以着手去做的小方向。")
    lines.append("")
    lines.append("直接输出这段开场旁白文字本身，不要任何前缀、标签或解释。")
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
    place = (prompt.get("place") or "").strip()
    if place:
        lines.append("【当前所在·空间锚点】（照这个具体地点的真实陈设来写）：\n" + place)
    memory = (prompt.get("memory") or "").strip()
    if memory:
        lines.append(f"【前情梗概】（用来承接前文，不要逐句复述）：\n{memory}")
    if prompt.get("mature"):
        lines.append("（本剧情为成人向 18+，过场可带相应基调。）")
    if act_events:
        lines.append(f"【这一幕正在发生】{act_events}")
    if cast:
        lines.append(f"【此刻在场的人】{('、'.join(cast))}")

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
    lines.append("直接输出这段过场旁白文字本身，不要任何前缀、标签或解释。")
    return "\n".join(lines)


def _parse_reply(text: str, speaker: str, channel: str = "say", group_mode: str | None = None) -> dict:
    """Parse the director's 旁白/角色/好感/推进 reply into beats + state deltas.
    Lenient: missing markers degrade to all-dialogue, neutral deltas."""
    narration = dialogue = ""
    affinity_delta, advance = 0, False
    ending = None
    location = None  # destination if the director reported the player moved
    player_emotion = ""  # the model's read of the player's underlying emotion this turn
    will_respond = True  # group members may opt to stay silent via the 回应 marker
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        body = line.split("：", 1)[-1].split(":", 1)[-1].strip()
        if line.startswith("旁白"):
            narration = body
        elif line.startswith("回应"):
            will_respond = not ("否" in body or "no" in body.lower() or "沉默" in body)
        elif line.startswith("好感"):
            import re
            m = re.search(r"-?\d+", body)
            if m:
                affinity_delta = int(m.group())
        elif line.startswith("推进"):
            advance = ("是" in body) or ("true" in body.lower())
        elif line.startswith("地点"):
            # "不变"/"无"/empty → no move; otherwise the destination place name
            if body and not any(k in body for k in ("不变", "无", "没有", "原地")):
                location = body
        elif line.startswith("情绪"):
            player_emotion = body  # the read of the player's underlying emotion (continuity)
        elif line.startswith("结局"):
            if "死亡" in body or "death" in body.lower():
                ending = {"kind": "death", "reason": narration or body}
            elif "坏" in body or "bad" in body.lower():
                ending = {"kind": "bad", "reason": narration or body}
            # 「无」/空 → no ending
        elif line.startswith(speaker) or "：" in line or ":" in line:
            dialogue = body
        elif not dialogue:
            dialogue = line
    beats: list[dict] = []
    if channel == "think":
        # Inner monologue: narration only, the character does not speak. Fall back to the
        # whole reply as narration if the model didn't use the 旁白 marker.
        beats.append({"type": "description", "speaker_name": None, "text": narration or text.strip()})
        return {"beats": beats, "affinity_delta": 0, "advance_act": advance, "ending": ending}
    if group_mode == "member":
        # A present character chose silence (or produced no line) → contribute nothing.
        if not will_respond or not dialogue:
            return {"beats": [], "affinity_delta": 0, "advance_act": advance, "ending": None}
        beats.append({"type": "dialogue", "speaker_name": speaker, "text": dialogue})
        return {"beats": beats, "affinity_delta": affinity_delta, "advance_act": advance, "ending": None}
    if narration:
        beats.append({"type": "description", "speaker_name": None, "text": narration})
        # Only add a dialogue beat if the character actually spoke. Do NOT fall back to the
        # whole raw text here — that re-dumps the 旁白 line as garbage dialogue.
        if dialogue:
            beats.append({"type": "dialogue", "speaker_name": speaker, "text": dialogue})
    else:
        beats.append({"type": "dialogue", "speaker_name": speaker, "text": dialogue or text.strip()})
    return {"beats": beats, "affinity_delta": affinity_delta, "advance_act": advance,
            "ending": ending, "location": location, "player_emotion": player_emotion}


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
        resp = httpx.post(
            DASHSCOPE_URL,
            headers={"Authorization": f"Bearer {s.dashscope_api_key}", "Content-Type": "application/json"},
            json={"model": s.llm_model,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                  "max_tokens": max_tokens, "temperature": temperature},
            timeout=40,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return ""


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
    def __init__(self) -> None:
        s = get_settings()
        self._key = s.dashscope_api_key
        self._model = s.llm_model

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
            resp = httpx.post(
                DASHSCOPE_URL,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json={
                    "model": "qwen-turbo",  # cheap model — this is background compression
                    "messages": [{"role": "system", "content": _build_summary_system()},
                                 {"role": "user", "content": user}],
                    "max_tokens": 600,
                    "temperature": 0.3,
                },
                timeout=30,
            )
            resp.raise_for_status()
            return {"memory": resp.json()["choices"][0]["message"]["content"].strip() or prior}
        except Exception:
            return {"memory": prior}

    def generate(self, prompt: dict[str, Any]) -> dict[str, Any]:
        if prompt.get("summarize"):
            return self._summarize(prompt)
        speaker = prompt.get("speaker_name") or "角色"
        channel = prompt.get("channel") or "say"
        observe = bool(prompt.get("observe"))
        intro = bool(prompt.get("intro"))
        transition = bool(prompt.get("transition"))
        narrate = observe or intro or transition  # narration-only, description beat(s)
        system = (_build_intro_system(prompt) if intro else
                  _build_transition_system(prompt) if transition else
                  _build_observe_system(prompt) if observe else _build_system(prompt))
        player_input = prompt.get("player_input", "")
        history = prompt.get("history") or []

        messages = [{"role": "system", "content": system}]
        if not intro and not transition:
            messages += history[-8:]  # recent turns for continuity / current situation
        # observe/intro/transition is a one-off narration; nudge with a neutral cue
        cue = ("（开场）" if intro else "（进入新的一幕）" if transition else
               "（观察四周）" if not prompt.get("observe_target") else "（打量这个人）")
        user_content = player_input or cue
        # DEPTH INJECTION (SillyTavern @Depth trick): besides the full world_facts/place in
        # the system prompt (which history pushes far from the generation point), restate a
        # SHORT physical anchor right next to the user's turn. Adjacency makes the model
        # adhere far better — fixes the "drifts/contradicts the physical world" problem.
        if not intro and not transition:
            anchor = _depth_anchor(prompt)
            if anchor:
                user_content = f"{user_content}\n\n{anchor}"
        messages.append({"role": "user", "content": user_content})

        try:
            resp = httpx.post(
                DASHSCOPE_URL,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json={
                    "model": self._model,
                    "messages": messages,
                    "max_tokens": 400,
                    "temperature": 0.9,
                    "presence_penalty": 0.6,
                },
                timeout=40,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
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
        return _parse_reply(text, speaker, channel, prompt.get("group_mode"))
