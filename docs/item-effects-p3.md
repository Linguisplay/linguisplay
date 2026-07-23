# 物品效果与变形系统 · 实现规格（P3）

> Yi 2026-07-15 拍板原文（实现偏差见文末）。在已上线的物品系统（物性卡/堆叠与立籍/
> 十一动词/审计单/隔离区）之上补第八节的四个窟窿。两条宪法不变：**引擎记账，模型报审**；
> **三级真实度**。效果和变形也走报审，记账依据全部长在物性卡上。

## 0. 实施顺序

1. **隔离区转正（补铸）** — 先架全局安全网
2. **效果字段进卡 + `item_used` 结算管线** — 主菜
3. **`item_transformed` 原子变形** — 复用铸卡口
4. **stashes / char_items 实体化改道** — 纯工程

## 1. 物性卡 schema 扩展（模板层）

八字之后追加：`effects: [{type, magnitude(1-3档), target(self|other)}]`（默认[]）、
`consumable: bool`（默认 False）、`uses: int`（默认 1；>1 = 多次使用品）。
**效果挂模板卡全服共享；用量进度（uses_left）挂个体籍，不进卡。**

**枚举铁律**：effect type 里只许出现引擎真正记账的状态——先有账本，后有效果枚举。
首发对应：heal → 血条阶梯；cure → 异常状态表；light → 光照。

铸卡两路（复用现有管线）：
- 申报（minted）：`item_new` 物性串追加末三段 `…|效果段|c|uses`
  （效果 `type:magnitude:target`，多个逗号分隔）。type 不在枚举 → 夹逼成无效果+audit。
- 规则表（backfilled）：**默认无效果**。绷/药/膏/丹→heal:1:self,c；解/清毒→cure:1:self,c；
  火折/火把/灯/烛→light:1:self,c,uses=3。宁可少效果，不可错效果。

老档冻结卡不回填效果；经第 5 节懒迁移补（backfilled 卡重推导，minted 卡不动）。

## 2. `item_used`（模型报审）

- schema：物品名 + 目标（缺省 self）+ 一句语境（只进 audit）。
- 结算守卫链：①真持有（否则驳回+隔离区）②卡上有效果（无效驳回，允许正文写徒劳）
  ③目标合法 → 全过才逐效果确定性落账（模型说了不算）。
- **消耗归卡，与效果成败解耦**：满血用绷带照样扣，叙事点明白费（no_op 记账）。
- 消耗与 split-on-write 联动：uses≤1 → 堆叠 qty-1；uses>1 → 首用即 split 立籍，
  indiv.uses_left 递减，归零销毁实例。
- **效果渗出**：结算后引擎产确定性孪生拍点名肇因与方向（"缠上绷带，伤口不再渗血"/
  no_op 点明白费）。数字永不裸奔。
- examine 渗出：效果 → 世界语言暗示（"闻着有股药草味，该是治外伤的"），零 LLM。
- 旧路径封口：模型把"用掉"报成 lost → audit why 指向 item_used；导演铁律显式禁止。

## 3. `item_transformed`（原子交换）

一笔销 n 铸 m 同拍落账，**禁止拆成 lost+gained**（拆开漏报一半=幽灵，正是病灶）。
- schema：inputs[名字…] / outputs[名字×qty 或 内联物性申报串] / method / destroys_clues。
- 守卫：①inputs 全数真持有 ②outputs 走现有铸卡口 ③有籍件（个体状态=叙事资产）销毁
  须显式 destroys_clues，落账进 `destroyed_evidence` 日志（世界记得玩家毁证——玩法资产）。
- 与制作的分界：结果有悬念走制作（过骰）；物理必然（火烧必成灰）走变形（**不过骰**）。

## 4. 隔离区转正（补铸）

3 天窗口内：正文提及 ≥2 次，**或**玩家对它发起过任何动词（最强信号）→ 转正。
批量补铸调用（schema 约束，失败走规则表兜底不阻塞），origin 三态 minted|backfilled|promoted。
入籍位置按最后语境（场景→scene_items）。转正频率监控保留。

## 5. stashes / char_items 实体化改道

懒迁移补 tid+qty；增减改道走现有动词；**防复活查重集合 = inventory ∪ stashes ∪ char_items**；
老档效果快照按规则表补（backfilled 重推导，保守默认）。

## 6. 导演铁律新增三句

3. 用东西一律报 item_used，lost 只用于遗失/被夺/丢弃；效果引擎说了算，照结果叙述。
4. 一物变他物报 item_transformed 一笔报完，不许拆 lost+gained；新产物连物性一起申报。
5. 有悬念的合成走制作（过骰）；物理必然的过程走变形（不过骰）。

## 7. 验收清单

见 tests/test_items.py P3 段（满血 no_op / uses=3 split 联动 / lost 封口 / 毁证确认 /
拆两笔被拦 / 转正 promoted / 枚举外夹逼 / stash 防复活 / v3 迁移幂等）。

---

## 实现偏差（2026-07-15，实现者注）

1. **cure 暂拒**：引擎无异常状态表（无人写入无人读取）——按枚举铁律"先有账本后有效果"，
   cure 保留枚举位但夹逼成无效果 + audit "账本未立"，毒机制立账后点亮。
2. **light 落 place_facts**：无黑暗 flag，但 place_facts（地点持久物理事实，提示词在读）
   是诚实的现成账本——"火把照亮了这里"作为 place_fact 落账。
3. **模型侧报名字不报 tid**：Bicking 教训（模型认标题不认编号），引擎内部才用 tid。
   item_used 走竖线串，item_transformed 走结构化对象（schema 支持，next_speakers 先例）。
4. **效果渗出用确定性孪生拍**（非"驳回重生成"）：结算后引擎自产点名肇因的旁白拍——
   不变式更强（必然点名）且省一次重生成调用。
