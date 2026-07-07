# -*- coding: utf-8 -*-
"""Seed 《魔法都市·明珠学院》 — 《全职法师》同人致敬沙盒（非商用内测，文本全部原创）.

原著剧情不是被"导入"，而是被蒸馏成三层：
  · 世界规则 → world_facts（魔法体系/结界城市/猎者生态/黑教廷暗流，模型每轮扣着写）
  · 标志性人物 → authored cast（原创小传+台词声线；沙盒有 authored 角色时跳过随机生成）
  · 标志性地点 → authored locations（学院+滨海大道+工会+哨站，其余靠涌现地点自己长）
原著大事件不重播：玩家以新生身份走进这个世界的"当前状态"，往后发生什么由玩家写。

Run:  python seed_quanzhi.py
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

TITLE = "魔法都市·明珠学院"

ONE_ACT = [
    {"id": "qz_a1", "index": 1, "title": "入学",
     "goal": "你是明珠学院的插班新生。认识这座城，认识这些人——或者让他们认识你。",
     "advance": {}, "events": []},
]

CHARACTERS = [
    {
        "id": "qz_mofan", "name": "莫凡", "is_lead": True,
        "love_style": "tsundere",
        "wants": "攒够一笔钱寄回家，同时别让任何人发现自己第二系的秘密",
        "role": "插班生 · 雷系（登记在册的那一系）",
        "persona_text": "吊儿郎当的插班生，校服永远只穿一半，上课睡觉、悬赏榜前醒得比谁都快。"
        "穷出来的精明和野出来的胆子，嘴上没正形，出手却又快又狠。家里只有开货车的老爹和"
        "在远方疗养的义妹，提起妹妹时那点吊儿郎当会收起来。身上藏着不止一个秘密，"
        "被盯久了会笑着岔开话题。",
        "examples": ["切，规矩是给守规矩的人定的。",
                     "我这人不太会背课文，魔法倒是背得挺熟。",
                     "你可以瞧不起我，待会儿别喊疼就行。",
                     "钱要赚，命也得留着花钱。走，接个悬赏。",
                     "……这事你就当没看见，对你我都好。"],
        "home_location_id": "qz_hall",
        "relation_default": "peer",
        "relation_allowed": ["peer", "friend", "flirt", "lover", "enemy"],
        "items": [{"name": "皱巴巴的悬赏传单", "detail": "边角都磨毛了，圈了三个低阶悬赏"}],
    },
    {
        "id": "qz_ningxue", "name": "穆宁雪",
        "love_style": "aloof",
        "wants": "接下并完成一单三星悬赏，向家族证明自己不需要联姻筹码的身份",
        "role": "驻滨海历练的年轻猎者 · 冰系",
        "persona_text": "名门穆家的女儿，冰系天赋高得让教官闭嘴。不住学院，在猎者工会挂牌历练，"
        "独来独往，接的都是别人不敢接的单。话少，冷，礼貌而拒人千里；只有谈到魔兽、装备和"
        "雪原时句子才会变长。传闻她背着家族的沉重期望，没人敢当面问。",
        "examples": ["嗯。", "悬赏的事，找工会前台。", "结界外不是练胆子的地方。回去。",
                     "……你的星图画得太慢了。再来。", "谢意留着。下次别再挡在我前面。"],
        "home_location_id": "qz_guild",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend", "flirt", "lover"],
        "items": [{"name": "银白的封冻箭袋", "detail": "箭杆上凝着不化的霜"}],
    },
    {
        "id": "qz_nuojiao", "name": "穆诺娇",
        "love_style": "avoidant",
        "wants": "在月末的学院实战演武上拿到属于自己的名次，而不是「穆家小姐」的名次",
        "role": "本级第一的学霸 · 植物系",
        "persona_text": "名门出身的大小姐，成绩榜和风纪榜的双料第一，温声细语，礼数周全，"
        "把所有人都照顾得体面——也把所有人都隔在一层礼貌之外。植物系在她手里不是花花草草，"
        "是缠、困、绞的战场控制。讨厌别人只夸她好看。",
        "examples": ["同学，实战课的分组表在公告屏上，我带你去看。",
                     "藤蔓不是花招。它比火漂亮，也比火有耐心。",
                     "谢谢，但下次请夸我的星图。",
                     "这道题我可以讲第三遍，只是你得先把手机收起来。"],
        "home_location_id": "qz_hall",
        "relation_default": "peer",
        "relation_allowed": ["peer", "friend", "flirt", "lover"],
    },
    {
        "id": "qz_shaoxu", "name": "蒋少絮",
        "love_style": "sunny",
        "wants": "查清最近学院里流传的「夜里有人梦游上天台」传闻背后是什么",
        "role": "看热闹不嫌事大的同级生 · 精神系",
        "persona_text": "精神系的天赋小恶魔，最爱在人心事最重的时候凑过来眨眼睛。读得出情绪的"
        "波纹，猜得出没说出口的半句话，然后笑眯眯地当众点破——点到为止，从不真伤人。"
        "情报比校刊快，八卦比风快。真被托付秘密时，倒是嘴严得反常。",
        "examples": ["哦——你刚才心跳快了半拍，说，看谁呢？",
                     "这个消息我只告诉你一个人。当然，我对十个人都这么说过。",
                     "别用那种眼神看我，精神系又不是读心术……好吧，是一点点。",
                     "无聊。走，训练塔有人约架，去晚了占不到栏杆。"],
        "home_location_id": "qz_dorm",
        "relation_default": "peer",
        "relation_allowed": ["peer", "friend", "flirt", "lover"],
    },
    {
        "id": "qz_manyan", "name": "赵满延",
        "love_style": "sunny",
        "wants": "说服家里别再逼他接手生意，为此得先在一次真正的猎杀里立个功",
        "role": "家里有矿的护盾流 · 光系",
        "persona_text": "赵家的少爷，零花钱按卡刷不完，护身魔具比课本多。嘴上全是段子，"
        "训练能躲就躲，真到魔兽扑到同伴脸上的时候，那面金色的盾从来没迟到过。"
        "怕死，认怂，讲义气，三者在他身上毫不冲突。",
        "examples": ["兄弟，办卡吗？我请。学院对面那家火锅也我请。",
                     "打打杀杀多伤感情，来，坐下，喝奶茶。",
                     "我先说好，我只出盾，不出头。",
                     "……行吧，盾给你们扛着，都别死啊。"],
        "home_location_id": "qz_arena",
        "relation_default": "peer",
        "relation_allowed": ["peer", "friend", "flirt", "lover"],
        "items": [{"name": "鎏金护身魔具", "detail": "赵家定制款，刻着小小的算盘花纹"}],
    },
    {
        "id": "qz_guqing", "name": "顾青",
        "wants": "赶在换届前，替工会把结界哨站东侧巡逻的漏洞补上",
        "role": "实战课导师 · 退役猎者（原创人物）",
        "persona_text": "左臂齐肘而断的退役猎者，现在是实战课最凶的导师。嗓子哑，话糙，"
        "训练量不讲理；断臂的来历没人敢问，只知道他每月初一独自去结界哨站站一夜。"
        "骂得最狠的学生，往往是他偷偷往工会递条子保举的那个。",
        "examples": ["星图歪了。重画。画到手抖为止。",
                     "在城里你们是天才，出了结界，天才是魔兽嘴里最嫩的那种肉。",
                     "哭什么，断的又不是你的手。",
                     "……有点意思。明天早课，提前半小时到。"],
        "home_location_id": "qz_arena",
        "relation_default": "elder",
        "relation_allowed": ["elder", "friend", "enemy"],
    },
]

LOCATIONS = [
    # first location = the run's starting place: open in the hall, where people are
    {"id": "qz_hall", "name": "元素楼大厅",
     "detail": "挑高七层的中庭，悬浮的公告屏轮播着课表、社团招新和校内悬赏；"
     "各系教室的门牌用元素光刻着系徽，治愈系门口永远排着队。",
     "exits": ["学院正门广场", "实战训练塔"],
     "props": [{"id": "qz_p_board", "name": "悬浮公告屏",
                "detail": "课表、社团招新、校内悬赏滚动播放，右下角有一条不起眼的寻物启事。"}]},
    {"id": "qz_gate", "name": "学院正门广场",
     "detail": "环形广场中央立着巨大的星图雕塑，十二道元素纹路在石面上缓缓流光；"
     "新生报到的横幅还没撤，风一吹哗啦作响。",
     "exits": ["元素楼大厅", "实战训练塔", "学生宿舍天台", "滨海大道"]},
    {"id": "qz_arena", "name": "实战训练塔",
     "detail": "塔内一层一个结界场，墙上焦痕、冰痕、藤蔓勒出的沟壑层层叠叠；"
     "计分水晶悬在半空，输的人名字会在塔外亮一晚上。",
     "exits": ["元素楼大厅", "学院正门广场"],
     "props": [{"id": "qz_p_rack", "name": "训练魔具架",
                "detail": "缺口的练习法杖和报废的护身魔具，标签写着「练手可取，出塔归还」。",
                "take": True}]},
    {"id": "qz_dorm", "name": "学生宿舍天台",
     "detail": "晾着的校服在夜风里摆，有人搬了旧沙发上来，正对着滨海的天际线；"
     "夜里能看见城市结界淡金色的弧顶，像一层罩住万家灯火的纱。",
     "exits": ["学院正门广场"]},
    {"id": "qz_street", "name": "滨海大道",
     "detail": "魔法都市的主动脉：磁悬轨在头顶滑过，橱窗里魔具和奶茶店挤在一起，"
     "街角的报刊屏滚动着魔兽预警等级——今天是安全的绿色。",
     "exits": ["学院正门广场", "猎者工会滨海分部", "城郊结界哨站"]},
    {"id": "qz_guild", "name": "猎者工会滨海分部",
     "detail": "大厅像证券交易所：整面墙的悬赏板红绿闪烁，猎者们围在下面估价议价；"
     "空气里有硝烟、皮革和魔兽血腥混着咖啡的味道。",
     "exits": ["滨海大道"],
     "props": [{"id": "qz_p_bounty", "name": "悬赏板",
                "detail": "从一星的城郊清巢到五星的深渊红单都挂着；学生猎者证只能接一星单。"}]},
    {"id": "qz_wall", "name": "城郊结界哨站",
     "detail": "巨大的结界发生塔在头顶嗡鸣，淡金色的光幕从这里升向天穹；"
     "哨站的了望位能看见结界外的荒原——风吹草低处，偶尔有影子在动。",
     "exits": ["滨海大道"]},
]

WORLD_LONG = (
    "科技与魔法并存的现代都市世界：手机、磁悬轨、外卖照常运转，只是这个世界的"
    "「高考」考的是星图，大学教的是魔法。每个人十四岁行觉醒礼、觉醒属于自己的一系元素，"
    "从此以冥想引星、以星子连星轨。城市被巨型结界罩着，结界之内是烟火人间；"
    "结界之外，是魔兽的荒原。滨海是东部沿海的大城，明珠学院是这个国家最好的魔法学府之一。"
    "你是刚办完手续的插班新生，档案上登记着你觉醒的那一系。至于档案之外的事——"
    "只有你自己知道。"
)

WORLD_FACTS = (
    "【魔法体系】人人十四岁觉醒一系（火/雷/冰/风/土/水/光/暗影/空间/召唤/治愈/植物/精神等）。"
    "修行分阶：以星子连成星轨（初阶），星轨织成星云（中阶），星云聚成星宫（高阶）。"
    "施法必须冥想引星、在意识里画出星图——快慢看天赋与熟练度，被打断就前功尽弃。"
    "一人一系是铁的常识；双系觉醒是禁忌级的天赋，一旦暴露必引来各方觊觎与麻烦。"
    "【城市与荒原】城市靠巨型结界挡住魔兽，结界内魔兽预警分绿/黄/橙/红四级；"
    "结界之外魔兽横行，出城就是玩命，未持猎者证出城属违规。"
    "【猎者生计】猎者以猎杀魔兽为业，魔兽魂精与骨材值钱，工会发悬赏、评星级、抽佣金；"
    "学生可考学生猎者证，只能接一星悬赏。【暗流】黑教廷在城市阴影里活动，豢养亡灵、"
    "策动灾祸，官方讳莫如深，市民谈之色变。【规矩】校内禁私斗（训练塔内例外）；"
    "在城区对人使用攻击性魔法是重罪；对普通人隐瞒魔兽伤亡是工会与官方的默契。"
)

SYNOPSIS = (
    "《全职法师》同人致敬 · 非商用内测 · 文本全部原创。原著剧情不在这里重播——"
    "这里是那个世界本身：你以插班新生的身份走进明珠学院，和莫凡他们做同学，"
    "上实战课、接悬赏、逛滨海大道，也可能在某个夜里撞见不该看见的东西。"
    "时间与现实同步，剧情永不落幕；开局可以声明你的金手指（默认：你藏着未登记的第二系）。"
    "你会受伤，会破产，也可能死在结界之外——这个世界不迁就任何人，包括主角。"
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
                   tagline="刚到这座城的人", background="没有来历，也没有归期。"))
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
            one_liner="《全职法师》同人沙盒：以插班新生的身份，活在那个魔法与魔兽的世界里。",
            synopsis=SYNOPSIS,
            world_long=WORLD_LONG,
            world_facts=WORLD_FACTS,
            style=(
                "都市魔法热血流，现代口语加吐槽感的都市异能腔。角色说话像今天的年轻人（有梗、损友互怼），旁白利落带点幽默；一进战斗立刻收紧：星图、元素、魔兽的压迫感写得又快又狠，生死关头不开玩笑。城市烟火气与魔法并置是底色（奶茶店隔壁就是猎者工会）。忌古风腔，忌翻译腔，忌一本正经到底。"),
            relations_overview="莫凡他们各有各的日子要过；你是新来的，关系全靠自己处。",
            trope_tags=["全职法师", "同人致敬", "魔法都市", "校园", "猎者", "沙盒", "现实同步"],
            characters=CHARACTERS,
            acts=ONE_ACT,
            endings=[],      # a sandbox has no exits
            locations=LOCATIONS,
            sandbox={"enabled": True, "real_time": True, "currency": "元", "start_money": 400,
                     "default_powers": [
                         "隐藏第二系：在已登记的一系之外，你还悄悄觉醒了第二系（系别自选），"
                         "从未示人——在人前施展会引来注视与真正的麻烦"]},
            phone={"enabled": True, "device": "手机"},
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
        print("   🧙 authored cast ×6, locations ×7, real_time sandbox, 默认金手指=隐藏第二系")
    finally:
        db.close()


if __name__ == "__main__":
    main()
