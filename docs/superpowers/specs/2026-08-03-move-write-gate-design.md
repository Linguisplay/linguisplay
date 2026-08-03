# 移动写侧收口（commit_move 唯一窄口）设计

2026-08-03，地图深查（21-agent 审查+反驳验证，15 条确认 0 驳回）后 Yi 拍板：按结构版修，不许引入新 bug。

## 问题

全引擎约十处代码直写 `state["location_id"]` / `char_pins`，每处要靠人记得配套做齐：拔旧钉（`_drop_pins_on_leave`，兼收场账本）、查锁定门、钉带路人。审查确认同一类遗漏发生了五次（generate_and_move 三处、fate 生成分支、猎手押送、moved_to 生成分支丢带路人、npc_moves 被陈钉压制）。读侧当年同病，收口成 `char_position` 唯一函数加 AST 守卫后绝迹；写侧从未收口。

## 设计

### 1. `commit_move(content, state, dest, lead_id=None)` —— 玩家真实换场唯一写入口

原子做三件事：拔旧钉+收场 → 写位置 → 钉带路人（`lead_id`，内部挡 pcid）。
**原地不换场**：`dest.id == 当前位置` 时不拔钉不收场（修 P2「原地移动也拔钉」）。

改走窄口的九处：`apply_move`、`settle_prose_arrival`、`player_move`（两处）、`_apply_fate` move 已知分支、`_settle_directed` moved_to 已知分支、猎手押送（run_turn_stream 9682）、`generate_and_move` 全部 `move=True` 写入（三处，含被 `_settle_directed`/`_apply_fate`/`/move` 端点间接调用的生成路径）。

### 2. generate_and_move 行为修正

- `move=True` 各路径统一过 `commit_move`（自动获得拔钉+收场+带路人）。
- **existing 捷径补锁定门**：resolve 命中已有地点但 `location_available` 为假 → 审计 `loc.mint` 驳回、返回 None（原先免检传送，可绕解锁门；含 LLM 提炼名二次捷径）。move=False 的提及即立档同样驳回，锁定地点名不得上确认条（宁漏勿误杀）。
- 新增 `lead_id` 参数：`_settle_directed` 生成分支把带路的说话人传进来（修 P0「带路人留原地」）。
- `mint_sought_character` 改传 `move=False`，删掉「移动后回滚」的写法（行为不变，写入点消失）。

### 3. apply_char_move 落账清钉

booked 成功即弹掉 mover 的 char_pins 并把 TA 摘出场账本 cast——明确申报的离场压过陈钉（修「审计记✓人不动」）。场账本合同（docs/scene-ledger.md）本就写明剧情走戏不受限。

### 4. AST 守卫 test_move_gate.py

扫 runtime.py：`["location_id"] =` 赋值只许出现在白名单函数：
`commit_move`、`ensure_start_location`、`build_opening`（开局锚定）、`discover_on_arrival`/`confront_stream`/`run_turn_stream` 的自愈重锚（`= current_location(...)` 形态）。
`char_pins` 写入白名单：`commit_move`、`_drop_pins_on_leave`、`_sl_open`、`_sl_close`、`build_opening`（访客钉）、`_apply_phone_judgments`（电话钉）、`_settle_prose_exits`、`_heal_away_pins`、`apply_char_move`（弹钉）、`run_turn_stream`（寻人钉）。
白名单外新增写入 = 测试红。这是「下次忘不了」的结构保证。

### 5. 插队两小刀（同批）

- **daily_check cron 复活**：`git update-index --chmod=+x apps/api/daily_check.sh`（git archive 部署剥 +x 的根因）+ 服务器 crontab 加 `bash` 前缀双保险 + daily_check 落「上次成功时间戳」哨兵文件。
- **剧透盾裁 locations**：`_public_story_view` 置空 `out.locations`（验证实锤 play.html 零处读 story.locations，玩家端地图全走 /runs/{id}/map；解锁攻略图与物证答案钥匙不再裸发）。

## 不改的

visitor 钉/电话钉/寻人钉/prose-exit 钉的语义；apply_move 的三道门；moved_to 已知路行为；EN 口径（第二刀另行处理）；地图 UI（第三刀）。

## 测试（先红后绿）

1. moved_to 生成路移动后旧地钉子已释放、场账本已收。
2. moved_to 生成路带路人钉在新地点（P0）。
3. generate_and_move 撞名锁定地点：驳回不传送（move=True/False 各一）。
4. fate 生成分支移动后旧钉已释放。
5. mint_sought_character 不再动 location 且不弄丢现场钉。
6. apply_char_move booked 后 char_position 到新地（陈钉不压）。
7. 原地 move 不拔钉不收场。
8. AST 守卫白名单。
9. 剧透盾：非 owner 视图 locations 为空。
