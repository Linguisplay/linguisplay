# LinguisPlay 健康台账

体检小队（4 agent：引擎核心/引擎外围/客户端/API运维）2026-07-13 首轮全面审计产出。
循环开发按此台账从高到低领活。修一条划一条，新发现追加。

图例：✅已修 · 🔧修复中 · ⬜待修

---

## P0（崩溃 / 丢档 / 越权 — 优先级最高）

- ✅ **路径穿越 → root 权限删/覆盖任意 .webp/.jpg**（gal.py redraw + stories.py upload_media）
  未消毒的 `key`/`target_id` 拼进落盘路径，认证用户可用 `../` 删他人的图。
  修：`gal.safe_asset_key()` 白名单消毒，两处入口套上；回归测试 test_asset_key_safety.py。commit 见本轮。
- ✅ **send 可重入 → 并发双 SSE 流互踩**（play.html）
  回车/▶/双击绕过 sendBtn.disabled，第二个 streamTurn 清掉未播完的正式拍、两个打字机交错、afterPlay 被覆盖。
  修：全局 `turnInFlight` 门闩，streamTurn 起置、finishTurn 落定释放。
- ✅ **回合中途异常/断流 → 正文入库但 state 全丢（文实永久分家）**（runs.py sse）
  逐拍 commit beat，但 state 只在 final 后落库；生成器抛异常或客户端断流则 final 永不到达，移动/收物/死亡旁白的 state 变更全回滚。
  修：sse except 兜底把就地改过的 state0 落库（GeneratorExit 也走），与已 commit 的 beats 对齐。
- ✅ **活世界心跳 vs 主回合并发写 → 整档覆盖**（runs.py living_heartbeat_pass）
  world_tick 含多次 LLM 可跑一分钟，玩家在窗口内玩一回合，其 state 被心跳陈旧副本整档冲掉。
  修：LLM 不持锁，写回前重读 + `_state_fingerprint` 乐观比对，变了就丢弃本次 tick。

## P1（坏玩法 / 文实分家 / 作者丢数据）

- ✅ **编剧拍 P2 字段全空转**（qwen.py）— 我方回归：mood/setup_plant/setup_pay/agenda_step 的 schema 碎片被误贴进解析器返回 dict，从没进 render_tool props。修：解析器改读 `d`，schema 补进 `_render_tool`，加进 `_PLAN_DROPS`。
- ⬜ **散文离场把角色 pin 成 AWAY 后永久放逐**（runtime.py:5148/991/1368）作息再也拉不回；正则还会误放逐旁观者。修：AWAY pin 带 TTL 或作息优先于 AWAY pin。
- ⬜ **无主答回合跳过事件对账 → 「想一想」能杀人**（runtime.py:6621/7402/8067）think/猎手截断/seek 无主答者，暂记事件永久 sticky，think 措辞撞事件关键词角色真死。修：kills/事件落账只认已对账触发。
- ⬜ **导演场次单缓存跨 run/跨用户串账**（runtime.py:1765）_BRIEF_CACHE 键不含 run_id/天，多用户共享故事 id 同键 → A 的戏眼指挥 B 的场；失败结果永久缓存、inflight 不在 finally 清。修：键加 run_id+day，失败不入缓存，inflight finally 清。
- ⬜ **受赠孪生成零成本偷窃通道**（runtime.py:4419/4460）「拿走/取走/抄起」被 accept_item 无条件入包，绕过抢夺判定。修：accept 只认赠予语境，抢夺动词转 taken 判定。
- ⬜ **强制命运移动丢 content_mutated → 新地点蒸发、玩家静默传送回开场地**（runtime.py:6636/3055）修：强制结算读 `_fres.get("content_mutated")` 写入 final。
- ⬜ **约定不 pin 对方脚 → 无作息角色结构性爽约还扣玩家分**（runtime.py:3598/7336/8241）修：约定时辰临近把 char_pins[cid]=约定地（同 seek 机制）。
- ⬜ **心跳 due() naive 时间串裸抛 TypeError → 卡死全架心跳**（living.py:62 + runs.py:1506 在 per-run try 外）修：due() 整体 try 返回 True 或挪进 per-run try。
- ⬜ **手机端 VN 控制排被 overflow:hidden 裁掉**（play.html:520/627）好感/状态/隐藏/自动/记录在 ≤640px 全不可见。修：#vnctl 移出 #vnbox。
- ⬜ **SSE 无重连无超时 → 断流卡死输入框**（play.html:3428）修：catch 调 reloadChat 补拍 + 60-90s 看门狗。
- ⬜ **换局不掐旧流 → 旧局事件串进新局 UI**（play.html:1344）修：AbortController，backToPick/enterRun 先 abort + 事件比对 runId。
- ⬜ **命运抉择在 vnLock 窗口被点 → 效果落账但玩家台词被静默吞**（play.html:1637）修：pickChoice 开头 `if(vnLocked())return`。
- ⬜ **退出剧本不撤导演层 → 心跳音效/暗角/滤镜跟到选书页**（play.html:1344）修：抽 resetDirector() 在 backToPick/doLogout 调用。
- ⬜ **_cleanup 按标题空判子系统置 null → 一次保存抹光沙盒/压力/时钟子配置**（studio.html:769 + stories.py:364）修：软关闭保留字段。
- ⬜ **秘密保存全删再建、无事务无锁 → 中途失败丢数据、双击成倍复制**（studio.html:797）修：save() 加锁 + 批量原子 PUT。
- ⬜ **重编章把新 target 阈值绑到 endings[0] → 攒 B 好感播 A 结局**（gal.py:931）修：按 cond.char 逐条对号。
- ⬜ **作者上传立绘被 smart_cast 无声重画覆盖**（sprites.py:194 + stories.py:590）作者上传没落 generated=False。修：上传处落 generated=False + 回写 snapshot。
- ⬜ **MockLLM 缺 fate_choice/track_scene/gen_progression/phone_reply 孪生 → 三条真路径测不到**（llm.py）修：补确定性 stub。

## P2（打磨 / 合规 / 死代码）

- ⬜ SQLite 无 WAL 无 busy_timeout（db.py:15）→ 并发写 database is locked。修：PRAGMA WAL+busy_timeout。
- ⬜ 进程级全局态假设单 worker（_TURN_ACTIVE/_PARSE_JOBS/_BRIEF_CACHE 等）→ 扩容即失效。修：扩容前移 DB/Redis。
- ⬜ vnWait 自动推进 setTimeout 从不取消 → 残留定时器快进后续页（play.html:2780）。
- ⬜ 目标栈 goal_settle 零调用 → 办成的差事在目标条钉两天（runtime.py:1881）。
- ⬜ opening_hook_beats / renderDiscoveries 死代码；offscreen_drama 与 apply_npc_shift 双源头。
- ⬜ profile.distill facts 整体替换（自称增量合并）→ 记忆退化（profile.py:55）。
- ⬜ _gal_endings 裸 json.loads 无截断抢救；_loads_lenient 可返回非 dict（qwen.py:2439/149）。
- ⬜ 地点通路按名字存储，改名断路产生脏数据（studio.html:287）。
- ⬜ 移动端横屏/软键盘/拖拽排除名单三处边界（play.html）。
- ⬜ backlog 无节点上限，长会话 DOM 无限增长（play.html）。
- ⬜ phone_mock 路由不校验 run 归属（接真数据前须修）。

## iOS 上架合规缺口（清单，不阻塞开发）

- ⬜ 账号删除端点缺失（Guideline 5.1.1）
- ⬜ UGC 举报/拉黑/下架缺失（Guideline 1.2）
- ⬜ HTTPS/ATS + cookie_secure（先域名+备案）
- ⬜ Session 无法吊销（stateless JWT，删号不失效 live token）
- ⬜ 生产 CORS 默认 localhost

---

**整体评价**（四队共识）：回合内快乐路径是法治（孪生确定性化、两段死亡、审计留痕、处处 clamp 与兜底），三块新边疆是人治——跨回合账本（pin/promise/goal 生命周期无人收尸）、跨请求持久化（content_mutated/异常时 beat-state 分家）、跨 run 进程级缓存（brief 串账）。P0 已全平；P1 是下几轮主攻。
