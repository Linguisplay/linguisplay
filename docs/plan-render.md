# 计划/渲染双拍合同（plan/render split）

> 2026-07-08 立项。依据：318 真实回合巡检（p50 7.7s / p95 21s，director 1.4 次/回合），
> 以及外部收敛证据（Hidden Door 结构层、Intra 事实/叙述分离、Story2Game 前置条件、
> Dramatron 层级生成）。结论：「自由写 + 事后守卫」不收敛，改为「引擎先决定、模型只渲染」。

## 病根

旧合同是一次 `render_turn` 函数调用同时承担：散文（narration/speech/inner_read）
+ ~25 项结算裁决（好感/推进/物品/移动/死亡/时跳/…）。后果：

1. **无法流式**：函数调用必须整包返回才能解析 → 首字上屏 = 整次生成时长（p50 4.5s）。
2. **不收敛**：责任越多越容易违规 → 守卫开枪 → 整包重写（再 4.5s），且重写只是重掷骰子。
3. **规则互相稀释**：每修一个症状加一条铁律，第 47 条生效的代价是前 46 条各弱一点。

## 新合同（P7 主答者，两拍）

```
plan_turn  (函数调用, temperature 0.4, max_tokens 500, kind="plan")
   ├─ grounding: 先答场面事实（在场者/情绪/知情边界）——guided thinking，引擎丢弃
   ├─ outline:   2~4 条分镜（这一拍按顺序发生什么），交给渲染拍
   └─ 全部裁决字段 = 旧 render_turn 减去散文字段（字段语义不变 → settle 级联零改动）

render     (纯散文, stream=true, temperature 0.85, kind="render")
   ├─ 输入 = 同一套人设/文风材料 + plan 的 outline 作为分镜指令
   ├─ 输出 = 「」引号体小说段落，逐 token 流出 → SSE "token" 事件
   └─ 结束后 _parse_reply 确定性切分 beats；渲染拍不产生任何状态
```

合成：`directed = {**plan, "beats": render_beats}` → 下游守卫、`_settle_directed`、
审计全部不动。**渲染器不掌管状态，就不可能弄脏状态。**

### 为什么 plan 与 render 共用同一个 `_build_system`

正确性优先 + DeepSeek 上下文缓存按前缀命中：两拍同前缀 = 第二拍输入近乎全命中缓存。
plan 拍靠工具 schema 本身约束「只裁决不写文」，render 拍在消息尾追加分镜指令。

## 守卫的新角色

`_logic_guard` 保留但预期开枪率大幅下降（分镜先过了 grounding）。开枪榜从
「看哪个最多」改读「趋零验证」。若试点期 render 拍仍触发守卫，修分镜指令，不加黑名单。

## 传输与前端

- `run_turn_stream` 新增 yield `("token", {"speaker", "text"})`（仅主答者渲染期间）。
- `runs.py` SSE 转发为 `{"event":"token", "t":{...}}`。
- `play.html`：首个 token 收到即撤掉「输入中」指示，建一个实时气泡逐字追加；
  该说话人的正式 beats 到达时移除实时气泡、beats 以免打字动画直出（不双显）。

## 灰度与回滚

- `Settings.plan_render`（env `PLAN_RENDER`）默认 **False**；
- 剧本级覆盖：`story.tuning.plan_render: true/false`，单剧本试点；
- 旧路径原样保留（flag 关 = 字节不差的旧行为）；Mock 同样实现双拍，测试确定性不变。

## 验收指标（对比同剧本 flag 开/关）

| 指标 | 旧基线 | 实测（2026-07-08 本机） | 目标 |
|---|---|---|---|
| 首字上屏 TTFT | ≈ 整包 4.5s+ | 3.9~4.4s | < 2.5s |
| 回合正文写完 | p50 7.7s（全程空白） | 5~6s（全程逐字可读） | ≤ 6s |
| 守卫开枪率 | 10.4/100 回合 | 待试点数据 | 趋零（< 2/100） |
| director 调用数/回合 | 1.4（重写） | plan 1 + render 1 | 重写率 < 5% |

metrics.jsonl 新增 kind="plan" / kind="render"（render 带 ttft 字段）。

**TTFT 的下一批抓手**（按性价比）：① plan 拍换更瘦的 system（当前与 render 共用全量
人设文风材料，plan 其实不需要台词范例/笔法规则）；② DashScope qwen-turbo/flash 做
plan 拍（DeepSeek 无小杯）；③ 已做：plan 工具要求省略空字段（7.8s→4s 的来源）。

## 不在本期

成员（member）答者、intro/observe/transition 旁白仍走旧单拍；建议/场记/记忆三个
aux 调用的并行化是下一刀（对两条路径都有效）。
