# 🧭 引擎功能全景（2026-08-17 盘点）

六个 subagent 分域只读扫过 `apps/api/app/engine/`、`apps/api/app/routers/`、`docs/`，逐条核对代码位置后合成本文，不是从文档或记忆里转抄的。
更新方式：重跑同一套六域盘点 prompt（core/social/sandbox/gameplay/presentation/authoring），再合成覆盖本文件；不建议手工增量改，容易和代码脱节。

## ⚙️ 作者可配置面速查

给问卷设计当弹药库：下面把全书 138 条带旋钮的功能，按旋钮落在哪一层拆成四类。同一功能的完整白话说明在下面各域表格里，这里只留「叫什么旋钮」。

### 剧本字段（作者在剧本 JSON / 工坊表单里直接写的字段）

**角色卡**：voice_print 语言指纹、act_pace/sense_focus/emote_form 表演指纹三维、examples 台词范例、traits 性格三轴、fear/line 软肋与底线、known_facts 已确知、gender/age_band 性别年龄档、species 物种标记、bio_layers 分层小传、rel_start 关系起点、opening_line 开场白定制、relation_default/relation_allowed 关系模式库档位、love_style 防御风格/追法、ties NPC关系网、life_goal/wants 活目标台账、eq_style EQ风格、presence/appears_from_act 在场离场骨架、schedule/home_location_id 位置级联与作息表、faction_id 阵营声望、device_peek 偷看设备素材、items 随身背包、wants 扮演者目标、voice={id,speed,model} 台词播放键。

**剧本顶层/结构**：story.clock 大限倒计时、story.dooms[] 预定命运、act.time 幕锚时间、location.unlock 地点解锁闸、story.endings[] 结局评定、acts[].title/opening 幕间演出、acts[].choice 幕抉择卡、acts[].advance 幕硬门推进、acts[].events[] 幕事件触发、story.verdict 指认结案、story.pressure 压力表、story.threat 猎手系统、story.sanity 理智账本、story.rules[] 规则怪谈、locations[].props[] 现场搜查、story.factions 阵营声望、story.cover_url 自动封面手填优先、story.style 文风注入、story.language="en" 语言合同、card.visibility 角色卡库可见性、item_new 物性串（效果\|冷却\|次数）。

**秘密/线索**：secrets[].fragments[].unlock 五维解锁条件、.cover 掩护谎言、.known_by_character_ids 知情人名单、secrets[].sensitivity 敏感度、fragments[].retrieval_key 追问计数、fragments[].unlock.location_id 到场即察、unlock.device_of 偷看设备解锁位。

**手机**：phone.apps 银行App开关、story.phone.enabled 短信总开关、story.phone.apps 朋友圈、story.phone{device,apps} 设备换皮。

### tuning 灰度旗（`story.tuning`，PATCH /stories/{id} 写入，未知键忽略，手册见 docs/tuning.md）

时间/节奏：turns_per_slot 虚构三段钟（0=关）、real_clock 现实对齐钟、return_gap_hours 回归问候阈值、letter_away_hours/initiate_cooldown 离线脉冲。
输入/判定：dice 命运骰总开关（做-通道与 d20 判定共用）、opening_player_first 玩家先开口、physics_guard 物理哨兵。
关系账：close/rom/trust_step_min/max 与三条 taper_den 关系三轴步进递减、friend_t/enemy_t/flirt_t/lover_t/lover_close_min 档位阈值、rel_events 事件记账开关、pushpull_give/hold 推拉相位、follow_min_closeness 同行门槛、contact_on_meet/contact_ask_t/phone_share_min_closeness 通讯录与共享手机门槛、promise_keep_bonus/promise_break_cost 约定赏罚。
追求/暧昧：pursue_threshold/pursue_gap_turns 追求触发、pursue_player 全员反向追、mind_reader 心象仪、fallible 会露怯。
记忆/名场面：callback_every 记忆回扣频率、golden_cooldown/golden_chance 金色瞬间冷却与自动摇（chance 出厂即关）。
玩法开关：scene_ledger 场账本中切（默认0，试点剧本开）、troupe 导演场次单（默认全舰开）、key_choice_min/max 与 fate_auto_resolve 命运抉择卡与代点（出厂0=关）、world_event_every 事件自燃（出厂0=关）、confront_base/confront_cost 证据对峙、min_turns_per_act/act_backstop_div 幕软推进兜底、stuck_push/stuck_spell 卡关提示节奏、peek_drop_chance 偷看设备机会窗。
演出：vn_mode VN 演出总开关、sfx={enabled,map} 音效表、bgm={节拍/情绪:曲名} 配乐点位、bg_style/art_style 背景与全站画风圣经、snap_chance/snap_pref 随手拍频率（作者档/玩家档）。
双拍与总闸：plan_render 计划渲染双拍（覆盖 settings.plan_render，仅中文本生效）；灰度旗面板一次性列了 troupe/scene_ledger/vn_mode/dice/rel_events/physics_guard/fallible/pursue_player/real_clock/mind_reader/opening_player_first/turns_per_slot/golden_chance 十二个总闸键。

### sandbox 键（`sandbox.*`，只在无尽沙盒模式下生效）

enabled 总开关、real_time 现实同步（沙盒可显式关，非沙盒走 tuning.real_clock）、currency 货币名、start_money 开局盘缠（也是转生重置值）、era 年代字段（须先写世界观才收）、progression={name,ranks[]} 修为阶梯、default_powers 默认金手指、opening_visitor 开场访客、start_location 开局地点键（现状名不副实，见死角一节）。

### 引擎旗（代码级：改常量/环境变量/API 请求体，不在剧本编辑器里）

地图四把锁 LLM_MAP_WRITES / LLM_MINTS_PLACES / TYPED_MOVE / INVITE_MOVE、SEEK_AUTO_MINT 找人自动造人、SHARED_LIBRARY 共享创作库、cover.ENABLED 自动封面总闸（当前 False）、voice_styles.json 说话风格库条目（改文件不改剧本）、FIRST_GRANT=200 月石首充、CREATOR_SHARE_PCT=70 创作者分成、MAX_PRICE=9999 收费包定价上限、grants.access/start_money_bonus/powers/items 收费包发货白名单；环境变量 PLAN_RENDER / SMOKE_CHROMIUM / QA_STORIES / QA_TURNS / LP_METRICS；请求体参数 RunCreate.era/powers/perk/carry_card_id（二周目与开局金手指走这条路，不走剧本字段）、GalCreate.mode/style/art_style/mature/enrich、if_rev 乐观锁版本号、`--live <剧本名> <回合数>` 冒烟门人工验档、`POST /runs/{id}/living {on,hours}` 世界心跳。

---

### 🔁 核心：回合循环与世界状态（73 条）

| 功能 | 一句白话 | 位置 | 作者旋钮 |
|---|---|---|---|
| SSE逐拍推流 | 玩家发一句话后，角色台词一拍一拍实时流到屏幕上，另有 dice/clock/phone/peek/sugg/final 等专用事件流 | routers/runs.py (play 端点 sse())、engine/runtime.py run_turn_stream |  |
| 回合管线P0~P9 | 每回合固定十阶段：归一时钟→感知→确定性孪生→行动骰→解锁→选角→旁白→导演循环→场后结算→世界翻页，顺序写死在 docstring | engine/runtime.py run_turn_stream (11344起)、docs/engine-logic.md §1 |  |
| 计划渲染双拍 | 主答先出裁决 plan 再纯散文流式 render，首字更快且渲染拍碰不到状态；仅中文剧本生效 | engine/runtime.py plan_render_on/plan_render_call、docs/plan-render.md | story.tuning.plan_render（默认随 env PLAN_RENDER=关） |
| token逐字直出 | 渲染拍逐 token 发 SSE，玩家看到实时打字气泡，正式 beats 到达后替换 | routers/runs.py (event:token)、docs/plan-render.md |  |
| 回合锁+幂等键 | 同一存档双击/双开第二拍直接 409；client_turn_id 重放同一次点击不推进第二遍剧情 | routers/runs.py _turn_lock_acquire/play |  |
| 审计单 | 每回合模型申报的事件逐条记「采纳/驳回+原因」，随 final 下发，前端 console 可见 📋 engine audit | engine/runtime.py _audit/_finish_audit、docs/engine-logic.md §3 |  |
| 回归问候 | 玩家离开超过阈值小时数再回来，主答者会接起上次的话头打招呼 | routers/runs.py play、engine/runtime.py run_turn_stream(returning) | tuning.return_gap_hours（默认6） |
| 重说回溯 | 每个玩家拍存 state_before 快照，可回滚到任意一拍重说，连该拍生出的地点/角色/手机消息一起清掉 | routers/runs.py rewind_run、engine/runtime.py rewind_phone |  |
| 说-通道 | 普通对话输入，落成 dialogue 拍，NPC 应答 | routers/runs.py _channel_beat_type、engine/runtime.py |  |
| 想-通道 | 观察/内心独白：没有 NPC 应答、时钟不拨格、物品隔离转正也不跑 | engine/runtime.py (is_think、13424 not is_think) |  |
| 做-通道 | 动作输入落 description 拍；有风险的动作走命运骰（模型评险、引擎掷 d20，先于旁白动画） | engine/runtime.py _roll_check、P3 行动解算 | tuning.dice（1=开） |
| 导演-观剧拍 | ▶ 零输入让剧情自己往前演；服务端强制两拍最小间隔防脚本刷剧情 | routers/runs.py play (drive 防刷)、engine/runtime.py (drive→say空输入) | settings.drive_min_seconds；tuning.opening_player_first（1=第一句必须玩家说，▶也不许抢） |
| 上帝旁观模式 | state.mode=god：玩家隐身当导演，输入是给场上角色的指令，角色互相演对手戏 | engine/runtime.py (observer 分支 12308) |  |
| 附身模式 | 玩家扮演剧中角色，NPC 按那个人的身份立场对待你；你的身体位置是位置判定链第0级 | engine/runtime.py (player_character_id、char_position 第0级) |  |
| 亡者幽灵门 | 沙盒里玩家死后「说/做」被拒绝并降级成「想」，只剩旁观 | engine/runtime.py (ghost gate 11412) |  |
| 虚构三段钟 | 晨/午/夜三时段，每 N 拍拨一格，翻格出时段旁白、角色按作息换位 | engine/runtime.py SLOTS/_slot_narr/5c段(13419) | tuning.turns_per_slot（6；0=关钟） |
| 现实对齐钟 | 全舰默认：故事的日子和时段镜像玩家的真实墙钟与时区，「明晚见」就真是明晚；角色也知道现在几点几号什么季节 | engine/runtime.py sync_real_clock/_now_for/real_now_line | tuning.real_clock（1；0=退回虚构钟）、sandbox.real_time |
| 时钟单调护栏 | 改时区/跨时区旅行也不许时间倒流：day 和同日 slot 都只进不退，防约定翻面纪念日二触 | engine/runtime.py guard_clock_forward |  |
| 幕锚时间 | 剧本写「第3天夜里」，进幕时钟就真拨到第3天夜里（只往前拨；现实对齐剧本禁用） | engine/runtime.py align_clock_to_act | act.time={day,slot} |
| 大限倒计时 | 🕐 chip 显示大限还剩几天，跨进当天大声警告，睡过去就触发指定坏结局 | engine/runtime.py clock_cfg/clock_view/deadline_blown | story.clock{deadline_day,deadline_text,deadline_ending_id} |
| 时间跳跃 | 模型申报 time_skip（睡到天亮/次日）时钟直接拨到位，跳过的时段不欠账 | engine/runtime.py 5c段 (13431 skip) |  |
| 新一天自由活动 | 翻天的那回合 final 带 new_day，建议 chips 换成「去哪找谁」菜单，客户端出过场卡 | engine/runtime.py free_day_suggestions/13913 |  |
| 角色作息表 | 角色按幕+时段在不同地点上班下班，AWAY=这个钟点找不到人（下一时段自动回来） | engine/runtime.py _char_home/_schedule_says_away | character.schedule（linter 查 bad_schedule/bad_slot） |
| 世界自转新闻 | 现实对齐的沙盒里玩家离开几天，回来时世界已经发生了几条新闻 | engine/runtime.py mint_world_news/serve_news (11405) |  |
| 约定守约爽约 | 约定钟点人到场=如约（加好感+信任，戏自动转向TA）；时间滚过没去=爽约（扣分，TA下次见面会提） | engine/runtime.py make_promise/promises_view/12270赴约/13477爽约 | tuning.promise_keep_bonus(6)/promise_break_cost(4) |
| 每日回忆结算 | 翻天时判官通盘总结昨天与最亲的人的互动，打标签收进回忆册；「心动/甜蜜」只进TA的私人日记 | engine/runtime.py 14048段/_diary_add/_MEM_TAGS |  |
| 场账本中切 | 「一段连续的戏」升为显式状态：开场把在场角色钉在场址，作息拉不走正在陪你的人；人走净/超24拍/换地即收场 | engine/runtime.py _sl_open/_sl_close/_sl_settle、docs/scene-ledger.md | tuning.scene_ledger（默认0，试点剧本开） |
| 场内时钟凝滞 | 场开着时时段拨格最多推迟2次（一炷香的戏不会被拨过半天），收场一次性补拨，世界不欠账 | engine/runtime.py 5c段 (13440让位规则b) |  |
| 问答账 | 问过且答过的问题记账两天，渲染注入「不许换措辞再问」；未答的可追问但别抛新钩子 | engine/runtime.py asked_log/_asked_view |  |
| 已演动作账 | plan 申报本场花掉的标志性动作（递汽水），注入渲染禁止再演一遍；申报对不上正文会被驳回 | engine/runtime.py scene_spent/_sl_settle (12673注入) |  |
| 地图硬移动 | 玩家点地图节点 POST /move 换场，走已解锁出口可多跳，跟随者自动带上 | routers/runs.py move、engine/runtime.py apply_move/_route_exists |  |
| 换场唯一写口 | 所有真实换场收口到 commit_move：原子做拔钉收场/写位置/钉带路人，AST 测试禁止旁路直写 location_id | engine/runtime.py commit_move（守卫 tests/test_move_gate） |  |
| moved_to声明 | 模型申报旁白已把人走到某个在册已解锁地点→引擎让它成真（作者没写的通路也放行，解锁闸留着） | engine/runtime.py _settle_directed (10637) |  |
| 文实合一兜底 | 模型忘了申报但旁白把人写到了另一处已知地点门口→回合末扫描，唯一命中+落地动词+可达才落账 | engine/runtime.py settle_prose_arrival |  |
| 邀约确认条 | 角色申报 move_invite→引擎验目的地在册/解锁/可达→弹「跟TA去/留下」，玩家点了才真走 | engine/runtime.py invite_chip/move_request | 引擎旗 INVITE_MOVE=True |
| 邀约两步握手 | 上一拍角色开口相邀、这一拍玩家嘴上答应→立刻走过去（表态即销账，拒绝正则先查） | engine/runtime.py note_invite/take_invite |  |
| 打字移动已锁 | 输入框写「我去码头」不再改位置（TYPED_MOVE=False）；玩家说要走时弹「点右上角地图」toast 而不是装没听见 | engine/runtime.py player_wants_to_move/map_move_hint | 引擎旗 TYPED_MOVE |
| 地图四把锁 | 四面旗分管谁能改地图：模型写位置(开)/模型铸新地点(关)/打字移动(关)/邀约确认(开)，每面旗带实弹论证注释 | engine/runtime.py 320-400 | LLM_MAP_WRITES/LLM_MINTS_PLACES/TYPED_MOVE/INVITE_MOVE |
| 涌现地点 | 对话里同意去图外的地方→模型写地名判官提炼→真生成地点+双向接线+搬过去（当前被 LLM_MINTS_PLACES=False 整条冻结） | engine/runtime.py generate_and_move/player_move_emergent |  |
| 地点解锁闸 | 哪一幕能去哪由作者的 unlock 条件管；新变得可达的地点回合末旁白播报，绝不悄悄出现在地图上 | engine/runtime.py location_available/13406新去处播报 | location.unlock |
| 位置判定链 | 角色到底在哪按固定优先级裁：玩家身体>跟随>濒死倒地>猎手账本>被掳>赴约>钉子>作息>记账位置>开局地 | engine/runtime.py char_position |  |
| 角色钉子 | 「TA在那儿等你」落成显式钉（约见/带路/场账本共用），玩家离开那个地点自动拔钉放人 | engine/runtime.py char_pins/_drop_pins_on_leave/_heal_away_pins |  |
| 同行跟随 | 邀角色同行要交情够（敌对拒绝）；对话里TA亲口答应也算，之后换场自动带着走 | engine/runtime.py set_follow/accept_companion | tuning.follow_min_closeness（0） |
| 找人确认条 | 打听在册人物下落→弹「TA此刻在X，去吗」；提到册上没有的名字交导演裁决该不该有这号人（自动造真已关） | engine/runtime.py player_seek/seek_unknown/mint_sought_character | 引擎旗 SEEK_AUTO_MINT=False |
| 玩家改地图 | 玩家可手动加/改/删自己生成的地点、写地点备注（作者写的地点不可删改） | engine/runtime.py add_place/edit_place/remove_place/place_editable |  |
| 进出场旁白 | 时段/换幕导致人来人往绝不静默：来者有亮相拍，走者有告别戏（每拍限2条走戏，其余一句旁白） | engine/runtime.py entrance_beat/farewell_beats/exit_beat (13510) |  |
| 幕后戏与谣言 | 时段翻转时两个别处的 NPC 顺着各自议程生一拍事，关系互移，产出的谣言下场有人传给你一次 | engine/runtime.py offscreen_drama/serve_rumor/char_agenda |  |
| 见证式历史 | 每拍盖 present_ids，角色只记得自己在场的戏——信息不在角色间静默泄漏 | engine/runtime.py history_for、routers/runs.py beat_log |  |
| 旁白进记忆 | 旁白（占正文77%）也进角色记忆，玩家记得一起淋的雨角色也记得；plan-render 路加「旁白：」协议记号 | engine/runtime.py history_for/NARRATOR_TAG |  |
| 分角色摘要 | 逐字窗口（24条）外的戏按角色后台折叠成私人记忆摘要，窗口和摘要用同一把尺切分不重不漏 | engine/runtime.py memory_cutoff/_folds_async/MEMORY_WINDOW/MEMORY_BATCH |  |
| 折叠三道闸 | 后台折好的记忆下一回合合账：没折完不烧票、底稿被动过就弃单自愈、覆盖游标只进不退 | engine/runtime.py apply_pending_folds |  |
| 记忆回扣 | 每N拍角色主动提起一件真实旧事（时刻卡/大事记/守过的约优先），正文落地验真，连空3次升硬性要求 | engine/runtime.py callback_due/pick_callback_material/_callback_landed | tuning.callback_every（10；暧昧节拍加急到3） |
| 时刻卡回忆册 | 金色瞬间/每日回忆/大突破等高光收成带稀有度的卡进回忆册（上限40张），同时反哺回扣素材 | engine/runtime.py album_add/state.album |  |
| 金色瞬间 | 玩家自己点 ✨ 按钮：模型读最近40拍精写一张纪念卡并加好感；模型哑火不扣冷却 | engine/runtime.py golden_moment_now、routers/runs.py POST /golden | tuning.golden_cooldown（10）/golden_chance（0=每回合自动摇已关） |
| 玩家档案蒸馏 | 引擎按节拍后台蒸馏「你是个什么样的玩家」画像，下一回合合账，供活世界推送用 | engine/profile.py、runtime.py 13923 |  |
| 手账周摘要 | 玩家手账原文退出上下文后，跨一个游戏周后台蒸一次摘要再进提示词 | engine/diary.py、runtime.py 13927 |  |
| 关系大事记 | 初见在哪/赴约/金色瞬间等按角色记流水账（rel_log），是回忆和角色档案的素材底账 | engine/runtime.py rel_log/met_ids |  |
| 关系读后台判 | 「TA此刻怎么看你」由后台判官周期性判读，下一回合合账进提示词 | engine/runtime.py relation_reads_async/apply_pending_reads |  |
| 场记帧表 | 后台记录每场的画面帧（谁穿什么拿什么），发现冲突下一拍随锚点注入提醒（track_note） | engine/runtime.py track_frames_async/apply_pending_track |  |
| 剧本linter | 作者存稿/发布时结构体检：推进死锁/悬空引用/作息地点不存在等30+错误码，每条配人话修复指引 | engine/logic.py lint_story/HUMAN_FIXES、lint_stories.py |  |
| 运行时校验 | 生成后零 LLM 确定性查：缺席者闯入/泄露未解锁秘密/瞬移未解锁地点/复读开场白；scrub_beats 兜底删句 | engine/logic.py verify_turn/scrub_beats |  |
| 推理脚手架 | 模型开口前先在私有 inner_read 字段答一遍场面事实（在场者/知情边界），引擎阅后即焚不上屏 | engine/qwen.py _render_tool、logic.py 头注 |  |
| 逻辑守卫七检 | 主答稿过七道检（缺席/泄密/语言/金手指/heat回避/旁白人称/导演审稿+物理），违规带着错误清单重写一次，仍破就确定性消毒 | engine/runtime.py _logic_guard |  |
| 语言守卫 | 英文局漂出≥2个汉字整拍重写（玩家自己写中文豁免）；群戏成员走轻量版 _lang_guard | engine/runtime.py _lang_break/_lang_guard |  |
| 金手指守卫 | 玩家声明的能力是世界更高法则：正文敢写「失灵/被压制/免疫」就强制重写成无条件生效 | engine/runtime.py _power_break/_POWER_CORRECTION |  |
| 物理哨兵 | 这拍有动作/道具/伤势字眼才用 flash 快审硬物理矛盾（裤兜掏整瓶汽水/断肋骨扛货），探到就重生 | engine/runtime.py _physics_audit | tuning.physics_guard（1） |
| 导演审稿 | 确定性四检：死者开口/旁白与时段昼夜矛盾/整回合逐字复读上一回合/招牌动作景物跨拍复读 | engine/director.py logic_audit、runtime.py _recent_narr(NARR_LEDGER=8) |  |
| 同拍禁复读 | 主答替群戏成员写过台词后，那些人不再被叫起来说第二遍（确定性筛掉，不求模型自觉） | engine/runtime.py drop_already_spoken/_too_similar |  |
| 名字守卫 | 「谁看见」这类句子碎片不许成为人名/地名；EN 地名允许多词空格 | engine/runtime.py npc_name_ok/place_name_ok/_bad_place_name |  |
| 破折号消毒 | 所有出稿清洗破折号成句号/逗号（Yi 家规：少用破折号），一处 dedash 全线过 | engine/runtime.py dedash/dedash_beat |  |
| 命运抉择卡 | 区间随机武装、憋到高张力拍才弹的三选强制岔口，选项引擎验证且真执行（死亡/迁移/定向）；宽限耗尽代点默认关 | engine/runtime.py fate_generate/_apply_fate/13884 | tuning.key_choice_min/max（0/12，min=0关）、fate_auto_resolve（0） |
| 预定命运doom | 作者指定某夜某人会被带走，玩家可凭线索+交情预防、或当夜守在TA身边；被带走的人没死可找回 | engine/runtime.py 13555段 | story.dooms[{day,char_id,to,prevent...}] |
| 回合末事件流 | final 一次性带齐 state/场面/在场/建议/时钟/约定/审计/new_day 等30+字段，客户端一拍收全 | engine/runtime.py _final_payload (13981) |  |

### 💞 角色与关系（60 条）

| 功能 | 一句白话 | 位置 | 作者旋钮 |
|---|---|---|---|
| 语言指纹 | 角色说话的规律(句长/口头禅/绝不说的词/标点脾气), 每次生成注进「声音只属于你」段, 一句就能认出是谁; 生成新角色时也会自动出生一条 | schemas.py Character.voice_print; qwen.py:851 注入(另 :519 声纹耳语复读); runtime.py:10864 新生自动指纹; qwen.py _voice_prints 存量补票 | character.voice_print |
| 表演指纹三维 | 管动作/感官/描写而非台词: 行动节奏、感官侧重、情感表达形式; 情绪浓时放满、日常轻描; Studio 有「AI补全表演指纹」批量起草 | schemas.py act_pace/sense_focus/emote_form; qwen.py:853 注入, :5056 批量起草 | character.act_pace / sense_focus / emote_form |
| 台词范例 | 随卡携带的 few-shot 台词, 语气句长分寸以此为准、绝不照抄原句 | schemas.py Character.examples; qwen.py:859 注入 | character.examples |
| 说话风格库 | 十几种「形象」腔调(抽象网虫/傲娇/中二/元气…), 每条含可直接贴 voice_print 的规律+台词范例+分场景素材, 给角色一秒套腔调 | engine/voice_styles.json | voice_styles.json styles 追加条目 |
| 性格三轴 | 外向/温度/主导 1~5 的可推理量, 给导演排冲突与主动权用, 散文人设仍是主体 | schemas.py Character.traits; runtime.py ensure_scene_brief 喂导演 | character.traits |
| 软肋与底线 | fear=被戳会失态但从不说破的软肋; line=无论关系多好都不跨的底线(一推就破的角色不可信), 随卡进每次生成 | schemas.py fear/line; qwen.py:731-733; runtime.py:12560 speaker_card | character.fear / character.line |
| 已确知 | 授权这个角色确切知道的玩家/局势事实; 此外关于玩家的私事只认TA亲口说过的, 拿不准就说不知道——治「现编玩家周三休假」 | schemas.py known_facts; qwen.py:865-869 知识边界条款 | character.known_facts |
| 性别年龄档 | 称呼与代词(他/她、哥/姐)从卡上走不再让模型猜名字; linter 守卫班底多样性(3人以上全同性别/同年龄段会亮灯) | schemas.py gender/age_band; logic.py:158 多样性守卫 | character.gender / age_band |
| 物种标记 | 非人角色(猫/犬/龙)立绘与头像提示词据此换词, 防止「布偶猫背后站个男青年」; 也用来跳过立牌姿势 | schemas.py species; sprites.py:267; routers/runs.py:2672 | character.species |
| 分层小传 | [{closeness_min,text}] 好感每过一档解锁一层过往, 档案卡展示已解锁层+下一层门槛的钩子——认识一个人本身就是收集玩法 | schemas.py bio_layers; runtime.py:9909 解锁与tease | character.bio_layers |
| 关系起点 | 作者写角色开局对玩家的 closeness/romance/trust, 压过引擎默认(5/0/10); 只种未建账的角色, 处出来的关系绝不被覆盖 | schemas.py rel_start; relationships.py new_scores_for; runtime.py _ensure_npc_rel 落账 | character.rel_start |
| 开场白定制 | 作者写死TA对玩家说的第一句话, 引擎原样上台, 模型只围绕它写动作 | schemas.py opening_line | character.opening_line |
| 角色卡库 | persona 子集(人设/指纹/小传/范例…)可存卡库、跨剧本导入; COPY 语义, 改卡不追改已导入的剧本; 可公开分享 | schemas.py CharacterCardInput; routers/cards.py | card.visibility |
| 关系三轴账 | 每角色对玩家 亲近(-40..100)/心动(0..100)/信任(0..100) 三本账; 每回合步进钳制、越高涨越慢(增益递减)、信任慢建快塌 | engine/relationships.py apply_deltas | tuning.close_step_min/max, rom_step_min/max, trust_step_min/max, close_taper_den, rom_taper_den, trust_taper_den |
| 关系模式库 | 八档原型(陌生人/长辈/小辈/同级/朋友/暧昧/恋人/敌人)各带行为剧本注入; 档位由分数+作者允许集推导, 不许跳档或落进作者禁的档 | engine/relationships.py ARCHETYPES / derive_mode / playbook_block | character.relation_default / relation_allowed; tuning.friend_t/enemy_t/flirt_t/lover_t/lover_close_min |
| 事件记账制 | 不许每句打分: 模型只申报关系事件(交心/帮衬/心动/和好/冒犯/争执/越界), 分值/冷却由引擎法条表定; 正向带冷却防刷分, 负向零限流; 手机等场外通道每角色每日正向封顶4分 | runtime.py _REL_EVENTS(:301) / _offscene_rel_budget(:7869) | tuning.rel_events (1=on, 可关回每句判) |
| 关系判官 | 第3拍首判、之后每6拍后台重判「TA此刻心里把你当什么」(mode/feeling/why), 上下文盖过算术——算术说朋友, 判官可说面和心不和; 见过面就必有关系不留空边 | runtime.py relation_of / relation_reads_async / RELREAD_FIRST(:14135) |  |
| 撩拨手艺包 | 朋友/暧昧/恋人档注入张力手艺: 推拉留白、心动落具体小动作、离场必留具体钩子(期待感); 忌油腻忌摊牌 | relationships.py _CHARM_PLAYBOOK / _HOOK_CRAFT |  |
| 成人向手艺 | 18+ 局每档追加吸引力/调情/亲密技巧+感情进展节奏(每次亲近比上次多走半步, 记得里程碑); 尺度由人设与心意决定不由档位决定 | relationships.py _MATURE_PLAYBOOK / _MATURE_ARC (state.mature 时生效) |  |
| 主动手段库 | 按关系档给「TA主动推近关系」的战术(长辈考校/朋友托付/暧昧制造独处…); 陌生人阶段有心思的走追求阶梯, 铁律不派差事使唤 | relationships.py _TACTICS / _COURT_LADDER / approach_block |  |
| 称呼负面清单 | 按档下发禁令: 禁查户口式连问、禁堆糖堆表情、非恋人禁摊牌表白、称呼亲密度按档查表封顶(朋友档禁「宝贝」) | relationships.py negative_list / _ADDRESS_CAP |  |
| 防御风格 | 傲娇/冷感慢热/回避型/占有欲/直球五款「难追法」, 风格 playbook 常驻角色 prompt; 引擎管推拉时机, 模型只管措辞 | relationships.py LOVE_STYLES; runtime.py:12526 注入 | character.love_style |
| 暖后回撤 | 关系升档或名场面后引擎记 warm_peak, 下次见面(两天内)演一次风格化回撤——「昨天那么好今天怎么冷了」是规则不是模型心情; 追求拍当帧压掉回撤防指令互斥 | runtime.py:8556/10583/13158 落账, :12529 消费 |  |
| 今日心气 | 每角色每天确定性掷 -1/0/+1 心气, 当天稳定跨天翻面; 心气差好话打折坏话加倍——好感像真人一样忽高忽低 | relationships.py day_mood / temper; runtime.py:10550/12695 |  |
| 信任行为化 | 信任读数翻成行为指令喂 prompt: ≥70 可交底托付, <25 设防; 「亲近高信任低」单列(嘴上热心里防)——卧底/悬疑戏的原材料 | relationships.py trust_note |  |
| 推拉节拍机 | 引擎控制的给糖×3→收着×1→补偿(1) 相位循环, 禁止模型自己权衡冷热(必趋同讨好); 相位归引擎措辞归模型 | relationships.py pushpull_tick; runtime.py:12614 | tuning.pushpull_give / pushpull_hold |
| 关系白话卡 | 关系网卡片上零数字的白话总结(有过程感), 素材全取自档位名/感受/大事记等人话——无密可泄; LLM 写+指纹缓存, 兜底不占缓存位; 写了数字整句弃用 | relationships.py rel_brief; routers/runs.py:2389 |  |
| 差一步升档 | 算出这个角色最近的「值得要的」关系升档还差多少(先交朋友再谈心动), UI 显示「差一点就到暧昧」的每日拉回钩子 | relationships.py next_tier; runtime.py relations_summary |  |
| 关系大事记 | 每角色一条时间线账本: 初见/送礼/受伤/表白/爽约/揭秘/名场面…档案卡可回看, 也是回忆册与判官的素材 | runtime.py rel_log(:8459), state.rel_log |  |
| NPC关系网 | 作者在卡上写 ties(对某人立场-2..2+标签), 种入方向敏感的活网(A眼中的B ≠ B眼中的A); 台上事件与幕后戏都能让边演变并留log, 演变过的边不被重种 | schemas.py ties; runtime.py _ensure_npc_rel / npc_stance / apply_npc_shift | character.ties |
| 关系网视图 | 玩家可打开的关系图: 认识的角色为节点、npc_rel 立场为边(带演变史), 未见过的人绝不泄漏 | routers/runs.py:2315 GET /runs/{id}/relweb; runtime.py npc_ties_of |  |
| 幕后戏谣言 | 钟点翻转时, 两个同在别处的 NPC 有一拍自己的戏: 立场动一格、生成一条谣言, 由玩家下一场里的某人转述一次(只传一次) | runtime.py offscreen_drama / serve_rumor |  |
| 活目标台账 | 每角色引擎持有的人生目标账本 {goal,stage,obstacle,step,log}: 从 life_goal/wants 种入, 离屏戏与心跳推进 stage, 办成一件事是这个世界的历史; 对白记得最近的动静 | runtime.py char_agenda(:2113) / agenda_advance; schemas.py life_goal/wants/agenda | character.life_goal / wants (wants 优先于旧 agenda) |
| 冲突矩阵 | ties 立场 × 双方目标的确定性交叉, 算出「阿娣的债撞上细辉的名单」式火花, 供导演挑进场次单 | runtime.py conflict_pairs(:3100~) |  |
| 追求系统 | 心动过线(默认4)的角色开追求台账主动追玩家: 六阶节拍(留意→借口接近→小殷勤→邀约→心迹渐显→表白), 一游戏日一拍+回合间隔; 单追求者锁(同时只一位); 三次明拒死心(退火+记疤永不再启); 表白拍立抉择卡, 拒绝直接死心 | runtime.py COURT_STAGES(:6008) / court_tick / court_directive_for / court_apply_response / _court_die | tuning.pursue_threshold (0=关) / pursue_gap_turns |
| 风格化追法 | 每款 love_style 有专属追求措辞指令(傲娇的殷勤全用借口包装, 冷感的动作比话多), 不加新字段 | runtime.py _COURT_STYLE(:6018) |  |
| 全员追玩家 | 反向后宫旗: 所有角色透过各自人设吊系地追玩家(冷的人冷着追), 欲擒故纵不倒贴; 恋爱本开恐怖本别开 | runtime.py DEFAULT_TUNING:290; qwen.py:876 底色条款 | tuning.pursue_player (默认0) |
| 约定系统 | 角色和玩家约未来的钟点+地点(挂顶栏), 赴约加好感、暧昧/恋人档的约定演成正经约会名场面; 爽约掉亲近塌信任(-5)且TA捎带刺的话; 每角色同时一单、全局最多3单, 拒收留审计痕; 约的地点按TA未来作息校验; 死亡自动作废 | runtime.py make_promise(:5634) / promises_view / open_promise_of / :13477 爽约结算 | tuning.promise_keep_bonus / promise_break_cost; turns_per_slot=0 时整个系统关闭 |
| 玩家行程 | 玩家在日历写「周五考试」, 公开的(told=all)角色会顺着关心, 日子过了在意你的人主动问一句结果(问过即翻篇); 私密的绝不入戏 | runtime.py player_events_view / player_diary_for_prompt(:5590); engine/diary.py 周摘要 |  |
| EQ表演宪章 | 共情基本功进宪章: 读出话底下的情绪先接情绪再接内容、话头绝不掉地上、随口细节记心上; 但怎么回应由人设定——冷硬的人读懂了也可以不软 | qwen.py:840-845 表演宪章 |  |
| EQ风格 | 每角色自己的读情绪/表情绪方式(冷的人有冷的体贴, 情商不等于嘴甜), 注入对白/短信/日记等全部生成点 | schemas.py eq_style; qwen.py:850; runtime.py 十余处注入 | character.eq_style |
| 情绪连续性 | 引擎存模型对玩家底层情绪的最新读数(player_emotion), 下一拍带回给角色——上一轮读出的委屈这一轮还记得 | runtime.py state.player_emotion(:166); qwen.py:829/2721 |  |
| 心象仪 | 气泡上显示角色此刻真实内心(口是心非可见), 玩家读得到TA没说出口的 | runtime.py DEFAULT_TUNING mind_reader | tuning.mind_reader (1=on) |
| 会露怯 | 治「角色永远占上风=下头」: 宪章常驻反完美话术锚+每4拍给主答者一记 off_balance(语塞/被将住/让玩家赢一手) | qwen.py:873; runtime.py DEFAULT_TUNING fallible | tuning.fallible |
| 玩家档案 | 角色给玩家建档: facts(跨角色引擎视角的习惯/雷点, 喂心跳不进对白)+by_char(每角色相处出的「TA眼中的你」, 只有在场见证者更新, 注入TA自己的对白); 第3个玩家回合首蒸、之后每6拍后台蒸 | engine/profile.py; 档案卡 impression 字段 runtime.py:9934 |  |
| TA的日记 | 每日结算挑当天陪你最多的角色写一篇日记(心动/甜蜜只住这里); 好感到暧昧/恋人档才解锁阅读, 锁着只报条数——日记本身是养成奖励 | runtime.py diary_view(:5084) / _heart_candidate; state.diaries |  |
| 角色私记忆 | 每角色只记自己见证的滚动摘要(memory_by_char)+名下事实账(knows), 不开上帝视角; 手机长对话溢出折进同一本记忆, 面对面时TA记得你刚发的短信 | runtime.py memory_by_char / _digest_phone_overflow / phone_recent_for_scene; gating.py build_context |  |
| 情绪残留 | 上一场散场时的情绪带进下一场(「那股气还没散」), 跨一整天自动冷却; 同场之内不自喂防复读环 | runtime.py _carried_mood(:2085), char_sim.mood |  |
| 导演场次单 | 每「场」(地点×时段×班底)后台生成一次 {戏眼,每人心事,主动权,暗流}, 切片注入各角色 prompt——群像有第三只眼排戏; 空单不缓存降级零行为差 | runtime.py ensure_scene_brief(:3159); qwen.py:975 消费; docs/troupe-design.md | tuning.troupe (1=全舰默认, 剧本可关) |
| 选角机制 | 谁来接玩家这句话由引擎选角(pick_responder 关键词五档优先级), 场次单的主动权建议参与排班 | runtime.py pick_responder(:3022) |  |
| 在场离场骨架 | presence=offstage 的角色存在但不可对话(鬼魂/缺席者); appears_from_act 晚入场; 死者出列; scene_characters=在场且在玩家当前地点(或同行)才可互动 | runtime.py _is_present(:1015) / present_characters / scene_characters(:2183) | character.presence / appears_from_act |
| 位置级联 | 「TA此刻在哪」唯一出口 char_position: 玩家身体>同行>濒死钉>作息表(作者是老板, 没排到=AWAY不可及)>已落账移动>开场地兜底; 作息表 [{from_act,location_id,slots}] 让世界自己动 | runtime.py char_position(:1947) / _char_home(:1873) | character.schedule / home_location_id |
| 文实同走 | 旁白写TA走了或TA台词说「我先走了」= 账本真离场(钉回家或AWAY), 邀请短语「跟我走」剥掉再判不误伤; AWAY 粘钉遇台上台词证据自愈回场 | runtime.py _settle_prose_exits(:9547) / _heal_away_pins(:9591) |  |
| 邀人同行 | 可邀角色一路同行(跟着你换场景), 只有敌对档拒绝——门槛从25砍到0因为中位一局只有4拍; 慢热本可调回 | runtime.py following; relationships.py can_follow | tuning.follow_min_closeness (默认0) |
| 阵营声望 | 对「人」有关系双轴, 对「势力」另有声望一轴(-100..100 五档): 帮这边对头反向记账; 声望只给成员底色, 个人恩怨仍归双轴——仇视阵营里可以有人偷偷喜欢你 | engine/factions.py; schemas.py faction_id | story.factions / character.faction_id |
| 活世界心跳 | 玩家不在剧情照走: 定时心跳推时钟、爽约当场落账(纯数学), 从最暖关系里挑人发主动邀约; 戏文押成词债, 玩家点开下一回合才补齐上演(无点击不推进) | engine/living.py; runtime.py settle_pending |  |
| 通讯录之门 | 照面即交换联系方式(陪伴链第一环不设门), 悬疑/恐怖本可关掉要「拿不到号」的封闭感; TA大方递手机给你看要暧昧/恋人档或亲近≥45 | runtime.py grant_contact_on_meet(:5737) / can_view_phone (relationships.py:462) | tuning.contact_on_meet / contact_ask_t / phone_share_min_closeness |
| 偷看设备 | TA离场遗落设备的机会骰(作者可用 event.peek_cid 写死), 浅翻看备注深翻解碎片, 失败被撞见掉好感、大失败设备永久上锁; 作者可写死 device_peek 素材当证物 | runtime.py:6210 起; schemas.py device_peek | character.device_peek / tuning.peek_drop_chance (0=关) |
| 信物记忆 | 送出的礼物成为TA随身的 keepsake, 档案卡可见、TA日后会记得并提起; 名场面/纪念日也进回忆册 | runtime.py:11005 keepsakes 落账, :9926 档案卡 |  |
| 应承保质期 | 角色应承的差事(intent)带时间戳, 3个时段没办完自动当办完——治「说过一次去码头, 此后条条短信都慢半拍」 | runtime.py _intent_stale(:7610), char_sim.intent |  |

### 🏕 沙盒：生存与经济（46 条）

| 功能 | 一句白话 | 位置 | 作者旋钮 |
|---|---|---|---|
| 沙盒总开关 | 剧本变成无尽沙盒：玩家开局自写世界观、没有结局、玩家自己的身体会坏 | engine/runtime.py sandbox_on() + docs/tuning.md §无尽沙盒 | sandbox.enabled |
| 现实同步 | 故事时钟就是墙上的钟：第N天=现实第N天、晨/午/夜按真实钟点，「明晚见」要等真明晚；沙盒默认开 | engine/runtime.py real_time_on()/sync_real_clock() | sandbox.real_time（沙盒可显式关）；非沙盒走 tuning.real_clock |
| 货币名 | 钱在这个世界叫什么（默认「元」），集市/银行/NPC台词全走这个称呼 | engine/runtime.py currency_of() | sandbox.currency |
| 开局盘缠 | 玩家开局余额（缺省100），同时是NPC身家和集市定价的基准数；转生也重置回这个数 | routers/runs.py create_run；engine/runtime.py ensure_npc_rank/market_view | sandbox.start_money |
| 年代字段 | 纯世界观文字（绝不进日期计算），喂给对白/社媒/书信/生图当年代常识；只在玩家亲手写世界观时收，自动前缀成【年代】句 | routers/runs.py:615-626；engine/runtime.py era_of() | sandbox.era / RunCreate.era |
| 修为阶梯 | 作者定境界体系名和层级表（4~12级）；没写的沙盒开新档时自动按世界观生成一条 | engine/runtime.py cult_cfg()/ensure_progression() | sandbox.progression = {name, ranks[]} |
| 默认金手指 | 玩家开局没填金手指时的保底能力表（至多4条） | routers/runs.py:678 | sandbox.default_powers |
| 开场访客 | 起点没人时，作者点名的角色亲自上门打照面（真移动+char_pins落位）；没点名按 relation_default 热度选 | engine/runtime.py:3503-3527；studio.html 有下拉配置 | sandbox.opening_visitor（角色id或名字） |
| 开局地点键 | 现状只被封面合成挑背景图和linter校验消费；真实出生点另有其路（见notes） | engine/cover.py:983；engine/logic.py:714-719 | sandbox.start_location |
| 修炼孪生 | 玩家输入「修炼/打坐/闭关…」当场涨本境进度%：连刷递减、行内点名服丹/灵石+12、灵气地点+4 | engine/runtime.py player_train() (~9115) |  |
| 资质抽卡 | 第一次修炼掷d20定终身资质（驽钝~天纵，训练倍率0.8~1.8），只播报一次，跨转生前的一世身份感 | engine/runtime.py _roll_aptitude()/_APTS |  |
| 突破仪式 | 进度满100才能突破：小境界d20≥6稳赢，大境界（圆满跨大境=天劫）≥12；失败倒扣进度、天劫roll≤3反噬见血；crit=顿悟留25%头款 | engine/runtime.py player_breakthrough() |  |
| 剧情炼化 | 剧里吞吸/炼化某股力量按命运骰结算修为：大成功翻倍、大失败经脉反噬倒扣8% | engine/runtime.py cult_absorb() |  |
| 申报进益 | 被传功/丹浴/顿悟等没过骰子的机缘由导演申报小/中/大，夹逼成+4/+10/+18（按资质缩放） | engine/runtime.py cult_declared_gain() |  |
| 离线温养 | 离开≥3小时回来修为自动小涨（每2小时×资质，单次≤18%，不破瓶颈）——回归永远有动静 | engine/runtime.py cult_offline_gain() (调用点~11574) |  |
| 境界碾压 | 战力=按大境界指数(1.9^n)增长的单一数字；物理类动作按境界降DC（至多-8）；提示词写死「境界即铁律」，NPC按境界差对待你 | engine/runtime.py cult_power()/cult_action_mod()/cult_anchor() |  |
| NPC同梯入座 | 每个NPC按同一阶梯判一次境界+口袋钱+一桩没人知道的暗线心事，只进TA自己的提示词（不开天眼） | engine/runtime.py ensure_npc_rank()/_own_rank_line() |  |
| 五维属性 | 沙盒首拍按「你在这个世界是谁」判一次力量/敏捷/体质/心思/气运（1~10），折进命运骰DC；力量还管物品拿不拿得动 | engine/runtime.py ensure_player_attrs()/ATTRS/_player_strength |  |
| 金手指承诺 | 玩家开局声明≤4条能力（每条≤40字），提示词标注「REAL in this world」，判定成功率把它算作真本事 | routers/runs.py:674-679；engine/runtime.py:12735/11808 | RunCreate.powers（回落 sandbox.default_powers） |
| 金手指护法 | 正文若写玩家点名的能力失灵/被压制/免疫，引擎判违规强制重写该回合：能力必须无条件全效，世界只许震惊忌惮不许抵消 | engine/runtime.py _power_break()/_POWER_CORRECTION (~3975, 4123) |  |
| 现金硬账本 | state.money 真账：花钱夹逼在余额内不许透支，每笔进带时间标签的流水（留20条） | engine/runtime.py book_money()/economy_on() |  |
| 银行App | 小手机里看余额/流水/收款人（见过面+有联系方式+还活着的角色）；沙盒不分年代全开，古风只是换皮叫「账房」 | engine/runtime.py bank_view()/phone_apps()；routers/runs.py GET /runs/{id}/bank | phone.apps（作者显式配最高优先） |
| 转账 | 给角色打真钱：落账+写进TA记忆+TA按性格回短信（谢/推辞/起疑）；拉黑中/没联系方式/余额不足都拒收 | engine/runtime.py bank_transfer()；routers/runs.py POST /runs/{id}/bank/transfer |  |
| 今日集市 | 每游戏日按世界观现生成6件带价的世界真货，当日缓存、次日重新上架；无经济账本的剧本直接报「没有市面」 | engine/runtime.py market_view()；routers/runs.py GET /runs/{id}/market |  |
| 集市购买 | 买=纯账本操作：扣钱+流水+入包堆叠（同名第二份qty+1）+audit；钱不够报差额 | engine/runtime.py market_buy()；routers/runs.py POST /runs/{id}/market/buy |  |
| 随身背包 | inventory 行=(物性卡模板tid, qty, detail)；附身角色开局自动带作者写的随身物；沙盒班底人手也带东西可送可换可抢 | routers/runs.py:704-708；engine/items.py add_stack | characters[].items |
| 确定性收下 | 「收下/接过/捡起X」正则孪生直接入包，模型隔轮重报同一件视为幻觉不重复入包 | engine/runtime.py _ACCEPT_RE_ZH/_inv_add() (~8667) |  |
| 寄存取回 | 「把X放在/藏在这里」落进本地点的stash账本，「取回X」回包——确定性双向孪生，东西不再凭空蒸发 | engine/runtime.py stash_items()/retrieve_stash() |  |
| 端详渗出 | 掂一掂/端详一件东西，物性卡（重量/体积/效果暗示）用世界的语言渗出，零LLM | engine/runtime.py examine_items()；engine/items.py WEIGHT_WORDS |  |
| 物品效果 | 效果先有账本后生效：heal走血阶阶梯（含给别人疗伤）、light写地点持久事实；未立账本的类型（cure）夹逼成无效+audit | engine/runtime.py _apply_item_effect()；engine/items.py EFFECT_TYPES；docs/item-effects-p3.md |  |
| 三级物真实度 | L0布景不登记 / L1场景在册（每地≤12件，导演申报）/ L2随身；未申报实体进隔离区候审，3游戏日不转正即弃 | engine/items.py scene_rows()/quarantine() |  |
| 两段式血阶 | 人人走 healthy→hurt→dying→dead：致命一击最多打到濒死并播「现在施救或许还来得及」，只有已濒死的才允许判死 | engine/runtime.py harmed/died 结算段 (~10756-10823)；docs/engine-logic.md |  |
| 玩家血条 | 沙盒里玩家自己同一套阶梯（player_harm判定字段），伤情注入提示词；死了=幽灵：说/做被引擎改判成旁观，只能看 | engine/runtime.py:10727-10755, 11411-11417；docs/tuning.md |  |
| 角色死账 | 死者进 dead_character_ids：退出同行、银行/电话联系人消失、与TA的每条约定逐条宣告「再没有人来赴了」 | engine/runtime.py:10810-10823 void_promises_of |  |
| 沙盒转生 | 死透后一键转生：新身体回同一世界——世界侧账本（事实/新闻/他人/死亡）全留，自己侧（钱物关系记忆手机）清零回开局盘缠；前世化作街头传闻，past_lives留5世 | engine/runtime.py reincarnate() (~1588)；routers/runs.py POST /runs/{id}/reincarnate + can_reincarnate:418 |  |
| 世界心跳 | 每run可开的服务端定时器：拨日、爽约当场扣关系、认识满月纪念日、最暖的人发起邀约——只做状态数学押词债，一个LLM都不跑（无点击不推进） | engine/living.py world_tick()；routers/runs.py living_heartbeat_pass() | POST /runs/{id}/living {on, hours 1~168}（默认24h） |
| 回归结算 | 玩家下次亲手点开的回合一次补齐≤4笔词债：缺席戏文入关系大事记、带刺短信、周年讯息、邀约写词成约；≤3条「你不在的时候…」播报 | engine/living.py settle_pending()/serve_living_news() |  |
| 现实推送 | 心跳产出敲真手机（Web Push）：纪念日>邀约>缺席留言，每跳至多一次；撞上玩家本地静默时段是改期到傍晚而非丢弃 | routers/runs.py _push_heartbeat_news()；engine/living.py defer_to_friendly_hour()；routers/push.py 订阅端点 |  |
| 世界自转 | 现实同步沙盒里玩家离开的每一天（封顶2条）世界自产一条新闻，由角色之口讲且只讲一次 | engine/runtime.py mint_world_news()/serve_news() (触发~11406) |  |
| 回归温差 | 回归拍在场角色的生活各自推进一步；离开≥48小时最暖的那个人会写一封真信 | engine/runtime.py offline_pulse() (~8383) | tuning.letter_away_hours（默认48） |
| 开局班底 | 开新档由LLM按世界观+玩家人设现造≤4人（带说话指纹/随身物/主角位，演刑警和演赌徒撞见的人不同），失灵保底一位「迎面而来的陌生人」；全员锚定在起点地点 | engine/runtime.py seed_sandbox_cast()/anchor_homeless_cast()；routers/runs.py:629 |  |
| 沙盒问卷本 | 问卷向导直接产出完整沙盒剧本：题材查表定货币与盘缠、金手指、修为阶梯、开场访客、起点地点一次配齐 | routers/stories.py:434-484 _SANDBOX_ECON |  |
| 二周目优势 | 走到过本故事任意结局才解锁的perk：故人（开局全员+8亲近）或直觉（命运判定+10%/骰DC-2） | routers/runs.py:724-736；engine/runtime.py PERKS/INSTINCT_BONUS (10003, 10266, 11827) | RunCreate.perk = veteran\|instinct |
| 带卡入局 | 铸出的人物卡带进新档，以「上一世的旧识」身份加入班底（同样要先通关一次才解锁） | routers/runs.py:756-774 | RunCreate.carry_card_id |
| 跨档残响 | 同剧本上一段人生的回声：当时暖过的角色带说不清的既视感（echo），玩家习惯档案facts跟人走；角色认知边界不破 | routers/runs.py:737-753 |  |
| 收费包发货 | 买过的通行包在建档时一次性结算：开局钱加成、额外金手指位（上限6）、开局物件 | routers/runs.py:709-723 owned_grants；routers/packs.py |  |

### 🎮 玩法模块与手机生态（61 条）

| 功能 | 一句白话 | 位置 | 作者旋钮 |
|---|---|---|---|
| 碎片五维解锁 | 秘密拆成分层碎片, 每层由 affinity_min/act_min/asks_min/trigger_event_ids/location_id 五条件全AND程序判定; 锁着的正文永远进不了提示词或向量库, 解锁粘性不回退 | engine/gating.py (iter_fragments/evaluate_unlocks) | secrets[].fragments[].unlock |
| 三态守卫 | 每碎片对当前状态分 reveal/hint/hide: 只差一个条件时 NPC 可用秘密标题吊胃口, 差多了自然搪塞装没事 | engine/gating.py (classify_guard/build_context) |  |
| 掩护谎言 | 层锁着时所有知情人统一说作者写好的同一套谎话, 真相或对峙揭开后自动作废 | engine/gating.py (build_context covers) | secrets[].fragments[].cover |
| 知情人名单 | 碎片只有名单里的角色开口能用, 空名单=旁白级人人可提 | engine/gating.py (_speaker_knows) | secrets[].fragments[].known_by_character_ids |
| 秘密敏感度 | 解锁 heavy 秘密扣5点理智、medium 扣2 (仅开了 sanity 的本): 窥见不该知道的要付代价 | engine/runtime.py (P4管线 ~12150) | secrets[].sensitivity: heavy\|medium |
| 追问计数 | 玩家话头命中秘密标题/retrieval_key 关键词就给该秘密记一次 ask, asks_min 门槛靠反复追问攒出来 | engine/runtime.py (_detect_asks) | fragments[].retrieval_key |
| 证据对峙 | 把已解锁碎片当面拍到当事人面前, 可见对抗骰(基础成功率+亲密/2): 赢了当场撬开该秘密下一层(绕过一切解锁门)但关系掉分, 大失败喂压力表; 对峙赢了还能直接满足幕门当场换幕 | routers/runs.py POST /confront + engine/runtime.py (confront_stream) | tuning.confront_base / confront_cost |
| 幕硬门推进 | 幕写了 advance (必查碎片/必发事件/好感线) 就只认程序判定 can_advance, 嘴炮推不动; 没写的幕走软推进(模型报或好感兜底), 但须呆满 min_turns_per_act 且一回合最多推一幕 | engine/runtime.py (can_advance / 结算期 P4) | acts[].advance{required_fragment_ids,required_event_ids,affinity_min}; tuning.min_turns_per_act/act_backstop_div |
| 进度清单 | UI 显示本幕必查线索的 ✓/○ 清单(只给净化标题绝不给正文), 地点锁的线索附「去X看看」变成旅行计划 | engine/runtime.py (act_progress) |  |
| 卡关提示 | 连续几回合没进展, 顶栏常驻一句「眼下最该弄清的是「X」」, 更久升级为点名全部未解话题 | engine/runtime.py (stuck 计数+hint, ~13351) | tuning.stuck_push / stuck_spell |
| 结局评定 | 作者结局按 condition(act_min/affinity_min/必查碎片/flags)评定, 择优 true>normal>bad; 达成只是里程碑世界继续开放, 只有死亡终局 | engine/runtime.py (evaluate_ending) | story.endings[].condition / kind |
| 大限时钟 | story.clock 定死第几天大限: UI 时钟片带倒计时, 跨入当天大声警告, 睡过头触发指定结局 | engine/runtime.py (clock_cfg / 5c时间流) | story.clock{deadline_day,deadline_text,deadline_ending_id} |
| 幕间演出 | 换幕播「✦第N幕·标题✦」分隔卡+承接剧情的过场旁白, 时钟自动对齐该幕设定时辰 | engine/runtime.py (build_act_transition / align_clock_to_act) | acts[].title/opening |
| 幕抉择卡 | 进幕弹作者写的关键抉择, 选项确定性落 flag/好感/指定角色关系增减, flag 可门结局; 选中的话当玩家自己的台词打出去 | routers/runs.py POST /choose + engine/runtime.py (choice_for_act/apply_choice) | acts[].choice{prompt,options[{id,label,flag,affinity_delta,character_id,closeness_delta,romance_delta}]} |
| 命运抉择 | 每隔随机N回合、等到高张力拍甩出模型生成+引擎验证的三选卡(kill/move/bond/rift/identity/fortune/timeskip), 选了引擎强制执行(真死人/真搬家/真破财), 选向成为导演8回合的深度0指令; 3回合不选可配命运代选 | engine/runtime.py (fate_generate/_apply_fate, 触发在 ~13884) | tuning.key_choice_min/key_choice_max (默认0=关) / fate_auto_resolve |
| 追求系统 | 心动过线的角色按6阶节拍主动追玩家(留意→借口接近→小殷勤→邀约→心迹渐显→表白), 单追求者锁, 一日一拍, 三次明拒死心永不再启; 各 love_style 有不同追法话术 | engine/runtime.py (court_tick/court_directive_for/court_beat_book) | tuning.pursue_threshold/pursue_gap_turns/pursue_player; characters[].love_style |
| 表白抉择卡 | 追到第6拍回合末弹「接受/拒绝」卡: 接受直升恋人线, 拒绝TA当场死心、心动清到暧昧线下并记疤 | engine/runtime.py (court_confession_pending/_apply_court_choice) |  |
| 指认结案 | 到指定幕解锁正式指认面板, 有限次数; 指对设 flags.verdict_solved(真结局拿它当门), 次数烧光触发作者的错判结局, 指认过程落成正文拍 | routers/runs.py POST /verdict + engine/runtime.py (submit_verdict) | story.verdict{prompt,options[{id,label,correct,text}],attempts,act_min,fail_ending_id} |
| d20判定 | 全引擎统一 d20: 天然20必成、天然1必炸, 差DC 3以内算「险成」(成功但有代价, fail-forward 治74%失败曲线); 骰面实时推给客户端演出 | engine/runtime.py (_outcome_of/_roll_check/_roll_dc) | tuning.dice=0 关 |
| 动作难度分级 | 做-频道11类动词(强攻/潜行/破闯/腾跃/追逃/欺瞒/威慑/巧手/卖艺/豪赌/炼化)引擎先定基础档, 模型只能±1档; 五维属性/气运/带伤/称手道具确定性改DC, 分类动作永远要掷 | engine/actions.py (classify/resolve_dc) |  |
| 幕事件触发 | 玩家话头命中事件关键词暂燃+导演复核才算真发生(只认已到幕的事件, 未来幕聊到也不引爆); 搜到挂 event_id 的道具直接点燃 | engine/runtime.py (_apply_event_triggers/_event_candidates) | acts[].events[]{id,what_happens} |
| 差事账本 | 对话/短信里应下的有偿差事落账(标题/报酬/限期), 办成真付钱、过期真黄掉; 目标条 errand 层两游戏日不办自动过期 | engine/runtime.py (quest_accepted/quest_done 结算 + 13501 过期) |  |
| 事件自燃 | 静场N回合后本幕作者事件自己烧起来, 出厂关, 剧本级可开 | engine/runtime.py | tuning.world_event_every (默认0) |
| 压力表 | 作者命名的仪表(暴露值/灵异逼近…): 模型判每回合增减、跨等级线播作者注记, 对峙大失败/噪音也喂它, 满100强制触发 trigger:pressure 的终局 | engine/runtime.py (pressure_cfg / 结算期) | story.pressure{name,hint,levels[{at,note}],ending_id} |
| 猎手系统 | 作者声明谁在哪几间巡逻, 引擎账本管一切: 每回合走一步(警觉≥2就BFS循声朝玩家来), 遭遇掷藏匿骰, 被抓走升级阶梯 请回→带伤→濒死→死; 提示词里挂「猎手实态铁律」不许模型让它乱现身 | engine/threat.py + engine/runtime.py (threat phase ~11800-12100) | story.threat{char_id,patrol,senses,cannot_enter,return_to,ladder,unfightable,cues{far,near,here}} |
| 噪音分贝 | 玩家每句话按词表定0~3噪音: 跑砸喊/打光=3引猎手, 潜行低语=0, 大失败必+1「失败会呼救」; 玩家可学会这套规则 | engine/threat.py (noise_of) |  |
| 张弛导演 | Alien-Isolation 式波浪恐怖: 压迫攒满12点强制猎手退场喘息几回合, 玩家舒服满6回合导演又把它满警觉派回来; 巨响能截断它的休息 | engine/threat.py (MENACE_HIGH/CALM_LIMIT) + runtime |  |
| 藏点学习 | 同一个藏身词(柜/床底/风管…)用第二次起被猎手记住, 藏匿DC越来越高 | engine/threat.py (HIDE_WORDS) + runtime (~11941) |  |
| 理智账本 | CoC-SAN 式: 目睹死亡/被抓/窥重秘/违守则扣, 安静回合回一点; 档位给所有DC加罚, 水线下旁白被授权每轮夹一处「极小的不对劲」不点破, 归零终局; 量表可整套换皮当饥饿/污染/嫌疑度用 | engine/sanity.py + engine/runtime.py (sane_delta) | story.sanity{enabled,name,start,regen,bands[{floor,label,dc}],ending_id} |
| 预定命运 | 约定之日有人被带走: 当天清晨警告一次, 玩家凑齐 prevent(碎片+亲密+flags) 或那晚亲身陪着就能救下; 被带走的不是死, 在 to 指的某处可找回 | engine/runtime.py (5f dooms ~13555) | story.dooms[]{id,day,char_id,to,text,warn_text,prevented_text,prevent{fragment_ids,closeness_min,flags}} |
| 规则怪谈 | 守则原文全文展示(允许自相矛盾); 写了 violate 条款的由引擎裁违规(关键词×地点×时段×频道)并确定性收账: 压力尖峰/扣理智/猎手当场转向+播作者后果文 | engine/runtime.py (P3.6 ~12099; journal 里展示) | story.rules[]{text,violate{keywords,channel},when{location_id,slots},consequence{pressure,sanity,threat_aggro,text}} |
| 现场搜查 | 做/看频道点名当前地点的道具名就翻查, 确定性无骰(物证靠亲手翻不靠运气): 掀出 detail、点燃事件、直接解锁证据碎片、take 的能拿走; 搜过的不重复 | engine/runtime.py (search_props) | locations[].props[]{name,detail,event_id,fragment_id,take} |
| 到场即察 | 移动落地那一刻, 解锁只差「人在这里」的碎片当场揭开并播「到了这里你才看清」发现旁白 | engine/runtime.py (discover_on_arrival) | fragments[].unlock.location_id |
| 偷看设备 | 「翻TA的手机」: TA离场且账本有新货才按概率开3回合机会窗(或作者用事件写死); 浅翻看备注名+各线程末句, 深翻全文+浏览器历史+未发草稿+device_of 碎片收成但DC更高; fail被撞见掉好感记仇, 大失败设备永久上锁 | engine/runtime.py (peek_attempt/_peek_cache) + engine/socialfic.py (filter_device_peek/device_extras) | tuning.peek_drop_chance (0=关); characters[].device_peek(act_min按幕锁); unlock.device_of |
| 共享手机 | 关系够近, 通讯录里出解锁位, TA大方把手机递给你看(无骰无代价), 内容与偷看共用缓存永远对得上; 第一次递记进TA的记忆 | routers/runs.py POST /character/{cid}/shared_phone + engine/runtime.py (shared_phone_view) |  |
| 短信 | 随时给认识的人发消息, TA带完整门控上下文用自己的声音回; 短信里追问也能撬开秘密(解锁全局粘性), 站TA旁边发短信TA会当场吐槽 | routers/runs.py POST /phone/{cid} + engine/runtime.py (phone_send/_phone_probe) | story.phone.enabled |
| 回信时机形状 | 引擎(不是模型)判回信六档时机 now/soon/later/next_slot/morning/never 和五形状 normal/word/long/burst/read: 延迟的词先写好押后送达(线程显示「已送达TA还没回」), 已读晾着留原因可追问、「稍后:」补偿延迟送到 | engine/runtime.py (_phone_beat/_phone_due/deliver_due_phone) |  |
| 短信落账 | TA在短信里答应的都是真的: 说「这就来」位置被钉到玩家处走进场, 应承差事进TA的行为账本, 定下的约会进约定账(爽约TA记仇那本) | engine/runtime.py (_apply_phone_judgments) |  |
| 来电 | 打给不在场的人: 语音台词+一句听筒里的背景音(TA在哪的真实线索); 作者作息说这个钟点找不到TA就真的无人接听, 判据与通讯录同一句 | routers/runs.py POST /phone/{cid}/call + engine/runtime.py (phone_call/_phone_unreachable) |  |
| 主动找你 | 确定性由头角色主动发短信: 约定将至提醒/被爽约的委屈/恋人分别余温(恋人直接拨来电话)/初见自我介绍/大事后关心/托办事项进度汇报; 每回合最多2条不轰炸 | engine/runtime.py (phone_deliveries/reachout_on_meet/reachout_after_event) |  |
| 离线脉冲 | 离开几小时回来, 最暖的心排队发消息(掷骰非保证+单角色冷却); 离开≥48小时最暖那位升级写一封真信进信箱 | engine/runtime.py (offline_pulse) | tuning.letter_away_hours / initiate_cooldown |
| 信箱 | 长信 app: 跨入恋人、久别重逢都会收到主题+正文的信, 未读角标; 与短信分开的慢热通道 | routers/runs.py GET /mail /mail/{id} + engine/runtime.py (mail_push/compose_letter) |  |
| 随手拍 | 角色消息按概率带一张照片(45%自拍走同脸种子, 否则眼前一景), 冷却账引擎管; 玩家自己0关/1少/2正常/3多四档调频率(生图花真钱) | engine/runtime.py (maybe_snap) + routers/runs.py POST /snap | tuning.snap_chance(作者) + snap_pref(玩家档) |
| 玩家发图 | 玩家在手机上传照片(≤5MB), qwen-vl 看图翻成「角色看见了什么」进提示词, TA真看得懂图再回复 | routers/runs.py POST /phone/{cid}/photo + engine/qwen.py (see_image) |  |
| 朋友圈 | 已认识角色的动态从活世界账本渲染(位置可印证/记得你俩刚发生的事), 账本指纹变了才发新帖零浪费; 点赞确定性+1好感(每帖一次), 评论TA亲声回(每游戏日限5条); 第一条是欢迎通告 | routers/runs.py GET /social + engine/runtime.py (social_feed/social_like/social_comment) | story.phone.apps |
| 玩家发帖 | 玩家自己发动态, 在场/关心你的角色看见、记进记忆、对白里会引用 | routers/socialfic.py POST /social/post + engine/socialfic.py (player_post) |  |
| 拉黑三档 | mute/block/removed: 静音只关角标信照收; 拉黑期来信非对称暂扣(TA视角发了你的手机没响), 解除按原时序回放; 拉黑还想转账/发消息会被人话拦下 | routers/socialfic.py POST/DELETE /character/{cid}/block + engine/socialfic.py |  |
| 世界论坛 | 匿名马甲论坛: 角色顶着马甲发帖(素材按幕解锁), 玩家可发帖引发回复; 恐怖本的规则怪谈味通道 | routers/socialfic.py GET /forum, POST /forum/post + engine/socialfic.py (forum_feed) |  |
| 银行app | 余额+流水+给角色转账: 真钱落账、TA的记忆和短信都知道这件事并按性格回应; 没有经济账本的本这个app不亮 | routers/runs.py GET /bank, POST /bank/transfer + engine/runtime.py (bank_view/bank_transfer) | phone.apps 含 bank |
| 日历app | 玩家记自己的行程(哪天/哪个时段/公开或私密, 上限20条): 公开的角色顺着关心, 日子过了在意你的人主动问结果(问过翻篇); 私密只是备忘绝不入戏 | routers/runs.py POST/DELETE /calendar + engine/runtime.py (player_events_view/player_diary_for_prompt) |  |
| 笔记app | 玩家亲手记/改/删的本子(上限12条), 角色看不见但它是主叙提示词的叙事罗盘: 相关细节和人物动向会有机会浮现; 零LLM后台调用 | routers/runs.py POST/PATCH/DELETE /notes + engine/runtime.py (player_notes_view) |  |
| 联系方式 | 默认见面即入通讯录(悬疑/恐怖本可关成要靠剧情挣); 通讯录行显示在哪/打不打得通/能不能看TA手机, 口径与地图完全对齐绝不多剧透一个字 | engine/runtime.py (grant_contact_on_meet/phone_threads_view) | tuning.contact_on_meet(0=关) / contact_ask_t |
| 设备换皮 | phone.device 把「手机」改叫口信/传呼机/水晶等(年代皮肤), apps 显式配开哪几个; 沙盒一律全开只换称谓 | engine/runtime.py (phone_device/phone_apps) | story.phone{device,apps} |
| 消息编辑 | 玩家可改自己发过的短信正文(标edited, 不重算当时的好感/解锁账), 改动进后续线程上下文 | routers/runs.py PATCH /phone/{cid}/msg/{mid} + engine/runtime.py (edit_phone_msg) |  |
| 线上线下互通 | 短信最近6条注入该角色下一场的提示词, 场上最近正文喂给短信/来电: 线上定的时间地点线下记得 | engine/runtime.py (sms_tail_line/phone_recent_for_scene) |  |
| 目标栈 | player>errand>self>act 四层目标各归各层, UI目标条读栈顶(state.goal只是镜像), 换幕不冲掉差事/自立目标; open条目永不静默消失 | engine/runtime.py (goal_push/goal_top/_trim_ledger) |  |
| 玩家自定目标 | 沙盒玩家亲手定目标压过一切、世界向它倾斜(进导演提示词); 「随机推荐」零LLM从活账本(没去过的地方/最暖的人/开着的差事/修为)长出来 | routers/runs.py POST /goal + engine/runtime.py (player_goal_set/player_goal_suggest) |  |
| 扮演者目标 | 扮演写了 wants 的角色时, 目标条显示TA自己的立场而不是幕目标(扮演谁立场就是谁的) | engine/runtime.py (goal_for) | characters[].wants |
| 物品效果 | 物性卡带 effects(heal进血条阶梯/light落地点事实)+consumable+uses; 模型报 item_used, 引擎守卫链(真持有/卡上有效果/目标合法)全过才落账, 消耗与成败解耦(满血用绷带白费也扣), 结算后确定性孪生拍点名因果 | engine/items.py + docs/item-effects-p3.md | item_new 物性串末三段 效果\|c\|uses |
| 物品变形 | 一物变他物走 item_transformed 一笔销n铸m原子交换(禁拆lost+gained); 销毁带个体籍的证物必须显式 destroys_clues, 世界记得玩家毁证 | engine/items.py + docs/item-effects-p3.md §3 |  |
| 悬念离场 | 中途离开(beacon只暂存不推进), 回来第一拍播〔上回〕闪回(用真实最近6拍写词); 中途弃局时给〔下幕预告〕只报下幕标题当钩子 | routers/runs.py POST /leave + engine/runtime.py (build_parting_hook) |  |

### 🎬 演出与媒体层（54 条）

| 功能 | 一句白话 | 位置 | 作者旋钮 |
|---|---|---|---|
| SSE演出事件流 | 每回合以 SSE 流下发约30种事件, 演出类有 dice/clock/phone/token/peek/beat(带sfx·fx·expr注记)/direct(BGM+色调)/newday/moments/achievements/ending 等, 客户端逐一演出 | routers/runs.py (sse 生成器 L1123-1318, 聊天模式 L2153) |  |
| 规则导演·每拍注记 | 零LLM确定性: 正文命中关键词→拍上挂 sfx 音效插点/fx白闪(一回合至多一次)/expr表情位, 同名音效一回合不重复 | engine/director.py TurnStage.beat_fx; runs.py L1171 挂到 beat 事件 | tuning.sfx = {enabled, map:{关键词:音效名}} (作者词表压过内置) |
| 回合演出单direct | 回合末一张 {bgm,tint,cue,mood} 演出单: BGM 四级优先选曲 + 全屏色调阶梯 danger>frail>night>none; 开档时 GET /runs/{id} 另给一份裸 direct | engine/director.py stage_turn; play.html #vntint 消费 | tuning.bgm = {节拍key或情绪key: 曲名} (作者点名不轮变奏、压过一切) |
| BGM曲库与变奏 | 11 种情绪标签曲库(甘茶の音楽工房), 同情绪多变奏按 地点+天数 salt 定曲(换地方换天才换曲); 变奏问磁盘不问表, 缺曲走 fallback | engine/director.py BGM_TRACKS/resolve_bgm/real_variants/pick_variant; 曲文件 static/scene/bgm/ |  |
| 乐师判官 | LLM 读实际剧情文字判曲 (track+pivot), 迟滞防抽风(无转折至少稳两回合才换曲), 曲名过白名单; 床笫/危机等硬状态引擎压过乐师 | engine/runtime.py settle_music (L2741) + _music_worker; director.stage_turn 装配 |  |
| 剧情节拍配乐 | 作者按「开场/暧昧/亲密/危机/高潮/落幕/日常」7 节拍点曲, 引擎从已有状态(结局/抉择/heat/压力/回合数)确定性认拍, 不新增字段不问模型 | engine/director.py STORY_CUES/cue_of/cue_menu | tuning.bgm["opening"/"climax"/"flirt"…] |
| SFX音效库 | 内置关键词→音效表约40条(敲门/雷/拔剑/施法…), 命中即随打字机播放且音乐自动闪避到45%; 心理惊悚无实体音效时心跳声顶上 | engine/scene.py _SFX; director.py _HEARTBEAT_RE; play.html playSfx | tuning.sfx.map 作者补本子专用词(剑鸣/拂尘等) |
| 场景分类器 | 纯关键词零LLM: 正文→{bg背景名,mood情绪,sfx,night}, 素材缺失客户端渐变/静默降级 | engine/scene.py classify_scene |  |
| 惊吓白闪 | 正文命中惊吓语法(尖叫/巨响/「猛地+撞击动词」)触发全屏白闪 0.42s, 一回合至多一次(阈下适应) | engine/director.py _FLASH_RE; play.html #vnflash/vnFlash |  |
| 骰子演出 | 冒险动作 d20 命运骰: roll 在旁白前先流出, UI 在舞台上动画展示骰面/DC/结果 | engine/runtime.py _roll_check/_roll_dc (L5216); play.html #vndice |  |
| 偷看设备peek | 玩家「做:翻TA的手机」→ 结构化手机视图(peek事件)直达手机壳UI; 有机会窗/上锁/被抓代价机制 | engine/runtime.py 手机翻看 (L6388); runs.py peek 事件 |  |
| 表情差分 | 喜怒哀惊四表情: 常态立绘上改图(微表情铁律不许崩相), 抠底+崩-gate体检后落盘 {cid}_{expr}.webp; 客户端按 beat.expr 换脸, 缺素材静默回落常态 | engine/sprites.py EXPRS/build_expr_pack/_intact; POST /runs/{id}/sprites/exprs (runs.py L2654) |  |
| 动作差分 | 挥手/抱臂/低头/伸手四动作位, 从模型已在报的 self_position 帧表认出, 动作压过表情; 双脚不挪防崩相 | engine/sprites.py POSES; director.py pose_of/POSE_ACTS |  |
| 立牌呼吸 | VN 立牌以 5.6s 周期做 0.6% 极轻缩放的呼吸动画 | play.html @keyframes vnbreathe (L900) |  |
| 眨眼与口型(gal) | gal 作品有闭眼帧(_眨)与张嘴帧(_口): 每隔几秒随机眨一下(E-mote丐版), 打字机进行中说话者嘴一开一合 | engine/gal.py BLINK/MOUTH (L515-528); galplay.html probeBlink/probeMouth/talkStart |  |
| 弹丸式立牌舞台 | 沙盒 VN: 宽画布横滑舞台, 背景 0.35x 视差+translateZ 真3D纵深, 说话者点亮回正并镜头平移居中, 纸板左右交替微斜, 拖拽带橡皮筋+惯性滑行 | play.html vnStageSync/vnSprite/vnStageClamp (L4850-5071) | tuning.vn_mode = 1 (整套 VN 演出的总开关) |
| 舞台双立绘(gal) | gal 播放器左右两槽, 最近两个开口的非主角各占一槽, 从 who 序列推导 | galplay.html stageSlots (L537) |  |
| enrich_tachie管线 | 原创角色按剧本画风圣经 t2i 出生立绘(Seedream 928*1664, story+cid 定 seed 同脸)→ingest三件套→表情差分; --restyle 用留档照片改绘防画风漂移 | apps/api/enrich_tachie.py; ingest_tachie.py 是验收图直上线的姊妹工具 |  |
| 智能搜图选角 | 影视IP角色 Tavily 搜剧照→选一张站得住的→动漫本改绘成剧本画风(写实本原样)→ingest; 玩家亲选的脸(generated=False)不动; 按人物重要性排预算 | engine/sprites.py smart_cast/_tavily_images/char_importance |  |
| 上传图三件套 | 上传人物图: rembg 抠底透底立绘 + 原图瘦身留档(_src/_photo) + 人形包围盒智能裁方头像; 旧表情差分自动作废 | engine/sprites.py ingest_upload; POST /runs/{id}/sprites (runs.py L2598) |  |
| 头像同脸捷径 | 有立绘的角色头像直接从透底立绘量 alpha 裁头胸窗, 零成本且与立绘绝对同脸, 不再另 t2i | engine/sprites.py avatar_from_base/_head_window |  |
| 每回合补脸 | 每回合都是回填机会: 缺头像/缺VN立绘的角色排队生成, 按重要性(主角位/恋爱位/作者亲写)先落地; 作者亲选的脸永不重画 | routers/runs.py _ensure_char_avatars (L294); sprites.rank_cast |  |
| 背景异步排队 | 单线程 worker 队列 t2i 地点背景(1280*720): 空镜铁律句尾压轴+生物负面词+广角三层景深; 消息先到图后台冲洗, 客户端 22 秒轮询补图最多8次 | routers/runs.py _img_worker/_enqueue_image/_spawn_location_bg/_bg_prompt; play.html paintBackground/bgRetry | tuning.bg_style (背景专用画风, 缺省回落 art_style) |
| 夜间背景 | 夜里客户端先试 {bg}_night.jpg, 404 回落白天版再叠夜色调; 仅是前端约定, 服务端无 _night 生成管线(素材手放) | play.html paintKeywordBg (L5799); packages/contract/FRONTEND.md L243 |  |
| 玩家重画背景 | 生成型地点玩家可点重画(授权地点仅作者可), 换图不出画风家族(剧本seed+递增位移), 一分钟限一次 | routers/runs.py regen_bg (L1550); 工坊侧 stories.py gen_bg (L1370) |  |
| 画风圣经 | 一世界一画风: art_style 开头压阵+邻近流派负面词封两头+稳定seed, 立绘/头像/背景/图鉴/封面三个出图口共用一份 | routers/runs.py _story_art/_bg_negative; sprites.portrait_prompt (四道保护, 全站唯一配方) | tuning.art_style |
| 背景兜底链 | 地点AI图→关键词预置图→情绪渐变三级降级, 每级404自动落下一级; 代际号防慢图盖新图 | play.html paintBackground/paintKeywordBg/MOOD_GRAD |  |
| 卡面缩略图 | 书架卡面按需压 860px webp 落盘永久复用(1.7MB冷开→几十KB), 压失败降级回原图 | engine/thumbs.py thumb_url |  |
| 自动封面(已关) | 用已有透底立绘+背景合成 galgame 盒绘(海报3:4烫字+宽幅16:9不烫字), 指纹判缺自愈, 三款版式; 现 ENABLED=False 全站关闭, 卡面退回地点背景图 | engine/cover.py (ENABLED L40, ALGO=d1); stories.py 四处 gate + 重画封面端点 (L1322) | story.cover_url (作者手填永远优先); cover.ENABLED 总开关 |
| 台词播放键 | 名牌/气泡旁小喇叭: 玩家点了才 CosyVoice 合成整句(花钱由玩家定), 服务端按句 sha1 缓存重播零成本; 无选角的角色不亮键; 选角读现行剧本, 换音色即刻全档生效 | POST /runs/{id}/tts (runs.py L858); engine/voice.py tts_line_cached; play.html armVox | characters[].voice = {id:音色, speed, model} |
| 语气音精灵 | 角色开口那一拍按导演 expr 注记播一声短叹词(嗯/哼/诶?!), 5类×2段×zh/yue/en 预生成; 缺素材404静默; 变体轮换定于文本不靠随机 | engine/voice.py SPRITES/gen_sprites_for; play.html voxSprite (L5723); 素材 /scene/voice/{voice_id}/ |  |
| CosyVoice选角表 | 工坊选角下拉: 22个预置音色带人话标签(粤语男仅 longanyue_v3 一个的硬限制), 只列语气音精灵已排齐的音色, 问磁盘不问表 | routers/stories.py VOICE_CAST + GET /stories/voice/list (L1234) |  |
| 声音克隆 | 作者上传 10~30s 人声样本→ffmpeg转16k wav→CosyVoice 克隆专属音色, 自动后台排整套精灵+返回试听; 样本注册完即删不留站 | engine/voice.py enroll; stories.py voice_clone (L1492)/voice_preview |  |
| 金色瞬间 | 玩家主动点✨按钮: LLM 认真读最近40拍写一段值得记住的戏, 涨关系+落回忆册+toast; 冷却制, 模型哑火不扣冷却 | engine/runtime.py golden_moment_now (L8495); POST /runs/{id}/golden (runs.py L1513) | tuning.golden_cooldown (默认10; golden_chance 已弃改玩家主动) |
| 时刻卡回忆册 | 双面收藏卡: 正面=发生地的艺术图+关键台词, 背面=摘句/日期/星级稀有度; golden/升档/约会/结局/暴击等8类自动落账(上限40), 手机壳「回忆册」翻面/系统分享/设壁纸 | engine/runtime.py album_add/_ALBUM_RARITY (L8470); play.html openAlbum/shareMoment (L3412) |  |
| CG时刻 | 稀有时刻(golden/breakthrough等)在 VN 里全屏亮相, 卡面取回忆册刚落账那张, 点按继续 | play.html vnShowCG/#vncg (L5213) |  |
| 时刻卡壁纸钉选 | 时刻卡的地点底图可钉为聊天背景(压过实况场景直到取消)或手机壳主屏壁纸 | play.html paintBackground pin (L5764)/setPhoneWall (L3114) |  |
| 成就系统 | 结局达成时按纯抽象条件判7种成就(真结局/零死亡/全真相/心动/两天通关等), 跨局存 StoryMeta, SSE achievements 事件 toast 亮牌, 选角页展示🏅徽章 | engine/runtime.py compute_achievements (L10011); runs.py _bump_story_meta (L1352); play.html L5988 |  |
| 万物铸卡 | 局内出生的涌现角色/地点/名场面铸成永久卡片收藏(id稳定去重), 角色卡可带进 NG+ 局 | engine/runtime.py mint_cards (L10048); play.html 卡片墙 (L2196) |  |
| 随手拍snap | 角色发消息按概率带自拍/照片: 有立绘走 i2i 改绘保脸(与表情差分同管线), 无底图 char_seed 定种 t2i; 消息即达图后台冲洗, 客户端重试直到图落地 | engine/runtime.py maybe_snap (L6859); runs.py _queue_snap (L251) | tuning.snap_chance (作者定这个世界该有多少照片, 默认12%) |
| 拍照频率档位 | 📷按钮循环玩家自己那一档(0关/1少/2正常/3多), 在作者 snap_chance 之上再缩放 | POST /runs/{id}/snap (runs.py L2544); runtime.snap_pref_of/set_snap_pref; play.html cycleSnap |  |
| gal编译播放器 | 识别拍→编剧拍→美术拍编译整本(40k字上限), 播放器只翻页: VN对话窗+名牌+打字机+点击/空格/回车推进+已读跳过+自动播放+回想log+好感账本真分歧结局 | engine/gal.py (build 管线); static/galplay.html (tap/toggleAuto/toggleSkip) |  |
| gal表情立绘 | gal 角色常态+喜怒哀每表情肖像, 同角色固定 seed 同脸; 差分在常态底上编辑生成防连衣服都换 | engine/gal.py EXPRESSIONS/差分提示词 (L510-545, L1124) |  |
| 文风注入 | 剧本级 style 字段作为「文风带」注入所有生成口(优先级高于通用文风习惯), 关系档「忌清单」负面清单(禁查户口/禁堆糖/称呼上限)同帧下发 | engine/qwen.py style_band (L751); runtime 各产地传 story.style; relationships.negative_list (L579) | story.style (作者腔散文) |
| 破折号治理 | 生成文本确定性重写破折号串: 句尾/闭引号前的戏剧性中断保留, 其余变逗号; beats/建议chips/回忆册全过这道闸 | engine/runtime.py dedash/dedash_beat (L60-124), set_suggestions (L3243) |  |
| 身份带voice_head | 角色「谁/脾气/怎么说话/语言指纹/台词范例」单一实现, 主拍/手机/电话共用同源(治「手机上性格跟线下不一样」), 逐字稳定吃前缀缓存 | engine/qwen.py voice_head (L709) | characters[].voice_print / eq_style / examples |
| en语言合同 | language=en 的本子玩家可读文本全原生英文, 但解析器按中文前缀匹配的标记行(好感：/【已读】等)保留中文前缀; 地名裁剪按语言分尺(en 40字符/zh 12字) | engine/qwen.py _lang_rule (L204)/place_clip; docs/i18n.md | story.language = "en" |
| 音频混音台 | 音乐/音效/人声三轨分层(音乐比音效低一档), 换曲交叉淡入、音效/人声响时音乐闪避到45%再爬回, 双滑杆音量跨局记忆, 任意点击解锁 autoplay | play.html swapBgm/playSfx/playVox/applyVols (L5652-5845) |  |
| 一句一页打字机 | 古典 ADV 呼吸感: 一个句号一次点击, 标点分级定打字节奏(句末重顿×7/逗顿×3.5), 点故事区跳过直出; 「引号悬挂缩进中文排印 | play.html typewriter 段 (L4761, L5574 一句一页, L4798 呼吸分级) |  |
| 新一天过场卡 | newday 事件→全屏章节过场卡+输入锁+自由活动菜单; 章节卡也用于幕切换 | runs.py newday 事件 (L1266); play.html #vnchap (L5200) |  |
| 导演审稿 | 确定性逻辑审稿只查铁证: 死者开口/昼夜矛盾/整回合逐字复读/招牌动作三拍复读, 查出随逻辑护卫定向重写; audit 事件下发调试单 | engine/director.py logic_audit/_repeat_motifs (L349-427); runs.py audit 事件 |  |
| 生物图鉴立绘 | 每只授权生物 t2i 一张图鉴图+一张透底舞台立绘(id定seed同怪同脸), 全服共用; 野兽立牌上台可进入狂暴态 | routers/runs.py _spawn_creature_art (L213); play.html standee beast 分支 |  |
| 物品配图懒生成 | 物品模板第一次被展示才排队 t2i 图标, tid 定 seed 同模板永远同图, 生成后全服复用 | routers/runs.py _queue_item_icons (L134); engine/items.py icon_prompt |  |
| 基调锚 | 乐师账本反哺文本: 软基调(暧昧/温情)连拍≥2时把基调当事实贴到生成点, 狠话先按撒娇/试探读, 硬基调按字面 | engine/runtime.py tone_anchor (L2770) |  |

### 🛠 创作与运营工具（52 条）

| 功能 | 一句白话 | 位置 | 作者旋钮 |
|---|---|---|---|
| 共享创作库 | 任何登录用户都能打开并编辑全站任意剧本/沙盒（删除仍只限作者本人） | routers/stories.py (SHARED_LIBRARY=True, _own_story/_my_story) | SHARED_LIBRARY（代码常量） |
| 分区编辑 | 作者按区块保存剧本：角色/幕/结局/地点/秘密/恐怖件(threat·dooms·sanity·rules)/时钟/手机/verdict/沙盒，PATCH 只动传了的区 | routers/stories.py update_story |  |
| 乐观锁 | 别的窗口或设备改过这本后再整本保存会吃 409，提示先刷新，防互相埋改动 | routers/stories.py update_story | 请求体 if_rev（客户端载入时的 updated_at） |
| 秘密碎片编辑 | 作者给角色挂分层秘密：每层碎片带解锁条件(act_min等)/知情人/掩饰话术，整套 CRUD | routers/stories.py /secrets 系列 |  |
| lint 体检 | 工坊一键体检：引擎同款 linter 列出死锁/悬空引用等 error+warn 清单（gate_deadlock/dangling_frag/dangling_exit…） | routers/stories.py /lint + engine/logic.py lint_story/humanize_issue |  |
| 发布硬门 | lint error 清零才许发布；发布=版本+1 落不可变快照上架，坏本无法一键上架 | routers/stories.py publish |  |
| 可见性批量 | 书架批量公开/隐藏（只翻 visibility 一个字段，不碰乐观锁），共享库下谁都能整理 | routers/me.py /stories/visibility |  |
| 剧透盾 | 玩家读剧本时结局/答案/幕内事件/角色小传/地图钥匙全被抹掉，只有工坊带 ?edit=1 才给全量 | routers/stories.py _public_story_view/get_story |  |
| 工坊书架 | 剧本列表每行带立绘数/背景数/开档数三条证据+mine 标记，供作者判断哪本该藏 | routers/me.py my_stories/_shelf_stats |  |
| 编辑痕迹埋点 | AI 起草本发布时自动记 _edit_ratio（草稿与发布版体量差），给推荐排序留质量信号 | routers/stories.py publish（tuning._origin=ai_draft 时） |  |
| 文字解析角色 | 作者扔一大段文字→自动解析出最多 6 张角色卡，秒回任务号+短轮询取结果（防手机掐长连接） | routers/stories.py parse_characters + _PARSE_JOBS | 请求体 language/world/style（留空自动判语言） |
| AI起草引擎本 | 几句想法或整段原文→AI 起出骨架+角色+秘密+结局的完整引擎本，走 生成→lint→确定性降级→拆光门控保底 闭环，私有落库后跳工坊精修 | routers/stories.py draft_engine/_degrade_draft/_strip_all_gates | 请求体 title（作者填了就尊重） |
| 问卷造沙盒 | 答几道题→生成世界概要（可改可重摇，日限10次）→确认后铸私有沙盒本即刻可玩（日限3本），题材查表定货币开局钱 | routers/stories.py draft_sandbox/draft_sandbox_summary/_assemble_sandbox/_SANDBOX_ECON |  |
| 沙盒形状闸 | 确定性修剪问卷沙盒的烂零件（坏 progression/悬空 opening_visitor），不报错不打断，修剪记录入 tuning._sanitize_notes | engine/logic.py sanitize_sandbox |  |
| gal三档输入 | A档贴全文(≥200字)/B档想法+确认大纲拓写/C档问卷→梗概回填B档，大纲确认是强制环节 | routers/gal.py + engine/gal.py outline_story/survey_idea/expand_work | GalCreate.mode=text\|expand, style, art_style, mature, enrich |
| 可存问卷向导 | gal 问卷草稿长在库里（每答一步落库），换设备续答，build_from_survey 才占配额开建 | routers/gal.py /draft /survey /build_from_survey |  |
| 编译式建造 | 识别角色场景→逐章编译拍序列（带前情摘要+前章收尾锚防吃书）→播放期纯翻页零 LLM，进度页轮询 status/progress | engine/gal.py build_work/parse_story + routers/gal.py status |  |
| gal美术管线 | 立绘一图四格差分+rembg抠底转webp、竖屏背景、CG、封面；生图失败进 manifest.missing 可续跑不废本 | engine/gal.py（SCENE_MODEL/FIGURE_MODEL=Seedream） |  |
| gal联网补设定 | 同人/IP 题材勾 enrich，建造时对前 2 位攻略角联网(Tavily)搜原作设定，编译时立设定铁律 | engine/gal.py build_work + engine/qwen.py generate_knowledge | GalCreate.enrich（无 Tavily key 时退回模型自身知识） |
| gal体检 | 编译完静态体检：章太薄/篇幅失衡/假选择(选项同向)/表情怒喜直跳/永远打不出的结局(error)/无兜底结局(error)/旁白「我」视角 | engine/gal.py gal_lint |  |
| 修订台 | 作者对成书重画单张(每项限3次)/重编某章(限2次)/直接改拍文字(零成本无限)/全本换画风(限2次全刷美术) | routers/gal.py redraw/rechapter/retext/restyle + engine/gal.py set_beat_text/rechapter_work |  |
| gal发布分区 | ready 且体检无🟥硬伤才能发布；discover 按游玩数排；18+作品走成年门；他人拉取脚本即游玩数+1 | routers/gal.py publish/unpublish/discover/work_script |  |
| gal配额 | beta 每人限 1 本已完成作品，建造失败不烧配额；同时只能建 1 本 | routers/gal.py create_work/build_from_survey |  |
| 断点续建 | 服务重启留下的孤儿建造可恢复：按残局自动判定从全重跑/续写章节/补美术三档接着干 | routers/gal.py rebuild |  |
| 剧本智能增强 | 一键为每个角色生成背景设定块（检测 IP、补年代与世界知识）写进角色卡，已发布本同步刷进快照让新档立即吃到 | routers/stories.py /enrich + engine/qwen.py generate_knowledge |  |
| AI画头像 | 工坊给角色画头像，与运行时补脸同管线同 char_seed——游戏里生成的立绘/自拍不会换脸；重画旧脸让位 | routers/stories.py gen_avatar + engine/sprites.py portrait_prompt |  |
| AI画背景 | 工坊给地点画背景，首画与游戏同种子（作者看到=玩家看到），再点是换一张（同族位移） | routers/stories.py gen_bg/_studio_bg_seed |  |
| 素材上传 | 作者上传自己的头像/背景/立绘：magic bytes+5MB 校验、路径消毒、立绘走透底+改脸源+方形头像三件套，快照同步 | routers/stories.py upload_media + engine/sprites.py ingest_upload | form kind=avatar\|bg\|sprite |
| 声音克隆 | 上传 10~30 秒人声→CosyVoice 克隆专属声线写进角色卡与快照，语气音精灵后台补齐，返回试听 URL；另有 voice_preview 当场试听现有音色 | routers/stories.py voice_clone/voice_preview + engine/voice.py enroll |  |
| 音库三张表 | 配乐(11情绪+真实曲库)/音效(问磁盘+人话名)/预置音色(只列精灵排齐的+人话标签)三个下拉数据源 | routers/stories.py bgm_list/sfx_list/voice_list + VOICE_CAST/SFX_LABEL |  |
| 自动封面 | 拿这本自己的立绘/头像/背景秒级合成盒绘（不生图），素材变了书架自动重排；工坊可看差什么并手点重画 | engine/cover.py + routers/stories.py get_cover/make_cover/_ensure_cover | cover.ENABLED（代码常量，当前=False 全关） |
| 月石钱包 | 玩家首访自动开钱包赠 200 内测币，不接真实支付 | routers/packs.py _wallet | FIRST_GRANT=200 |
| 创作者收费包 | 作者给每本挂最多 6 个收费包，grants 只认白名单：门票 access/开局钱 bonus/金手指×2/道具×3；下架软删已购永久有效 | routers/packs.py create_pack/_clean_grants/retire_pack | grants.access / start_money_bonus / powers / items；MAX_PRICE=9999 |
| 门票闸 | 本子挂了 access 包且玩家一张没买→开新档被拦；作者自动全拥有 | routers/packs.py access_blocked/owned_grants（runs 开档时调） |  |
| 分成看板 | 作者看每包销量与自己 70% 分成累计（P1 只记账不提现） | routers/packs.py earnings | CREATOR_SHARE_PCT=70 |
| 发现页 | 玩家大厅：标签筛选+游标分页(50/页)+标题/简介检索+sort=hot(赞×3+游玩数)+featured 运营位；卡面带署名/秘密数/进度阶梯/缩略图 | routers/stories.py discover/_to_card/_card_art |  |
| 精选位 | Story.featured 布尔列上卡面并可 featured=true 过滤；故意无公开写入口，运营手动置（谁都能自封精选=没有精选） | app/models.py Story.featured + routers/stories.py discover |  |
| 点赞收藏 | 玩家给公开本点赞/收藏（幂等 toggle，并发撞主键当成功），收藏进「我的书架」新藏在前 | routers/community.py like/favorite/my_favorites |  |
| 评论评分 | 一人一评（再评=改评），1~5 星+文字，楼中楼一层回复，评论可点赞；本子下架评论区随之关门 | routers/community.py post_review/reply_review/list_reviews |  |
| 作者主页 | 作者主页列公开作品卡+总游玩数+粉丝数，玩家可关注/取关 | routers/community.py author_profile/follow_user |  |
| 游玩数 | 每本的 plays=runs 表分组计数、likes 分组计数，批量上卡不逐行查库 | routers/community.py social_counts/_cards_with_social |  |
| 服务端冒烟门 | 部署前把每本已发布剧本用 MockLLM 走一遍脚本化小周目并断言不变量（拍产出/位置真移/状态可序列化），红了不许上；--live 档人工验提示词 | apps/api/smoke_stories.py | --live <剧本名> <回合数> |
| 客户端冒烟门 | Playwright 起一次性服务真点玩家金路径（注册/大厅/建档/手机/工坊/创作页），全程零 JS 报错才放行部署 | apps/api/smoke_client.js + tests/fixtures_smoke_story.json | SMOKE_CHROMIUM 环境变量 |
| gal冒烟门 | MockLLM 全流程建一本+孤儿续建，断言每章有拍有选择/结局阈值可达/CG≤1每章/体检无 error | apps/api/smoke_gal.py |  |
| 夜巡 | 每晚 QA 专属账号轮换扮真玩家巡 2 本×2 回合（真 HTTP+SSE 路径），体验判官按 9 条实弹清单机械判卷，巡完删档 | apps/api/qa_playtour.py | QA_STORIES/QA_TURNS 环境变量；--story 点名巡 |
| 每日巡检 | 服务器 root cron 每天跑：服务/磁盘/库健康+冒烟门+守卫开枪榜(24h)+夜巡，写 daily_check.log 并落哨兵时间戳防 cron 静默死 | apps/api/daily_check.sh |  |
| 遥测 | 每次 LLM 调用和每个回合落一行 append-only JSONL（fail-open 绝不弄坏回合），报表出调用量/成功率/延迟分位/审计事件榜 | app/metrics.py + metrics_report.py | LP_METRICS 环境变量（改落盘路径） |
| BUGS挂账本 | bug 与欠账当天入账、修完标 ✅ 留一行归因不删条目，归因史当防复发教材 | docs/BUGS.md |  |
| 守卫测试群 | 221 个测试文件当宪法：引擎剧本无关/位置单一真源/资产路径消毒/URL 出库消毒/gal 建造等各有专职守卫 | apps/api/tests/（test_engine_agnostic、test_asset_key_safety 等） |  |
| 剧本级调参 | 作者在 story.tuning 覆盖任何节奏/平衡键（好感夹取/衰减分母/卡关三档/关系阈值/约定赏罚/对峙成功率等），未知键忽略，手册全列 | engine/runtime.py tuning_for/DEFAULT_TUNING + docs/tuning.md | PATCH /stories/{id} 的 tuning JSON |
| 灰度旗面板 | 剧本级开关一批系统：troupe剧组(默认开)/scene_ledger场账本(默认关)/vn_mode视觉小说演出/dice命运骰/rel_events事件记账/physics_guard物理哨兵/fallible会露怯/pursue_player全员追/real_clock现实时钟/mind_reader心象仪/opening_player_first玩家先开口/turns_per_slot时钟(0=关)/golden_chance奇遇自动摇(默认0) | engine/runtime.py DEFAULT_TUNING（每键带拍板注释） | tuning.troupe / scene_ledger / vn_mode / dice / rel_events / physics_guard / fallible / pursue_player / real_clock / mind_reader / opening_player_first / turns_per_slot / golden_chance |
| 计划渲染双拍 | plan/render 双拍合同：引擎默认读 settings，单本 tuning 可正反覆盖做试点，目前仅中文本生效 | engine/runtime.py plan_render_on + docs/plan-render.md | tuning.plan_render（覆盖 settings.plan_render） |

## 🕳 盘点时发现的死角

六个 subagent 各自留的 notes，按域归拢、内容重复的合并成一条（主要是场账本/命运抉择四件套/自动封面/cure效果这几处被两个域各说了一遍）。

### 核心回合与世界状态

- 涌现地点玩法当前整条冻结：`LLM_MINTS_PLACES=False` 让 `generate_and_move` 六条铸造路全部返回 None，`player_move_emergent` 又挂在 `TYPED_MOVE=False` 之后——「说去哪就长出哪」目前实际不可达，代码与提示词仍在（runtime.py 13845-13868 的 minted 分支是死路）。
- `engine/runtime.py _update_memory_for`（888行）已无任何调用者，是被 `_folds_async` 后台折叠取代后留下的死函数。
- `_update_memory`（全局单摘要）仅剩 legacy 路径在用（13736：responder 历史为空时的兜底），主力早已是分角色摘要。
- 场账本 `tuning.scene_ledger` 默认0，只在狗笼试点剧本开着（gameplay 域盘点确认大盘未全开）；`plan_render` 同样默认关且 zh-only——两大结构改造都还没铺开到全站。
- `key_choice_min`（命运抉择卡）、`world_event_every`（事件自燃）、`fate_auto_resolve`（命运代点）、`golden_chance`（金色瞬间自动摇）四个键出厂默认全 0：都是「留着可逆」的关闭态，剧本不显式开就等于不存在；金色瞬间目前只留玩家手点 `POST /golden` 一条路。
- docs/engine-logic.md §1 的管线表还是旧六阶段口径，runtime.py 实际已是 P0~P9 十阶段（以 docstring 为准），文档略滞后。

### 角色与关系

- schemas.py `Character.relations` 与 `linked_event_ids` 两个字段全仓无读取点（engine/routers 都不消费），疑似死字段；`state.relations`/`relations_summary` 是另一套东西。
- `char_sim.intent` 全仓没有清除点，是已知账（runtime.py:7613 自注），现靠 `_intent_stale` 保质期兜底而非真正清账。
- engine/diary.py（手账周摘要）自注：`DIGEST_EVERY_DAYS=7` 在 88% 存档活不过第1天的留存下几乎不触发，靠「第一次不等一周」补救；按游戏日的节拍对多数玩家仍近似永不重蒸。
- troupe-design.md 病灶8「玩家在场时 NPC 之间零互动」：`npc_rel` 的台上演变入口 `apply_npc_shift` 依赖模型报审，幕后戏仍是主要驱动——群像互戏的落地程度建议结合编剧拍实测确认。
- schemas.py `examples` 注释仍写 "future mes_example hook"，实际 qwen.py:859 已消费，注释过期。
- 推拉节拍（pushpull）与追求节拍（court）与回撤（warm_peak）三套冷热机制同时作用于一个角色，引擎只处理了 court 压 warm_peak 的互斥（runtime.py:12530），pushpull 与另两者同帧仍可能给出矛盾指令。

### 沙盒生存与经济

- `sandbox.start_location` 名不副实：全仓只有 cover.py（封面挑背景）和 logic.py（linter校验）消费它，真实出生点走 `ensure_start_location`（首个地点/附身角色的 home_location_id）；问卷向导恰好把它设成 `locs[0]` 才没暴露这个坑。想让它真管出生点得在 runs.py `create_run` 接上。
- items.py 的 `cure` 效果是保留枚举位（reserved）：引擎没有异常状态账本，作者声明了也会被夹逼成无效果+audit（docs/item-effects-p3.md 记的实现偏差①，代码自认「账本立了再点亮」；gameplay 域盘点同一处坑）。
- `bank_transfer` 的回执短信拿不到 beat_log 上下文（runtime.py:6621 注释自认），TA 的回复看不见你们刚聊到哪。
- `era` 有准入门槛（runs.py:617）：只在玩家亲手写了世界观时才收，只填年代不写世界观会被静默丢弃——有意为之但作者/玩家容易踩。
- docs/tuning.md 沙盒节只写了 enabled/real_time/永不结束/玩家会死四件事；九键其余（currency/start_money/era/progression/default_powers/opening_visitor/start_location）没有任何文档，只活在代码和 studio.html 里。
- health-ledger.md 挂账：MockLLM 缺 `gen_progression` 等孪生，修为阶梯自动生成这条真路径测不到。

### 玩法模块与手机生态

- 恐怖主题包（猎手/理智/dooms/规则怪谈）在 docs/ 目录没有任何专门文档，合同只活在 threat.py/sanity.py 的代码注释里——grep 全 docs 近零命中。
- 手机回信形状 `read` 有「点名不兑现」缺口：引擎点了已读而模型写了正文时只审计不兑现，兑现率全靠 metrics `phone_shape` 的 asked/got 对比追踪。
- `CONTACT_OFFER_T=20` 那条「TA主动塞号」通路如今只负责演戏——能力早被照面即入通讯录静默给了，属设计性冗余。

### 演出与媒体层

- 自动封面整套（cover.py ~1200行，排版/陈旧检测/后台队列/工坊接口/守卫测试全在）是关着的：`ENABLED=False`（Yi 2026-08-02 判「看起来太糟糕了」），已排的图留盘不丢，卡面退回地点背景图/选角页缩略；翻回 True 即全部恢复（authoring 域盘点同一处坑）。
- BGM 曲库 ancient/grimdark 两格没有真曲（只有24秒老合成器片），靠 fallback 指到 lonely/tense；作者点名可压过。
- gal 作品的逐句配音是半吊子：gal.py schema 里 `characters[].voice` 写着 "reserved for the TTS build stage"，出生即 None，gal 播放器没有台词键（只有沙盒 play.html 有）。
- 夜间背景 `_night` 只是前端探测约定（packages/contract/FRONTEND.md），服务端没有任何生成 `_night` 图的管线——只有手放素材的预置背景才有夜版，AI 生成的地点背景永远只有白天版+夜色调滤镜。
- 沙盒立牌只有呼吸没有眨眼/口型：`probeBlink`/`probeMouth` 只在 galplay.html，依赖 gal 管线的 `_眨`/`_口` 帧；沙盒 sprites.py 的 DIFFS 不含这两帧。
- 粤语音色仍只有一男一女（longanyue_v3/longjiayi_v3），粤语本子选角的硬限制照旧。
- 语气音精灵只列「精灵排齐了的」音色（`voice/list` 问磁盘）：新音色若没跑 gen_voice.py 排精灵就上表，玩家听到的是静默，表由守卫测试盯着。
- 表情差分构建有并发闸 `_EXPR_BUILDING`（runs.py L2650）防重复排队，但失败靠幂等重跑补齐，无自动重试。

### 创作与运营工具

- 智能增强的「联网」有条件：无 Tavily key 时 `generate_knowledge` 退回模型自身知识（stories.py `/enrich` docstring 明说 no live web search until a search key is configured），gal 的 enrich 同源。
- `featured` 精选无任何写入口（models.py 注释：运营手动置），意味着运营要直接改库。
- 问卷沙盒配额闸是进程内存字典（`_SANDBOX_SUM_QUOTA`），重启清零且先扣后调（LLM 502 也烧一次）——BUGS.md #19 已挂账认领 v1。
- galmaker.html 存量三处转义/裸拼（轮询URL裸拼 story_id、done 页 answers 直拼 innerHTML 等）未修——BUGS.md #18。
- gal discover 是全表扫+每行单查作者（N+1），与 stories discover 的轻列/分组优化不同步，发布作品多了会慢。
- `draft_engine` 失败会留空草稿剧本在库里，无自动清扫——BUGS.md #6。
- `_PARSE_JOBS` 任务台账（parse/draft_engine/draft_sandbox 三家共用）进程内、容量40、重启即失——起草中重启=任务凭空消失，客户端只看到 404 过期。
- gal 修订台 `rechapter` 的限次是每章2次（代码 `_bump_limit` cap=2），与蓝图 docs/galgame-maker.md 写的「立绘每张 2 次」不一致——`redraw` 实际 cap=3。
- 蓝图 P3 的多视角/TTS 配音/创作者选择分布看板/既读统计在 gal 路由与引擎中未见实现（字段位留了，功能未落）——与既有笔记里「剩多视角/TTS/存档/审稿拍」的说法一致。
