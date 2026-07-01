# 调参手册 · story.tuning

每个节奏/平衡数值都可以按剧本覆盖：`Story.tuning`（JSON，作者可через API/seed 设置），
未设置的键用引擎默认。恐怖本和恋爱本要的节奏不同——这就是调的地方。
生效路径：`runtime.tuning_for(content)`（defaults ⊕ story.tuning，未知键/非数值忽略）。

## 好感（每回合总和）

**公式**：`affinity += clamp(Σ speaker_delta, affinity_clamp_min, affinity_clamp_max)`，好感地板 0。

| 键 | 默认 | 说明 |
|---|---|---|
| `affinity_clamp_min` | -3 | 单回合好感总变化下限 |
| `affinity_clamp_max` | 8 | 单回合好感总变化上限（群聊多人加总后夹取） |
| `act_backstop_div` | 12 | 无硬门槛的幕：幕数地板 = `1 + 好感 // 此值`（防软流程卡死）|

**算例**：好感30、`act_backstop_div=12` → 幕地板 = 1+30//12 = 3。想让软剧本推进更慢就调大。

## 卡关提示（连续无线索的被锁回合数）

| 键 | 默认 | 效果 |
|---|---|---|
| `stuck_nudge` | 1 | NPC 明显更愿意指路 |
| `stuck_push` | 2 | 顶栏出现直接提示（点名一个待挖话题）|
| `stuck_spell` | 4 | 顶栏列出全部剩余线索清单 |

解谜向剧本想更"硬核"就调大三档；轻松向调小。

## 关系（每角色对玩家，两轴：亲近 closeness / 心动 romance）

**档位推导**（`relationships.derive_mode`，按此优先级）：
`心动≥lover_t 且 亲近≥lover_close_min → 恋人`；`心动≥flirt_t → 暧昧`；
`亲近≤enemy_t → 敌人`；`亲近≥friend_t → 朋友`；否则保持作者设定的初始档。

| 键 | 默认 | 说明 |
|---|---|---|
| `friend_t` | 40 | 亲近 ≥ → 朋友 |
| `enemy_t` | -15 | 亲近 ≤ → 敌人 |
| `flirt_t` | 25 | 心动 ≥ → 暧昧 |
| `lover_t` | 60 | 心动 ≥ → 恋人（还需亲近够）|
| `lover_close_min` | 35 | 恋人档的亲近门槛 |
| `follow_min_closeness` | 25 | 邀请同行所需亲近（朋友/暧昧/恋人档直接可邀，敌人永远拒绝）|
| `close_step_min/max` | -6 / 8 | 亲近单回合步长夹取 |
| `rom_step_min/max` | -4 / 6 | 心动单回合步长夹取 |

**算例**：慢热恋爱本 `{"flirt_t": 40, "lover_t": 75, "rom_step_max": 4}` →
心动每回合最多+4，40 才进暧昧：至少 10 个走心回合才到暧昧档。

## 不按剧本调的（全局）

- `MEMORY_WINDOW=14` / `MEMORY_BATCH=6`（runtime.py）：逐字历史窗口与摘要批量。
  与 qwen.py 的 `history[-14:]` 耦合，改要一起改，故不开放给剧本。

## 用法示例（seed 或 PATCH /stories/{id}）

```json
{"tuning": {"stuck_push": 4, "flirt_t": 40, "affinity_clamp_max": 5}}
```
