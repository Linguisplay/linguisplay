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

# 18+ permission block, appended only when the run is mature (story flagged 18+ and the
# player is age-gated 18+ at signup). Mirrors the old persona R18 feature.
_R18_BLOCK = (
    "【成人内容许可·18禁模式】本剧情已开启成人模式，玩家是成年人，平台已做年龄门控：\n"
    "- 当剧情与情绪自然走到亲密处，就【正面、具体、不回避】地写成人/性爱内容：不要黑幕跳切、"
    "不要用省略号或含糊修辞糊弄过去、不要写到关键处突然收笔转场，更不要加道德说教或免责声明；\n"
    "- 身体、欲望、动作都可以直白地描写，火候由关系深浅与此刻的情绪决定；始终贴着角色人设，"
    "用符合「{speaker}」性格的方式表达，要有张力与代入感，不要写成流程说明书；\n"
    "- 写人的外貌与身材要【具体、感官、有视线】：身形轮廓、曲线或力量感、皮肤的质地、"
    "衣物如何贴合身体，都从看的人的位置与心境去写（目光落在哪、为什么移不开、心跳变没变），"
    "让描写带着欲望的温度，而不是清单式报参数；\n"
    "- 铁律只有两条：绝对拒绝任何涉及未成年人的性内容；强迫与胁迫不得被写成浪漫。"
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

    # group naturalness: the transcript of what others ALREADY said THIS turn (data; the
    # how-to-react rules live in the charter's 群戏 line)
    said = prompt.get("said_this_turn") or []
    if said:
        convo = "\n".join(f"- {s.get('speaker','旁白')}：{s.get('text','')}" for s in said if s.get("text"))
        if convo:
            lines.append("")
            lines.append("【就在刚刚这一轮，你开口之前，现场已经发生了（按顺序）】：\n" + convo + "\n"
                         "接住上面某个具体的人刚说的话往下走，只给出你自己的新反应/新主张/新信息。")

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
    powers = [str(p) for p in (prompt.get("player_powers") or []) if str(p).strip()]
    if powers:
        lines.append("【玩家的金手指·这个世界承认的真实能力】" + "；".join(powers) + "。"
                     "这些能力【确实存在、确实生效】：玩家动用它们时，让它在其描述的范围内真的起作用，"
                     "在场者亲眼所见就要有相应的震动与反应；可以有代价、消耗或边界，"
                     "但绝不能凭空发明「力量被压制」「此地无效」之类的理由让它失灵。"
                     "超出描述范围的夸大用法，才可以打折扣或失败。")
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
            if chk:
                verdict = {"crit_success": "大成功——干得超预期地漂亮，甚至带来意外之喜",
                           "success": "成功——如愿做成了",
                           "fail": "失败——没做成，并付出一点小代价或引来注意",
                           "crit_fail": "大失败——不但没成，还出了岔子、把局面搞得更糟"}.get(chk.get("outcome"), "")
                lines.append(f"【命运判定已掷出（d20 掷出 {chk.get('roll')}，需要 ≥{chk.get('dc') or '?'}）：{verdict}】"
                             "旁白必须严格按这个结果演出，不许翻案、不许淡化。")

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
                          "这一句对你们关系的影响(-3~5)：走心/戳中你→+2~3；正常聊得下去→+1；敷衍/冒犯→负；只有完全冷场才是0")}
    required.append("affinity")
    if not observer and not is_member and not is_think:
        props["romance"] = {"type": "integer", "description": "默认0；仅当对方调情/示好/制造暧昧/情话且你被触动才给正分，范围-2~5，恋爱线"}
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
    if has_map and not is_member and not is_think:
        props["move_invite"] = {"type": "string", "description": "若你这轮提出或答应带玩家去某处，填那个地点名（可以是【可去通路】里的，也可以是对话里自然浮现的新地点；旁白只写到起身相邀为止）；否则填空字符串"}
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
                              "description": "若这一轮有在场角色【确实起身离开、去了别处】（你在叙述里写了TA走），"
                                             "填 who=名字、to=去处地名；通常填空数组[]"}
        if prompt.get("can_new_char"):
            props["new_character"] = {"type": "string", "description":
                                      "若剧情此刻确实需要一个此前不存在的新人物登场（推门进来/被引见/"
                                      "下属报到/线人现身），填「名字｜身份与外貌各一句话」，并且 narration "
                                      "里必须把TA的登场写实：进场的动作、外貌神态、第一眼给人的感觉；"
                                      "不需要则空字符串"}
    if not observer and not is_member and not is_think:
        props["identity_change"] = {"type": "string", "description":
                                    "若这一轮玩家的身份/职务发生了实质改变（升职、任命、被揭穿、获得头衔），"
                                    "用一句话写TA的新身份；没有则空字符串"}
        props["item_gained"] = {"type": "string", "description":
                                "若玩家这一轮确实把某件具体物品拿到手（捡起/受赠/收起），填物品名；否则空字符串"}
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
                                       "若这一轮有人把一件有报酬的差事托付给玩家、且玩家应下了，填"
                                       "「一句话差事|报酬数额|限几天」（如 送三坛酒到码头|40|2；"
                                       "无期限第三段填0）；没有则空字符串"}
            props["quest_done"] = {"type": "string", "description":
                                   "若玩家这一轮把先前应下的差事当面办成交付了，填那件差事的原话关键词；"
                                   "没有则空字符串"}
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
    if prompt.get("player_dead"):
        lines.append("【玩家已死】玩家已经死了，此刻是一缕无形的视角：任何人都感知不到玩家。"
                     "把这个世界在没有玩家之后如何继续，具体地写给玩家看。")
    if prompt.get("sandbox"):
        lines.append("【无尽沙盒】这个世界没有终点，不要收束剧情，不要总结抒情。")
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
    if "self_state" in d:
        out["self_state"] = str(d.get("self_state") or "").strip()
    if "self_intent" in d:
        out["self_intent"] = str(d.get("self_intent") or "").strip()
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
            "★建议只能落在【当前地点、此刻在场的人、可去的地方】上——绝不要提任何不在场的人、"
            "不在眼前的东西。不要剧透隐藏真相，只点方向。"
        ) + _lang_rule(prompt)
        u = (
            f"你（{pc or '主角'}）此刻在：{ctx.get('place') or '（未知地点）'}\n"
            f"你刚才对{ctx.get('speaker','对方')}说：{ctx.get('player_input','')}\n"
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
            resp = httpx.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json={"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": u}], "max_tokens": 8, "temperature": 0.0},
                timeout=15,
            )
            resp.raise_for_status()
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
               "让TA感觉被点名、被看见，而不是被客套地接待）。两行都不要用破折号。")
        try:
            resp = httpx.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json={"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": "输出那两行："}], "max_tokens": 140,
                      "temperature": 0.9},
                timeout=20,
            )
            resp.raise_for_status()
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
        sys = ("你在为互动剧情游戏生成一段【玩家不在场时】两个角色之间发生的小事，"
               "并把它压成一句会在街坊嘴里流传的传闻。\n"
               f"甲：{a.get('name','')}（{a.get('role','')}）{a.get('persona','')}\n"
               f"乙：{b.get('name','')}（{b.get('role','')}）{b.get('persona','')}\n"
               f"两人的交情：{prompt.get('stance','')}；事发地：{prompt.get('place','')}\n"
               "只输出两行：\n变化：近 或 僵 或 无（这件事让两人关系更近/闹僵/没变化）\n"
               "传闻：一句话（30字内，像闲话——谁听见谁看见了什么，具体、有画面，不用破折号）")
        try:
            resp = httpx.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json={"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": "输出那两行："}], "max_tokens": 80,
                      "temperature": 0.95},
                timeout=20,
            )
            resp.raise_for_status()
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
               "只输出这句话本身，不要引号、不要旁白。")
        try:
            resp = httpx.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json={"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": "你的告辞："}], "max_tokens": 40, "temperature": 0.9},
                timeout=15,
            )
            resp.raise_for_status()
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
            resp = httpx.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json={"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": u}], "max_tokens": 90, "temperature": 0.9},
                timeout=20,
            )
            resp.raise_for_status()
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
            f"你们此前的经历（你的记忆）：{(prompt.get('memory') or '')[:400]}" if prompt.get("memory") else "",
            (f"TA不在你身边，此刻正通过{device}和你【实时通话】。你听得到TA的呼吸和背景音，"
             "TA也听得到你的。你说出来的是口语，一句一句，可以停顿、可以叹气、可以突然沉默。"
             if call else
             f"TA不在你身边，是通过{device}给你捎话。你在忙你自己的事，回不回、回多少、什么语气，"
             "全凭你此刻的心情和你们的关系。"),
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
        u = ((f"你们此前的往来：\n{tail}\n\n（电话接通了，TA刚说了最后那句。）你开口说什么？\n"
              if call else
              f"你们的消息记录：\n{tail}\n\n（TA刚发来最后那条。）你现在回什么？\n")
             + "最后另起一行，写：好感：一个整数-2~2（这几句话让你对TA更近还是更远）；"
             "心动：一个整数-1~2（仅当TA的话让你心里一动）。")
        try:
            resp = httpx.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json={"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": u}], "max_tokens": 240, "temperature": 0.9},
                timeout=25,
            )
            resp.raise_for_status()
            txt = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            return {"msgs": [], "closeness": 0, "romance": 0}
        import re as _re
        dc = dr = 0
        msgs: list[str] = []
        ambient = ""
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
            elif ("已读" in s or "沉默" in s) and len(s) <= 6:
                msgs = []
                break
            else:
                msgs.append(s.strip("「」\"'")[:120])
        out: dict[str, Any] = {"msgs": msgs[:3], "closeness": dc, "romance": dr}
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
            resp = httpx.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json={"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": "写这封信（第一行标题，空行，正文）："}],
                      "max_tokens": 420, "temperature": 0.9},
                timeout=30,
            )
            resp.raise_for_status()
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
            resp = httpx.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json={"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": u}], "max_tokens": 220, "temperature": 0.95},
                timeout=25,
            )
            resp.raise_for_status()
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
        try:
            resp = httpx.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json={"model": self._model, "messages": [{"role": "system", "content": sys},
                      {"role": "user", "content": u}], "max_tokens": 260, "temperature": 0.9},
                timeout=25,
            )
            resp.raise_for_status()
            txt = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            txt = ""
        if not txt:
            return {}
        return {"beats": [{"type": "description", "speaker_name": None, "text": txt}],
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
            resp = httpx.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json={"model": self._model,
                      "messages": [{"role": "system", "content": sys},
                                   {"role": "user", "content": u}],
                      "max_tokens": 120, "temperature": 0.95,
                      "response_format": {"type": "json_object"}},
                timeout=25,
            )
            resp.raise_for_status()
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
            resp = httpx.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json={"model": self._model,
                      "messages": [{"role": "system", "content": sys},
                                   {"role": "user", "content": f"世界观：{wv}"}],
                      "max_tokens": 420, "temperature": 0.9,
                      "response_format": {"type": "json_object"}},
                timeout=30,
            )
            resp.raise_for_status()
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
        sys = ("你在为一个互动剧情游戏写【玩家暂时离开】时的收尾旁白。写1~2句第三人称旁白，"
               "留一个让人惦记的钩子：在场的某人欲言又止、一个反常的细节此刻才被注意到、"
               f"或一句没说完的话。{tline}要具体可感，不要总结、不要抒情空话、不要预告。"
               "只输出旁白本身。" + _STYLE_PUNCT + _lang_rule(prompt))
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
        if prompt.get("sandbox_cast"):
            return self._sandbox_cast(prompt)
        if prompt.get("world_news"):
            return self._world_news(prompt)
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
        player_input = prompt.get("player_input", "")
        history = prompt.get("history") or []

        is_observer = bool(prompt.get("observer"))
        messages = [{"role": "system", "content": system}]
        if not intro and not transition:
            hist = history[-14:]  # recent turns for continuity (matches MEMORY_WINDOW)
            if is_observer:
                # 👁 god mode: the viewer's lines are STAGE DIRECTIONS, never audible —
                # mark every one (current AND past) so no character ever "hears" them
                hist = [dict(m, content=f"（画外引导，场景里无人听见：{m.get('content', '')}）")
                        if m.get("role") == "user" and m.get("content")
                        and not str(m.get("content", "")).startswith("（画外引导")
                        else m for m in hist]
            messages += hist
        # observe/intro/transition is a one-off narration; nudge with a neutral cue
        cue = ("（开场）" if intro else "（进入新的一幕）" if transition else
               "（观察四周）" if not prompt.get("observe_target") else "（打量这个人）")
        user_content = player_input or cue
        if is_observer and player_input:
            user_content = f"（画外引导，场景里无人听见：{player_input}）"
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
        said_appended = False
        for s in (prompt.get("said_this_turn") or []):
            if s.get("text"):
                sp = s.get("speaker") or "旁白"
                messages.append({"role": "assistant", "content": f"{sp}：{s['text']}"})
                said_appended = True
        if said_appended:
            # RE-ANCHOR whose turn it is. Without this, generation continues the assistant
            # chain conversationally — e.g. the primary just asked the PLAYER a question, so
            # the "natural next line" is the player's ANSWER, and a member speaks it as if
            # it were their own (the 十二少-answers-for-the-player bug). A closing user-role
            # cue breaks that continuation: the model now responds to the cue AS ITSELF.
            pl = (prompt.get("persona") or {}).get("name") or "对方"
            messages.append({"role": "user", "content":
                             f"（该你了：只以「{speaker}」自己的身份接话。上面若有人向{pl}发问，"
                             f"要由{pl}自己来答——你绝不能替{pl}作答。不想搭话就保持沉默。）"})
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
