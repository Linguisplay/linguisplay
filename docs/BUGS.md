# 🐛 挂账本

bug 与欠账不再散落在聊天里。规矩:报障当天入账,修完标 ✅ 留一行归因,别删条目
(归因史就是防复发的教材)。状态: 🔴 未修 / 🟡 有缓解 / ✅ 已修。

## 打开的

| # | 入账 | 现象 / 欠账 | 状态 | 线索 |
|---|---|---|---|---|
| 1 | 07-30 | 部署脚本 `git archive \| tar -x` 只解压不删除 — 删掉的文件永远留在服务器 (phone_mock.py 实弹, 手动清过一次) | 🔴 | deploy/deploy_from_git.sh; 每次删文件要手动跟一刀, 或改成清单比对 |
| 2 | 07-30 | ~~test_phase2 offline_pulse 不定期红~~ | ✅ 08-04 | monkeypatch `_rng.random`→0.0; 6 连跑 6 绿 |
| 3 | 07-30 | 斗罗/明珠 新旧两版共用 location id — lint 跨本报警 | 🔴 | 我升级时的残留; 旧版下架或改 id |
| 4 | 07-30 | 马红俊只有 2/8 张表情差分 | 🔴 | 阿里已续费, enrich 补跑即可 |
| 5 | 07-31 | 立绘大图查看器 (头像→档案卡→大图) 真机 E2E 一直没跑完 — 墙内链路慢, 验证脚本超时 | 🟡 代码已单测 | scratchpad/pw/shot.js 思路重跑 |
| 6 | 07-31 | 3 个空草稿剧本躺在库里 | 🔴 | draft_engine 失败残留; 加自动清扫 |
| 7 | 08-01 | ~~本地测试基线不是零: 2 个「环境噪声」失败 (play_e2e / real_clock)~~ | ✅ 08-04 | **归因归错了, 只有一条是环境**: real_clock 是测试拿本机时间对北京时间的钟 (美东 23:48 / 北京 11:48 差一个 slot), 改用 `runtime._now()`; **play_e2e 是真回归** — 好感 07-25 改事件记账后「交心」带 8 回合冷却, 3 拍到不了 affinity_min=6 (实测第 9 拍 4→8、第 10 拍开门), 测试仍钉死第 3 拍。改成「打到开门为止」, 门没开的每一拍都断言不漏。教训: 「环境噪声」是个太舒服的抽屉, 塞进去就没人再看 |
| 8 | 08-01 | 双会话共用一个工作树 — TTS 与返回键修复曾混在同一文件里, 靠补丁块挑拣才没互踩 | 🟡 纪律缓解 | 分文件分工, 或起 feature branch |
| 9 | 08-01 | ~~runs.py 顶层 `import fcntl` 让整个应用在 Windows 起不来~~ | 🟡 winshim 垫片 | 生产不受影响; 根治 = 条件导入 |

| 10 | 08-01 | (TTS会话未提交稿) qwen.py 注释携带「蓝信一」— 引擎不许带具体剧本内容, agnostic 守卫红 | 🔴 提交前必修 | test_engine_agnostic |
| 11 | 08-01 | (TTS会话未提交稿) runtime.py `_sl_open/_sl_close` 直接翻 char_pins — 位置真源守卫红 | 🔴 提交前必修 | 问路走 char_position(); test_position_single_source |
| 12 | 08-01 | 无头玩测驱动器时灵时不灵 (resumeRun 偶发静默失败原因未钉死) — 只坑验证不坑玩家 | 🟡 | scratchpad/pw/playtest*.js |
| 13 | 08-06 | `_settle_prose_exits` 离场正则只认中文 — en 本子角色「说走」不会被记走 (锁下 npc_moves 又摘了, en 离场只剩作息换班一条路) | 🔴 | runtime.py `_SELF_EXIT_RE/_EXIT_TAIL_RE` 补英文构式; 对抗性审查 08-06 发现 |
| 14 | 08-06 | free_day 第三张建议片「一个人去X转转」在锁下点了不走 (无 seek 形状, 打字移动已取消) — 前两张是 seek 形状还活着 | 🔴 | runtime.py free_day_suggestions ~9059; 改成原地或 seek 形状 |
| 17 | 08-11 | 双会话部署对撞实锤：我 restart 的瞬间另一路正在写 runtime.py → 首启 SyntaxError(11809行字符串被撕断)，systemd 3s 自愈。#8 的部署版：restart 可能读到写了一半的文件 | 🟡 systemd 兜底 | 根治=写临时名+mv 原子替换（scp 到 .tmp 再 ssh mv），或部署前喊一嗓子对齐两路会话 |
| 16 | 08-10 | 现网反复出现 `CLIENT-JS [promise] undefined`（08-09 21:13 三连 + 08-10 02:16）— 某个 promise 用裸 reject/throw undefined，遥测 `String(e.reason)` 拿不到任何线索，来源钉不死 | 🔴 | play.html reportClientError 的 unhandledrejection 分支该补：reason 为空时上报 `document.visibilityState + runId + 最近一次动作名`；play.html 归手账会话在改，别混文件，等那边提交后跟一刀 |
| 15 | 08-08 | 背景空镜铁律在 Seedream(Ark) 上是反效果 — Ark 无负词通道, `_generate_image_ark` 把负词折进正文, 铁律那墙「人、兽、猫狗、怪物」token 变成召唤 (樱见坂实弹: 运行时 `_bg_prompt` 出的六张背景**张张有人**, 固定 bg_seed 还把同一个女孩复制进六张; 七月弱提示词零生物 token 反而全空镜)。运行时三条背景路 (开档补图/游戏内重画/工坊) 全踩此雷 | 🔴 | runs.py `_bg_prompt` 铁律段 + qwen.py `_generate_image_ark` 折负词; 修法方向: ark 路生物负词不折正文, 铁律改「无人的空景」一句零 token 措辞, 生物压制靠 detail 消毒 (数据层 bg_style 已在樱见坂验证) |

| 18 | 08-16 | galmaker 存量转义/裸拼群: wzEngine 轮询URL与 story_id 裸拼、done(gal成书站)摘要行 answers 直拼 innerHTML、wzOl 仅引号转义 — 沙盒向导本次已按 _wzEsc 内容级收口, 存量三处未动 | 🔴 | galmaker.html; 沙盒终审 08-16 裁定另案, 修法照抄 fb06c16/20d7c22 |
| 19 | 08-16 | 沙盒问卷小欠账打包: 概要配额先扣后调(LLM 502 也烧一次)、_SANDBOX_SUM_QUOTA 进程内无回收重启清零(v1 认领)、造什么/题材中途切换旧答案残留混进 prompt 行、llm 合同测试只 hasattr 不验分发真通、test_quota_day_frame_is_utc 是镜像测试 UTC 午夜理论闪红 | 🟡 | stories.py draft_sandbox 一带 + galmaker.html + test_sandbox_llm_contract.py; 终审 Minor 打包 |

## 已修的 (本周实弹归因)

| 修于 | 现象 | 归因一句话 |
|---|---|---|
| 08-10 | 冒烟门本地又起不来 (`no such column: stories.featured`, 08-04 creatures 同款二犯) | smoke_stories.py 从不自己跑 init_db, 靠「服务器起过一次」的隐性假设 — 模型加列后本地 dev.db 落后于模型, 门先倒。修=门开跑先 init_db()（差分器幂等）。教训升级: 08-04 修了差分器却没修「谁来跑差分器」 |
| 08-04 | **同一份代码这一跑 917 绿、下一跑 17 红, 红的还跟改动毫无关系** | 全套件共用一个 test_e2e.db, 十来个文件为拿干净数据 `drop_all`; 而 `create_all(checkfirst=True)` 查的是 **SQLAlchemy inspector 缓存** —— 缓存里还记着「表在」, 于是跳过创建, 表真的没回来。pytest-randomly 每跑换种子, 受害者跟着轮换(先 test_shared_library, 换个种子成 test_shelf_tidy)。conftest 加 autouse: `inspect(engine).clear_cache()` + `create_all`。六连跑 936 全绿。**教训: 这层伪装成随机故障, 让人以为是自己改坏了 —— 我一度以为是自己的 db.py 干的, 换回原版才证明是存量问题** |
| 08-04 | 🪃 回扣旧事 166 次注入只落地 3~5 次(约2%) | 素材池 278 条里 193 条是 meet「初次见面」而取料取最老那条 → 角色回忆必然是寒暄; 且验真要自报摘录前12字原样出现, 模型换个说法就判失败。meet 降兜底 + 时刻卡进池 + 验真加「与素材共享≥4字连续片段」通路 |
| 08-04 | 💘 追求节拍是颗哑弹地雷 | `court_dir = court_directive_for(...)` 赋值从来没人读, 而该函数取数即写账(last_day/_court_confess) —— 一旦接上 court_tick 就变成「生成失败也照样花掉当天名额、武装表白」。拆成取数只读 + court_beat_book 结算期落账, 指令真的进 rel_playbook, 并压掉同帧的 style retreat(两条互斥指令) |
| 08-04 | 🃏 抉择卡点不动返回 400 且卡死存档 | `apply_choice` 只分派 kind=='fate', court 卡掉进幕内选项查表 → ValueError。补 court 分派 + 任何「自带 options 却不认识的卡」一律收走再报错(不收就永远挂着) |
| 08-04 | 冒烟门在本地根本跑不起来 (`no such column: stories.creatures`) | `_ensure_columns` 是手抄的列清单, creatures/factions 从没被抄进去。换成照模型声明的通用差分器, 补不上要往 stderr 喊。手抄清单的失效方式是沉默的 |
| 07-30 | 地图说他走了对话还在互动 (高频报障) | 客户端 cast 缓存无重同步; 服务端五处位置分歧 |
| 07-31 | 英文本子断句劈单词、匀速滴答 | 分页/呼吸/第一句三处词表只认中文标点 |
| 07-31 | 英文起草进编辑器语言变中文 | draft_engine 写死 language="zh" |
| 07-31 | 新加角色直接作画 404「没有该角色」 | 前置保存只认「剧本是新的」, 不认「卡是新的」 |
| 08-01 | 手机返回键死键 (图鉴/银行/动态) | backTo 传了光杆名字 "phone", onclick 无效表达式 |
| 08-01 | 真人玩测: 英文开场旁白半个单词 (straig) 存进库 | 开场拍 [:80] 硬截按中文体量定, 英文劈词 — cap_prose 中西分刀 |
| 08-01 | (TTS会话) 音量键被切劈 / 配音被剥 / 播放键找不到 | 功能间互踩, 无客户端门 |

## 教训沉淀 (写新代码前扫一眼)

- **词表/判据要中西通吃**: 分页、断句、ANIME_HINTS 三次栽在「只认中文」上
- **传参约定用调用不用名字**: onclick 里的字符串必须带括号
- **先落库再引用**: 客户端新建的对象, 服务器不认识
- **`.local/.test` 是保留域名**, 邮箱校验会拒
- **Windows 杀进程要杀树** (taskkill /T), 不然孤儿占端口, 下一跑静默连旧服务
- **page.evaluate 会等 async 函数**: 等一个「等玩家点击」的 promise = 互等死锁
