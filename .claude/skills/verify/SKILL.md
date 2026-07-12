---
name: verify
description: LinguisPlay 玩法金路径真机验收 — 每次改引擎/播放器后，把游戏当玩家开一遍并断言丝滑
---

# LinguisPlay 玩法验收（真机驱动，不是跑测试）

产品 = 竖屏手机 App 形态的 AI 实时 galgame（prod: http://106.54.1.82:8100/play）。
验收 = 用 Playwright 手机视口把**玩家会走的路**走一遍，断言 + 截图为证。
pytest/smoke 是部署门，不算验收；验收看的是台上的行为。

## 拿手柄（驱动配方）

1. **Token**：服务器上铸造会话（不要走登录 UI）：
   `ssh root@106.54.1.82 "cd /opt/linguisplay/apps/api && set -a && . .env && set +a && .venv/bin/python -c 'import sys; sys.path.insert(0,\".\"); from app.security import make_session_token; print(make_session_token(\"<user_id>\"))'"`
   demo 玩家 user_id=c7394a9c2cb74beeb86e4fc0978e0fe2。写进本地 token.txt 时必须 ASCII 无 BOM（PowerShell `>` 会写 UTF-16，用 bash 或 [IO.File]::WriteAllText）。
2. **Playwright**（harness 在会话 scratchpad `pw/`，node + chromium 已装）：
   - context: `{ viewport: {width:390, height:844}, isMobile: true, hasTouch: true }`
   - cookie: `{ name:"lp_session", value:TOKEN, domain:"106.54.1.82", path:"/" }`
   - 进游戏：goto /play → 等 3.5s → 若有「登录」按钮先点 → 点剧本卡（`text=剧本名`）→ 等 ~11s（世界加载）
   - **新手引导必须真点掉**（`button:has-text("明白了，开始玩")`，可能迟到/复弹，循环点 3 次）——
     删节点不写 localStorage 会复弹，挡住 elementFromPoint 断言（实弹教训）
3. **遥测**：页面 JS 崩溃会打到服务端日志：`journalctl -u linguisplay | grep CLIENT-JS`
4. **纪律**：验证回合会真实写进存档（≤2 个回合/轮）；生图验证 ≤5 张/轮；
   重启后 3 秒内发请求会撞上服务未就绪的假故障（先 sleep 或重试）
5. **铁律·别碰 Yi 的活档**：点剧本卡会续【最新】的档——那很可能是 Yi 正在玩的。
   验证一律开专用档（POST /api/v1/runs 记下 id, 用 openRun(id) 直进）或用我自己
   建的档 id。另外**点 #vnbox 推进时避开面板下半区**（选项在面板内, 盲点会误触
   选项发出真实回合——实弹闯祸过）：tap 坐标取 vnbox 顶部 1/4 处。

## 金路径（每一站都要丝滑）

按顺序驱动并断言：

1. **进档**：`body.vn` on、`vnfree` on、footer 贴底、输入框可见、无 JS error
2. **开场**：新档要有人亮有人说话（backlog 里存在 dialogue+speaker 的开场拍；
   全是无名旁白 = 开场保真回归）
3. **建议常驻**：chips 在面板内、正文下方（`chipsDocked`: chips.top ≥ vntext.bottom-4
   且 chips.bottom ≤ vnbox.bottom+2）、恢复档也有（state.suggestions 持久化）
4. **打字回合**：placeholder 在「轮到你了」↔「剧情推进中」间切换；发送后焦点离开输入框
   （触屏永不自动弹键盘）；SSE 流式回复逐拍进面板
5. **过场锁**：`vnChapCard()` 在放时 `vnAdvance()` 必须被吞（vnLocked），放完恢复；
   CG 至少亮 1.3s 才可点掉
6. **导演**：每回合末收到 `direct` 事件（bgm=情绪标签选曲带变奏、tint 阶梯）；
   有 mood 的拍带 `expr`（喜怒哀惊）
7. **新的一天**：翻天回合收到 `newday` 事件 → 过场卡 + 建议变成自由活动菜单（去哪找谁）
8. **阻断面**：`renderChoiceAsk`（命运抉择）/`renderMoveAsk`/`showDice`/`showEnding`
   注入假数据后必须可见可点（elementFromPoint 命中），结局是全屏谢幕不是冻结输入框
9. **立绘**：说话者剪影 `.cut`（透底 webp）、站地（bottom==屏底）、头胸在面板上方；
   无立绘的说话者上 `_extra.webp` 黑灰人影；换脸带 `?v=` 防缓存

## 已知假故障（别误报）

- 重启窗口内图片 onerror → 背景落到渐变（服务热了就好）
- 立绘 img 加载慢于截图（等 4s 再截）
- `#moveask` 若再出现空绿条 = `.hidden` 特异性回归（`#moveask.hidden{display:none}` 必须在）

## 服务器侧

部署 = scp 改动文件 → `systemctl restart linguisplay`（静态文件也重启，保持习惯）。
python 改动先本地 `./.venv/Scripts/python -m pytest -q` + `smoke_stories.py` 全绿再传。
绝不 git push（Yi 亲自推）；绝不做破坏性生产库操作。
