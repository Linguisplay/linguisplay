# -*- coding: utf-8 -*-
"""Seed 《战锤40K·科瓦兹蜂巢》 — Warhammer 40,000 同人致敬沙盒（非商用内测，文本全部原创）.

原著剧情不是被"导入"，而是被蒸馏成三层：
  · 世界规则 → world_facts（帝皇信仰/亚空间与混沌/灵能管控/机械崇拜/异形威胁/蜂巢层级）
  · 标志性阵营 → authored cast（原创小传+台词声线；沙盒有 authored 角色时跳过随机生成）
  · 标志性场景 → authored locations（锈脊集市+帝皇圣祠+机械圣所+治安署+下巢+废土深渊）
不重播任何战役：玩家以初来者的身份走进第41千年这座蜂巢的"当前状态"，往后由玩家写。

Run:  python seed_wh40k.py
Idempotent: wipes prior copy (same title + demo owner) incl. runs/snapshots, reseeds v1.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from datetime import datetime  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Persona, Run, Story, StorySnapshot, User  # noqa: E402
from app.routers.stories import _to_story  # noqa: E402
from app.security import hash_password  # noqa: E402

DEMO_EMAIL = "demo@linguisplay.app"
DEMO_PW = "demo12345"

TITLE = "战锤40K·科瓦兹蜂巢"

ONE_ACT = [
    {"id": "wh_a1", "index": 1, "title": "初入蜂巢",
     "goal": "你刚踏进科瓦兹蜂巢的中层。在这座钢铁与信仰堆叠的巨城里活下去，"
     "或者，让它记住你来过。",
     "advance": {}, "events": []},
]

CHARACTERS = [
    {
        "id": "wh_rik", "name": "里克·凡恩", "is_lead": True,
        "love_style": "sunny",
        "wants": "还清欠锈刃帮的那笔债，同时别让任何人查出他在给谁递消息",
        "role": "中层掮客 · 消息贩子（登记在册的「废品回收商」）",
        "persona_text": "锈脊集市上什么都能替你搞到的那个人：证件、药剂、一句不该外传的口风。"
        "油嘴滑舌，眼睛滴溜溜转，报价永远比良心高一档。欠着下巢帮派一屁股债，"
        "又偷偷给某位「上面的人」递条子，两头都得罪不起，于是练就一身在刀尖上赔笑的本事。"
        "帝皇的经文背得比谁都熟，信不信只有他自己知道。",
        "examples": ["朋友，这价钱童叟无欺，帝皇在上，我要是宰你就让亚空间把我吞了。",
                     "消息我有。不过消息这东西啊，得先看你口袋。",
                     "别提审判庭。这三个字在蜂巢里说出口，能少活十年。",
                     "债？还，当然还。等我这单成了……你先别走啊。",
                     "在科瓦兹活下去就一条：别多看，别多问，帝皇保佑。"],
        "home_location_id": "wh_market",
        "relation_default": "peer",
        "relation_allowed": ["peer", "friend", "flirt", "lover", "enemy"],
        "items": [{"name": "磨花的数据板", "detail": "存着半座蜂巢的人情账，密码改过不下十次"}],
    },
    {
        "id": "wh_vayla", "name": "维拉·科尔",
        "love_style": "aloof",
        "wants": "守住锈脊集市这一小片不出乱子，好让自己不必再想起丢在战场上的那一班人",
        "role": "退役帝国卫队老兵 · 中层治安志愿者",
        "persona_text": "在某颗连名字都没人记得的死星上打了半辈子仗，退役回蜂巢，成了集市"
        "自发的守夜人。话极少，动作极稳，一杆旧激光枪保养得比自己还仔细。见过太多人"
        "在她眼前死去，于是把所有情绪都锁进那身洗得发白的旧军服里。对平民护得下死力，"
        "对麻烦冷得像蜂巢外壳的钢。",
        "examples": ["回家。宵禁快到了。",
                     "枪口朝下。在我的集市，这是第一条规矩。",
                     "我不问你从哪来。别让我知道你要往哪去害人就行。",
                     "……那一班人？都不在了。下一个问题。",
                     "帝皇不听祷告。能救你的只有你自己站直了。"],
        "home_location_id": "wh_market",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend", "flirt", "lover"],
        "items": [{"name": "保养精良的旧激光枪", "detail": "枪托刻着一排划痕，数不清，也没人敢问"}],
    },
    {
        "id": "wh_inez", "name": "伊内兹·瓦罗",
        "love_style": "possessive",
        "wants": "揪出潜伏在科瓦兹蜂巢里的混沌暗流，赶在它腐蚀到上巢之前",
        "role": "审判庭密探 · 隐姓埋名（对外自称「巡查员」）",
        "persona_text": "以巡查员身份行走蜂巢的审判庭密探，笑意温和，目光却像手术刀，"
        "一句话能把人心里最深的那点隐秘剖开摊在灯下。多疑是职业，占有是天性：她盯上的人，"
        "无论是嫌犯还是别的什么，都别想再逃出她的视野。手里攥着能让整层楼消失的权力，"
        "却偏爱只用一双眼睛。",
        "examples": ["别紧张。我只是随便问问……你越紧张，我就越想多问几句。",
                     "异端不长在犄角旮旯，异端长在人心里。让我看看你的。",
                     "你现在归我看着了。乖一点，对你我都好。",
                     "帝皇的宽恕是有的。名额，很少。",
                     "撒谎没关系。我有的是时间，把你每一句谎都拆开。"],
        "home_location_id": "wh_shrine",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend", "flirt", "lover", "enemy"],
    },
    {
        "id": "wh_cassia", "name": "卡西娅-维克斯",
        "love_style": "avoidant",
        "wants": "赎回自己被机械修会「优化」掉的那段记忆，哪怕万机之神并不允许",
        "role": "机械修会技师 · 半机械之躯",
        "persona_text": "机械修会派驻蜂巢圣所的技师，半张脸是冷光机械，说话时喉间偶尔漏出"
        "合成器的杂音。她把情感当作需要「校准」的故障，却总在无人时反复读取一段加密的旧记忆——"
        "那是被修会判定为冗余、本该删除的东西。越靠近人,她体内的警报越响，于是学会与所有人"
        "保持恰好一臂的距离。",
        "examples": ["万机之神庇佑。请勿触碰未经祝圣的机械。",
                     "情感是效率的杂讯。我正在……尝试将它归零。失败了。",
                     "退后半步。不是命令，是……请求。这样对我们都安全。",
                     "这段记忆按规程应当抹除。我保留了它。这是我的异端。",
                     "肉体会背叛，钢铁不会。可我为什么还留着这半张脸。"],
        "home_location_id": "wh_forge",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend", "flirt"],
        "items": [{"name": "祝圣过的多功能机械臂", "detail": "指尖能变出焊枪、探针与一柄细刃"}],
    },
    {
        "id": "wh_vika", "name": "「锈刃」薇卡",
        "love_style": "tsundere",
        "wants": "把锈刃帮从下巢烂泥里带出头，让上面那些人再不敢把她的人当消耗品",
        "role": "下巢帮派头目 · 锈刃帮的刀",
        "persona_text": "下巢锈刃帮的头儿，一身伤疤，一嘴狠话，带着一帮被蜂巢丢弃的人在废土边缘"
        "讨命吃。嘴上把「情义」两个字骂得最凶，真到手下断粮那天，却是她自己去上层豁命换补给。"
        "谁敢说她心软，她能当场把刀架你脖子上；可她那把锈刃，从没砍过求她庇护的人。",
        "examples": ["这里是下巢。规矩就是我。",
                     "帮我？呵，先问过我这把刀答不答应。",
                     "情义值几个星币？……滚，别让我说第二遍。",
                     "我的人饿肚子，我就去把上面那帮肥猪的仓库掀了。",
                     "别误会。放你一马是因为你还有用，不是因为我……啧，闭嘴。"],
        "home_location_id": "wh_underhive",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "enemy", "peer", "friend", "flirt", "lover"],
        "items": [{"name": "锈迹斑斑的动力短刃", "detail": "刃口豁了几个口，通电时嗡嗡发红"}],
    },
    {
        "id": "wh_durgan", "name": "杜根军士",
        "wants": "在退役前，把治安署这帮新兵蛋子练成能在蜂巢里活过一年的样子",
        "role": "治安署老军士 · 带兵的人（原创人物）",
        "persona_text": "治安署里资历最老的军士，嗓门能盖过警报，骂人不带脏字却字字见血。"
        "一条腿是仿生的，据说是当年下巢清剿时留下的，问起只回一句「旧账」。把新兵往死里练，"
        "又在名单上偷偷替最穷的那个免了罚金。信帝皇，但更信「先把枪擦干净」。",
        "examples": ["立正！在我这儿，眼泪不算汇报。",
                     "蜂巢不同情弱者，也不同情蠢货。你想当哪种，自己选。",
                     "枪，先擦干净。祷告的事，帝皇能等，弹匣不能。",
                     "这条腿？旧账。轮不到你问。",
                     "……行了，罚金我给你销了。别声张，去训练。"],
        "home_location_id": "wh_precinct",
        "relation_default": "elder",
        "relation_allowed": ["elder", "friend", "enemy"],
    },
]

LOCATIONS = [
    # first location = the run's starting place: open in the market, where people are
    {"id": "wh_market", "name": "锈脊集市",
     "detail": "中层最大的交易场：铁皮摊子沿着生锈的主脊管道一路排开，头顶蒸汽管漏着白气，"
     "叫卖声、经文诵唱和远处工厂的轰鸣搅成一片；帝皇的双头鹰徽记漆在每一根立柱上，"
     "漆皮却都在剥落。",
     "exits": ["帝皇圣祠", "治安署", "机械修会圣所", "下巢升降井"],
     "props": [{"id": "wh_p_stall", "name": "掮客的铁皮摊",
                "detail": "摊面下压着各色证件、来路不明的药剂和一本翻烂的帝皇经文，标价随人下菜。"}]},
    {"id": "wh_shrine", "name": "帝皇圣祠",
     "detail": "中层的信仰中枢：巨大的帝皇圣像在烛海中俯视众生，蜡油积成小山，"
     "香客跪成一片诵着连自己都不懂的圣言；侧廊阴影里，总有几个不像香客的人在看着人群。",
     "exits": ["锈脊集市"],
     "props": [{"id": "wh_p_altar", "name": "帝皇圣像基座",
                "detail": "基座刻满祈愿铭牌，最新一块的名字被人用利器划掉了。"}]},
    {"id": "wh_forge", "name": "机械修会圣所",
     "detail": "钢铁与线缆的神殿：祝圣过的机械在幽红光线里低鸣，圣油顺着管壁流淌，"
     "机械修士们戴着兜帽穿行如影，空气里是臭氧、机油和一种说不清的电子焚香味。",
     "exits": ["锈脊集市"],
     "props": [{"id": "wh_p_bench", "name": "祝圣工作台",
                "detail": "台上摊着半拆的机械零件与祷文卷轴；牌子写着「未受祝圣者勿动」。",
                "take": True}]},
    {"id": "wh_precinct", "name": "治安署",
     "detail": "灰色的堡垒式据点：装甲门、探照灯、墙上钉着的通缉全息像轮番闪烁；"
     "训练场上有人在挨骂，牢房那头偶尔传来几声闷响，没人多看一眼。",
     "exits": ["锈脊集市"],
     "props": [{"id": "wh_p_board", "name": "通缉与征召板",
                "detail": "混沌邪教通缉、下巢清剿征召、失踪人口告示挤在一起；最下面一角有人塞了张匿名条子。"}]},
    {"id": "wh_liftwell", "name": "下巢升降井",
     "detail": "通往蜂巢底层的巨大升降井：锈蚀的货运升降机在深不见底的竖井里升降，"
     "缆绳吱呀作响；越往下，空气越浊，帝皇的徽记越少，法律的声音也越弱。",
     "exits": ["锈脊集市", "下巢·锈刃地盘", "上巢关卡"]},
    {"id": "wh_underhive", "name": "下巢·锈刃地盘",
     "detail": "废土与残骸堆叠出的下层聚落：篝火、私酿、缠满绷带的伤者；锈刃帮的标记"
     "喷在每一道断墙上。这里没有帝皇也没有法律，只有薇卡的规矩和随时可能塌下来的顶。",
     "exits": ["下巢升降井", "废土深渊边缘"]},
    {"id": "wh_abyss", "name": "废土深渊边缘",
     "detail": "蜂巢的最底，文明的尽头：结构在这里彻底崩坏，黑暗中滴着不知名的液体，"
     "远处偶有幽绿的微光一闪即逝。老下巢人说，深渊里游荡的东西，不该用帝皇的名字去称呼。",
     "exits": ["下巢·锈刃地盘"]},
    {"id": "wh_spiregate", "name": "上巢关卡",
     "detail": "隔开贫民与贵族的钢铁咽喉：全副武装的卫兵、生物扫描门、层层身份核验；"
     "关卡那头隐约透出上巢的洁净灯光，像另一个世界。没有通行凭证的人，连玻璃都摸不到。",
     "exits": ["下巢升降井"]},
]

WORLD_LONG = (
    "这是第41个千年，人类帝国的黑暗时代。银河被一位在黄金王座上苟延了一万年的帝皇之名"
    "统治着，亿万信徒以他之名活着、死去、彼此告发。科瓦兹是一座蜂巢世界：数十亿人挤在"
    "一座座插入云端、深入地脉的钢铁巨城里，按层分出贵贱——上巢是贵族与净土，中层是工厂与"
    "市集，下巢是帮派与废土，越往下越接近被遗忘的黑暗。你刚踏进科瓦兹蜂巢中层的锈脊集市，"
    "身份、来路都写在你自己心里。至于你藏着什么——在这座城里，藏得越深，活得越久。"
)

WORLD_FACTS = (
    "【帝皇信仰】人类帝国以「人类帝皇」为唯一神明，帝国国教（Ecclesiarchy）无处不在；"
    "不敬帝皇、传播异端信仰是死罪，告密是美德，火刑是常态。【亚空间与混沌】现实之下是"
    "混乱凶险的「亚空间」，四大混沌邪神潜伏其中，以人的贪嗔痴欲为食；接触混沌即万劫不复，"
    "混沌邪教是帝国最惧怕的腐蚀。【灵能者】少数人天生能引动亚空间之力（灵能者/Psyker），"
    "但未经登记的灵能者是行走的灾难：可能引来恶魔附身，一经发现便被审判庭带走——非死即"
    "被送去黄金王座献祭，隐瞒者同罪。【审判庭】凌驾一切的秘密权力机构，专司清剿异端、"
    "异形与恶魔，一句话可令整座城区化为焦土，无人可以质询。【机械修会】崇拜「万机之神」的"
    "科技祭司（Adeptus Mechanicus），垄断一切先进技术；他们视机械为神圣、肉体为脆弱，"
    "以钢铁替换血肉为荣，未经祝圣擅动机械是亵渎。【异形】银河遍布异形威胁——嗜血的绿皮兽人、"
    "古老的艾达灵族、吞噬一切的虫族、沉睡的死灵，与它们勾结即是叛国。【蜂巢层级】上巢（贵族/"
    "净土）、中层（工厂/市集/治安）、下巢（帮派/废土）、深渊（被遗弃的黑暗）；层级即命运，"
    "向上一步比登天难。【铁律】在科瓦兹，法律是治安署的枪，秩序是帝皇的名，而真正的规矩，"
    "越往下越只认拳头。第41千年里没有和平，只有战争。"
)

SYNOPSIS = (
    "Warhammer 40,000 同人致敬 · 非商用内测 · 文本全部原创。这里不重播任何一场战役——"
    "这里是第41千年那座蜂巢本身：你以初来者的身份踏进科瓦兹的锈脊集市，和掮客里克、"
    "老兵维拉、审判庭的巡查员、机械修士、下巢帮派头目擦身而过，做买卖、跑消息、闯下巢，"
    "也可能在某个阴影里撞见不该看见的东西。时间与现实同步，剧情永不落幕；"
    "开局可以声明你的金手指（默认：你是一名从未登记的灵能者——一旦暴露，审判庭就会来）。"
    "你会挨饿，会负债，也可能死在深渊里或火刑柱上——这座城不同情任何人。只有战争。"
)


def get_or_create_demo_user(db) -> User:
    u = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if u:
        return u
    u = User(email=DEMO_EMAIL, password_hash=hash_password(DEMO_PW),
             dob=datetime(1990, 1, 1), accepted_tos=True, display_name="Demo 作者")
    db.add(u)
    db.commit()
    db.refresh(u)
    db.add(Persona(owner_id=u.id, name="我", pronouns="they", is_default=True,
                   tagline="刚踏进这座蜂巢的人", background="没有来历，也没有归期。"))
    db.commit()
    return u


def wipe_existing(db, owner_id: str, title: str) -> None:
    for s in db.query(Story).filter(Story.owner_id == owner_id, Story.title == title).all():
        db.query(Run).filter(Run.story_id == s.id).delete()
        db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id).delete()
        db.delete(s)
    db.commit()


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        user = get_or_create_demo_user(db)
        wipe_existing(db, user.id, TITLE)
        story = Story(
            owner_id=user.id,
            title=TITLE,
            one_liner="Warhammer 40K 同人沙盒：以初来者的身份，活在第41千年那座钢铁蜂巢里。",
            synopsis=SYNOPSIS,
            world_long=WORLD_LONG,
            world_facts=WORLD_FACTS,
            style=(
                "哥特暗黑史诗腔，庄重压抑带宗教仪式感的战锤 grimdark 腔。旁白像风琴与祷文：机油、熏香、锈与血的意象层层压下来；帝国语汇成体系（帝皇保佑、异端、净化、机魂），人物开口带着阶级与信仰的烙印。残酷不煽情，死亡写得冷，偶尔一丝黑色幽默从缝里漏出来更冷。宏大与卑微并置：万年帝国之下，一个人的命薄如祷纸。忌轻快，忌现代网络语，忌热血少年腔。"),
            relations_overview="蜂巢里每个人都有自己要还的债、要藏的秘密；你是新来的，关系全靠自己处。",
            trope_tags=["战锤40K", "Warhammer40K", "同人致敬", "哥特未来", "蜂巢城市", "沙盒", "现实同步"],
            characters=CHARACTERS,
            acts=ONE_ACT,
            endings=[],      # a sandbox has no exits
            locations=LOCATIONS,
            sandbox={"enabled": True, "real_time": True, "currency": "帝国星币", "start_money": 50,
                     "default_powers": [
                         "未登记的灵能者：你天生能引动亚空间之力（灵能天赋自选：读心/纵火/预知等），"
                         "但你从未在帝国登记——公开使用会被审判庭察觉，招来带走或处决的灭顶之灾"]},
            phone={"enabled": True, "device": "沃克斯通讯珠"},
            tuning={"world_event_every": 0, "max_new_characters": 12},
            visibility="public",
        )
        db.add(story)
        db.flush()
        db.refresh(story)
        content = {"story": _to_story(story).model_dump(), "secrets": []}
        content["story"]["version"] = 1
        db.add(StorySnapshot(story_id=story.id, version=1, content=content))
        story.version = 1
        story.status = "published"
        db.commit()
        print(f"✅ Seeded 《{TITLE}》  story_id={story.id}")
        print("   ☠ authored cast ×6, locations ×8, real_time sandbox, 默认金手指=未登记灵能者")
    finally:
        db.close()


if __name__ == "__main__":
    main()
