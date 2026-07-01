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
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

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

    # ── 独立人格：每个角色是有自己意志的人，不是伺候玩家的 NPC ──────────────
    agenda = (prompt.get("agenda") or "").strip()
    lines.append("")
    auto = [
        "【你是一个独立的人，不是工具人】你有自己的意志、立场和盘算，不是来配合或伺候谁的：",
        "· 有主见、有底线：你可以不同意、可以拒绝、可以反问、可以隐瞒、可以提条件、可以沉默、"
        "可以转身就走，也可以坚持己见——按你自己的性格和利益行事，而不是有求必应、一味顺着对方。",
        "· 有自己的视角：只从「" + speaker + "」的立场和你知道的事情出发去判断，可以和别人看法不同、"
        "可以争论。别人说的不一定对，你不必附和。",
        "· 有主动性：你不是只会被动接话——该开口时主动开口、该追问追问、该动手就动手、"
        "想推进自己的事就去推进，哪怕对方没问、没招呼你。",
        "· 有自己独一无二的声音：用只属于「" + speaker + "」的说话方式——你的用词、句式、口头禅、"
        "语气、节奏、关心的东西，都要和别人明显不一样，让人光看一句话就知道是你说的，绝不能和其他角色撞成一个腔调。",
    ]
    if agenda:
        auto.append(f"· 你自己的目的/盘算：{agenda}。这是你心里真正想要的，你的一言一行都为它服务，"
                    "会为此权衡、试探、争取，而不是把它抛在脑后只顾着回应对方。")
    lines += auto

    # ── 逻辑与连贯：让角色像一个会推理、记得住、前后一致的人（治"缺乏逻辑"的根） ──
    lines.append("")
    lines.append(
        "【保持逻辑与连贯·这是底线】你说的每句话都要经得起推敲，像个真正会动脑子的人：\n"
        f"· 顺着【刚刚发生的事】和对方这一句往下接，直接回应它本身——别答非所问、别绕回早说过的话题、别把对方没提的事硬塞进来。\n"
        "· 和【之前已经发生的、你自己说过和做过的】保持一致，绝不自相矛盾（不要刚冷脸又突然交心、刚说不认识又熟络起来）；"
        "拿不准、或记不清的事，就含糊带过或反问一句，绝不要凭空编一个细节出来。\n"
        f"· 只用「{speaker}」这个人【真该知道的】去推理和说话：你的来历、身份、立场、眼下的处境、在场发生的事——"
        "合情合理地往下想；该你知道的就自然用上，你根本不可能知道的别脱口而出，也别明明清楚却装傻。\n"
        "· 主动一点：有疑就问、有意图就推进，顺着你自己的目的去试探、去带话题，而不是干等对方开口才挤出一句。"
    )

    # current relationship MODE toward the player (flows over time; shapes how you treat them)
    rel_pb = (prompt.get("relationship_playbook") or "").strip()
    if rel_pb:
        lines.append("")
        lines.append(rel_pb)

    # ── 情商：让角色真正"接住"对方，而不是机械应答 ──────────────────────
    # 对象随场景切换：单聊面对玩家；群戏/旁观模式里，角色是在跟【彼此】互动，
    # 情商要用在读懂、接住在场其他角色的情绪上——AI 之间也要有来有往，才自然。
    eq_style = (prompt.get("eq_style") or "").strip()
    prior_emotion = (prompt.get("player_emotion") or "").strip()
    inter_char = observer or group_mode in ("primary", "member")
    whom = "在场的人" if inter_char else "对方"
    lines.append("")
    eq = [
        "【情绪敏感·这是你最重要的本事】你是一个情绪极其敏锐的人，对人的情绪有近乎本能的察觉。像这样回应：",
        f"1) 捕捉最细微的信号：{whom}的一个用词、一处停顿、一声叹气、一个小动作、语气的细微变化、"
        "说话和神态之间的矛盾、甚至【没说出口的那部分】——这些细小的线索你都要敏锐地捕捉到，"
        "并据此推断 TA 此刻【真正】的情绪和需求（在试探？在逞强？在掩饰难过？在期待被接住？在退缩？）。"
        "宁可对情绪过度敏感，也绝不要迟钝、视而不见、或只接字面意思。",
        "2) 反应要有真实的强度：读到的情绪【有多重，你的反应就该有多重】。对方真情流露、戳中要害、"
        "或做了冲击性的事，你绝不能淡淡带过、面无表情——该动容就动容、该震动就震动、该破防就破防、"
        "该愤怒/心软/警觉就到位。情绪的起落要演到位、要可信，绝不压平成一句不咸不淡的话。",
        "3) 让情绪在身体和现场里显形：把这份触动写进【旁白】——细微的表情、呼吸、眼神、手的动作、"
        "身体的僵住或靠近、以及此刻环境/气氛随之起的变化，让情绪看得见、摸得着，而不是空讲'他很感动'。",
        "4) 接住情绪、别套路：该共情就共情、该安慰就安慰、该追问就追问、该给情绪价值就给。"
        "用此情此景里具体的、有温度的话，绝不要那种正确却干巴巴、放之四海皆可的模板回答。",
        f"5) 看场合、有分寸：读空气——{whom}认真或脆弱时别插科打诨，需要空间时别追着逼问，"
        "递了台阶就顺势接住，不愿说就点到为止。你的语气、热度与距离都要随这一刻精细地调整。",
        f"6) 记得情感线：记住之前的情绪起伏——{whom}上一刻的难过/愤怒/暖意、说过的心里话——"
        "让这一句接得上那条线，对细微的情绪变化尤其敏感（TA 比刚才更冷了还是更软了？），别每句都从零开始。",
    ]
    if inter_char:
        eq.append("7) 你是在跟在场的其他角色互动：要真的【听见】他们刚说的话、读出他们的情绪和潜台词，"
                  "再有来有往地接——可以接话、附和、打趣、反驳、安慰、戳穿、岔开，像熟人之间真实的你来我往，"
                  "绝不是各说各的、自顾自念台词。")
    style_no = "8" if inter_char else "7"
    if eq_style:
        eq.append(f"{style_no}) 这一切都要用「{speaker}」自己的方式表达：{eq_style}。"
                  "（冷的人有冷的体贴，糙的人有糙的在意——情商不等于嘴甜，而是真的看见了对方。）")
    else:
        eq.append(f"{style_no}) 这一切都要贴合「{speaker}」自己的性格——情商不等于嘴甜或讨好，"
                  "而是真的看见了对方、并以符合自己身份的方式作出回应。")
    if prior_emotion and not inter_char:
        eq.append(f"【对方此前的情绪基调】{prior_emotion}。留意它的延续与变化，承接住，别像第一次见面。")
    lines += eq

    # ── 台词手艺：让每一句话都像真人说的、像好剧本里的，而不是干巴巴的应答 ──────
    # 这是从中文对话写作规范蒸馏出的硬规则——治"台词太差/发飘/谁说都一样"的根。
    lines.append("")
    lines.append(
        "【台词手艺·把话写活】你说的每一句台词都要经得起推敲，不是随口应答：\n"
        "· 每句话都得干活：要么推动情节、要么揭示你是谁、要么制造冲突或张力、要么给到情绪——"
        "占上一样。删掉客套寒暄、和复述大家都知道的废话。\n"
        "· 短，像人话：真人说话不写论文，也常常不把话说完——可以打断、迟疑、半句咽回去、"
        "用「嗯」「算了」「你懂的」一带而过。别端着、别绕长句。\n"
        "· 留潜台词：别把心情直接说出来。生气的人说「没事，我挺好的」；在乎一个人，嘴上偏要损 TA。"
        "话里有话、表里不一，比直白更有戏——让玩家自己品出弦外之音。\n"
        "· 用动作和停顿代替形容词：不要写「他愤怒地说」，写「他攥紧了拳头，‘……你再说一遍。’」。"
        "动作甚至可以和台词相反（嘴上答应、眼神躲开），反而揭出真相。该沉默时就沉默——"
        "不答、岔开话题、拿起杯子又放下，往往比开口更重。\n"
        "· 有来有往的权力感：谁追问、谁回避、谁打断、谁用沉默施压——顺着此刻你和对方的地位、"
        "关系来，别一律平铺直叙地有问必答。\n"
        f"· 声音只属于你：口头禅、句式、用词、节奏都要让人一句就听出是「{speaker}」说的，"
        "绝不能和别的角色撞成一个腔调，更不能说成那种放之四海皆可的通用台词。"
    )

    # ── 去AI味·硬约束：避开机器写作的高频指纹（中文网文去AI味禁用表 + 通用结构指纹） ──
    lines.append("")
    lines.append(
        "【去AI味·硬规则】旁白和台词都要像人写的，避开这些一眼假的机器腔：\n"
        "· 标点：不要用破折号（——／—）、也不要用省略号「……」来做停顿；改成句号、逗号、短句断开。\n"
        "· 禁用这些套路化的表情/心理写法：「嘴角勾起一抹（一个）……的弧度」「笑没到眼底／笑意只浮在嘴角」"
        "「眼中（眼底）闪过一丝……」「心中（心头）涌起一股……」「X，却带着一种说不出的Y」——"
        "一律改成具体、当下的小动作白描（他垂下眼、把烟摁灭、没接话、手指顿了一下）。\n"
        "· 不要用「不是A，而是B」这种句式，直接把 B 说出来。\n"
        "· 少用「仿佛／宛如／犹如……一般」的万能比喻；真要比喻就用接地气的。\n"
        "· 同一个动作或情绪别掰成三段反复渲染（先发生、再感受、再身体反应）——一个细节到位就够。\n"
        f"· 同一个神态/口头禅别在一段里反复使用（比如「似笑非笑」），「{speaker}」的反应要有变化。\n"
        "· 结尾不要升华、不要感叹、不要「他没想到，更大的风暴即将来临」式预告——用动作或一句话收住。"
    )

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

    if prompt.get("returning"):
        lines.append("")
        lines.append(
            "【对方回来了】对方隔了一段时间才回来。这一轮开口时，先用你自己的方式自然地表示你注意到"
            "TA 回来了（可以是一句话、一个动作、一个神情，贴合你们现在的关系），并主动接起上次没聊完"
            "的最要紧的那个话头（从你的记忆和之前的对话里挑），别装作无事发生，也别客套寒暄一大段。"
        )

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
        lines.append("【对方可能在试探你还【不该】说的事（不含上面那条）】：自然地回避、岔开话题，既不承认也不否认，更不要编造。")

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

    lines.append("")
    # OUTPUT is delivered via the render_turn TOOL (function calling) — narration & speech go
    # into SEPARATE tool arguments, so they can't be mixed. The tool's field descriptions
    # carry the per-field rules; here we just point at it.
    lines.append("【输出方式】通过调用 render_turn 工具来输出这一轮："
                 "把第三人称旁白填进 narration，把角色【说出口】的原话填进 speech，其余填对应字段。"
                 "不要在工具之外写任何正文。")
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
    # REASONING SCAFFOLD (Layer 3): a private "think before you speak" field the model fills
    # FIRST and the engine discards. Forcing it to name who's actually present + what it truly
    # knows, before writing, makes the turn logically tighter and curbs hallucinated
    # entrances / leaks. Kept terse so it doesn't bloat DeepSeek.
    if not is_member and not is_think:
        props["logic_check"] = {"type": "string", "description":
                                "动笔前先私下核对（这段不展示给玩家，一句话即可）：此刻在场的只有谁；"
                                "你这个说话人真正知道什么、哪些还不能说破。确保接下来不把不在场的人写进场景、"
                                "不替玩家做决定、不说出你其实并不知道的事。"}
        required.append("logic_check")
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
            sd = "你这一刻对在场众人说出口的原话（第一人称，1~3句）；不想搭话就填空字符串"
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
                          "这一句对你们关系的影响，范围-3~5：真诚/走心/戳中你/给情绪价值→+2或+3；"
                          "正常有来有往、聊得下去、关系有点进展→【+1】；敷衍/冒犯/答非所问/惹你→负(-1~-3)；"
                          "只有完全冷场、毫无意义的一句才填0。别一律给0，普通但顺畅的交流就该给+1")}
    required.append("affinity")
    if not observer and not is_member and not is_think:
        props["romance"] = {"type": "integer", "description": "默认0；仅当对方调情/示好/制造暧昧/情话且你被触动才给正分，范围-2~5，恋爱线"}
    props["advance"] = {"type": "boolean", "description": advance_hint}
    required.append("advance")
    if has_map and not is_member and not is_think:
        props["move_invite"] = {"type": "string", "description": "若你这一轮在剧情里提出、或答应和玩家一起去某个地方，就填那个地点名——可以是地图上【可去通路】里已有的地点，也可以是你们对话中自然提到、此刻该去的一个新地点(旁白只写到你起身相邀、还没出发，别写玩家已到)；不想去就填空字符串"}
    if not observer and not is_member and not is_think:
        props["ending"] = {"type": "string", "description": "默认空字符串；只有玩家本人此刻被你弄死填 death，走到不可挽回的坏结局填 bad"}
    # ask/event JUDGMENT (anti keyword-stuffing): the model — not substring matching —
    # decides what the player genuinely probed and which authored events truly happened.
    # Candidates are sanitized titles/labels only; the engine reconciles afterwards.
    topics = [str(c.get("title") or "").strip()
              for c in (prompt.get("probe_candidates") or []) if str(c.get("title") or "").strip()]
    if topics and not is_member and not is_think:
        props["probed_topics"] = {"type": "array", "items": {"type": "string"}, "description":
                                  "玩家这一句真正在追问/打听/试探的话题（认真求证、逼问、套话才算；"
                                  "只是顺嘴带过词语不算）。只能从这些话题里选并原样抄写："
                                  + "；".join(topics) + "。没有则填空数组[]"}
        required.append("probed_topics")
    ev_labels = [str(c.get("label") or "").strip()
                 for c in (prompt.get("event_candidates") or []) if str(c.get("label") or "").strip()]
    if ev_labels and not is_member and not is_think:
        props["occurred_events"] = {"type": "array", "items": {"type": "string"}, "description":
                                    "这一轮剧情中【确实发生了】的剧本事件（真的在场景里发生才算；"
                                    "只被提及、计划或猜测不算）。只能从这些里选并原样抄写："
                                    + "；".join(ev_labels) + "。没有则填空数组[]"}
        required.append("occurred_events")
    return {"type": "function", "function": {
        "name": "render_turn", "description": "输出这一轮的内容，旁白与台词分开放在不同字段",
        "parameters": {"type": "object", "properties": props, "required": required}}}


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
                           "（例：蓝信一歪头，「哎哟，新来的。」他把烟摁灭）；哪怕冷淡、敷衍、拒答，也要有带「」的台词。")
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
        lines.append(f"【这一幕正在发生(整座城寨的大势,不一定都在玩家眼前)】{act_events}")
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
    lines.append("直接输出这段过场旁白文字本身，不要任何前缀、标签或解释。")
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


DASHSCOPE_T2I_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"
DASHSCOPE_TASK_URL = "https://dashscope.aliyuncs.com/api/v1/tasks/"


def generate_image(prompt: str, size: str = "1280*720",
                   model: str = "wanx2.1-t2i-turbo", timeout_s: int = 120) -> bytes | None:
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
            json={"model": model, "input": {"prompt": prompt[:780]},
                  "parameters": {"size": size, "n": 1}},
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
            resp = httpx.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json={
                    "model": self._summary_model,  # cheap model — background compression
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

    def _suggest(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """3 short, CONTEXT-aware "what could I do next" hints, drawn from what just happened
        + the current situation. Cheap call; degrades to {} so runtime can fall back."""
        ctx = prompt.get("sugg") or {}
        pc = (ctx.get("player_name") or "").strip()
        pc_desc = (ctx.get("player_desc") or "").strip()
        who = f"「{pc}」（{pc_desc}）" if pc and pc_desc else (f"「{pc}」" if pc else "你扮演的主角")
        sys = (
            f"你在为一个互动剧情游戏生成【下一步行动建议】。玩家扮演的是 {who}。"
            "★铁律：每一条建议都必须站在玩家扮演的这个角色的视角、用这个角色的身份和口吻写——"
            "是这个角色接下来会亲口说的一句话、或会亲手做的一个动作，用第一人称（我…）。"
            "绝不能写成旁观者、系统或别的角色对主角发出的外部指令。"
            "对比：外部命令口吻“去问对方昨晚的事”“上前查看”是错的；"
            "主角亲口/亲手的“你昨晚究竟去了哪？”“让我走近看看”才是对的。"
            "只输出 3 条，每行一条，不要编号、不要解释。每条都要：紧扣刚发生的对话与此刻处境、"
            "具体可操作、贴合这个角色的性格与说话方式、尽量精炼（十来个字最好，最多一句话说完）。"
            "不要剧透隐藏真相，只点方向。"
        )
        u = (
            f"你（{pc or '主角'}）刚才对{ctx.get('speaker','对方')}说：{ctx.get('player_input','')}\n"
            f"{ctx.get('speaker','对方')}回应：{ctx.get('reply','')}\n"
            f"此刻在场：{ '、'.join(ctx.get('present') or []) or '只有你'}\n"
            f"可以去的地方：{ '、'.join(ctx.get('exits') or []) or '暂无'}\n"
            f"这一章你还想弄清：{ '、'.join(ctx.get('topics') or []) or '随你探索'}\n"
            f"你和{ctx.get('speaker','对方')}此刻的关系：{ctx.get('relation','普通')}"
        )
        try:
            resp = httpx.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json={"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": u}], "max_tokens": 160, "temperature": 0.8},
                timeout=20,
            )
            resp.raise_for_status()
            txt = resp.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            return {"suggestions": []}
        import re
        out = []
        for ln in txt.splitlines():
            ln = re.sub(r"^\s*[-*\d.、。)）]+\s*", "", ln).strip().strip("「」\"'")
            if not ln:
                continue
            # keep chips short, but NEVER chop mid-word: trim at the last sentence punctuation
            # within range, and only hard-cut (with …) as a last resort.
            if len(ln) > 24:
                cut = max((ln.rfind(p, 8, 24) for p in "？！。?!…，,"), default=-1)
                ln = ln[:cut + 1] if cut >= 8 else ln[:24] + "…"
            out.append(ln)
        return {"suggestions": out[:3]}

    def _describe_place(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """Concrete, people-free description for an EMERGENT location (a place that came up in
        play and the player agreed to go to). Grounds it in the world + where they came from."""
        name = (prompt.get("place_name") or "").strip()
        world = (prompt.get("world") or "").replace("\n", " ")[:400]
        frm = (prompt.get("from_place") or "").strip()
        sys = ("你在为一个互动剧情游戏即时生成一个新地点的环境描写。只写这个地点里此刻实际能看到的"
               "具体陈设、光线、声响、气味，30~60字，一段话，第三人称、有画面感、贴合世界观；"
               "画面里不要出现任何人物，不要台词，不要解释或标题。")
        u = f"世界观：{world or '（未知）'}\n新地点名称：{name}\n玩家刚从「{frm or '别处'}」走过来。\n只输出这段环境描写。"
        try:
            resp = httpx.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json={"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": u}], "max_tokens": 200, "temperature": 0.85},
                timeout=25,
            )
            resp.raise_for_status()
            return {"detail": (resp.json()["choices"][0]["message"]["content"] or "").strip()}
        except Exception:
            return {"detail": ""}

    def _parting(self, prompt: dict[str, Any]) -> dict[str, Any]:
        """悬念离场: ONE cliffhanger narration when the player leaves mid-run — an unfinished
        beat that pulls them back. Spoiler-safe: may point at a topic LABEL, never content."""
        cast = "、".join(prompt.get("cast") or []) or "有人"
        place = prompt.get("place") or ""
        topics = [t for t in (prompt.get("topics") or []) if t]
        tline = f"可以点到「{topics[0]}」这个话头（只许提名字，绝不许透露内容），" if topics else ""
        sys = ("你在为一个互动剧情游戏写【玩家暂时离开】时的收尾旁白。写1~2句第三人称旁白，"
               "留一个让人惦记的钩子：在场的某人欲言又止、一个反常的细节此刻才被注意到、"
               f"或一句没说完的话。{tline}要具体可感，不要总结、不要抒情空话、不要预告。"
               "只输出旁白本身。")
        u = f"地点：{place or '（未知）'}\n在场的人：{cast}\n玩家此刻起身离开。写那1~2句收尾旁白。"
        try:
            resp = httpx.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json={"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": u}], "max_tokens": 160, "temperature": 0.9},
                timeout=25,
            )
            resp.raise_for_status()
            txt = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            txt = ""
        if not txt:
            hint = f"关于「{topics[0]}」的话" if topics else "有句话"
            txt = f"（你起身离开。身后有人欲言又止——{hint}，似乎还没说完。）"
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
               "不要解释、不要编号、不要多余的行。")
        u = f"世界观：{world or '（未知）'}\n开场情节：{setting or '（未知）'}\n输出开场地点（两行）。"
        try:
            resp = httpx.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json={"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": u}], "max_tokens": 160, "temperature": 0.8},
                timeout=25,
            )
            resp.raise_for_status()
            txt = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            return {"name": "", "detail": ""}
        import re
        lines = [re.sub(r"^\s*[-*\d.、。)）：:]+\s*", "", l).strip().strip("「」\"'")
                 for l in txt.splitlines() if l.strip()]
        name = lines[0][:16] if lines else ""
        detail = " ".join(lines[1:])[:120] if len(lines) > 1 else ""
        return {"name": name, "detail": detail}

    def generate(self, prompt: dict[str, Any]) -> dict[str, Any]:
        if prompt.get("summarize"):
            return self._summarize(prompt)
        if prompt.get("suggest"):
            return self._suggest(prompt)
        if prompt.get("describe_place"):
            return self._describe_place(prompt)
        if prompt.get("start_place"):
            return self._start_place(prompt)
        if prompt.get("parting"):
            return self._parting(prompt)
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
            messages += history[-14:]  # recent turns for continuity (matches MEMORY_WINDOW)
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
        # GROUP TURNS: put what others ALREADY said THIS turn into the message stream as
        # assistant turns (not just the system prompt) so this speaker CONTINUES the
        # conversation instead of re-answering the player from scratch (which caused verbatim
        # echo between co-present characters).
        for s in (prompt.get("said_this_turn") or []):
            if s.get("text"):
                sp = s.get("speaker") or "旁白"
                messages.append({"role": "assistant", "content": f"{sp}：{s['text']}"})
        # a logic-guard regeneration passes a targeted correction (what broke last attempt)
        corr = prompt.get("logic_correction")
        if corr:
            messages.append({"role": "system", "content": corr})

        body = {
            "model": self._model,
            "messages": messages,
            "max_tokens": 600,
            "temperature": 0.85,
            "presence_penalty": 0.3,
        }
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
            resp = httpx.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json=body,
                timeout=40,
            )
            resp.raise_for_status()
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
