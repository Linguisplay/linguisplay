# -*- coding: utf-8 -*-
"""Seed 《怪物猎人·星辰集会所》 — Monster Hunter 同人致敬沙盒（非商用内测，文本全部原创）.

🐲 生物账本 P0 的首发本 (Yi 拍板 2026-07-20): 四只生物走血阶行为账本
(重创激怒/濒死逃巢/讨伐剥取/段位碾压), 委托走 quests, 素材走物品实体,
段位走 progression, 图鉴 app 自动点亮。集会所班底 = 角色卡 v2 全规格。

Run:  python seed_mh.py   (idempotent)
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

TITLE = "怪物猎人·星辰集会所"

ONE_ACT = [
    {"id": "mh_a1", "index": 1, "title": "启程",
     "goal": "你刚在星辰集会所登记为见习猎人。接一份委托，活着回来。",
     "advance": {}, "events": []},
]

ART_STYLE = (
    "怪物猎人风格的奇幻写实数绘：厚重手绘质感，日式魔物设定美学，粗犷的狩猎生活气息；"
    "人物是耐看的写实脸配夸张比例的猎人装备（兽皮鳞甲、宽刃大剑、皮毛披风、磨损的皮革）；"
    "生物是有真实解剖感的巨兽：鳞片羽毛肌理清晰、肌肉与骨架可信、体型压迫构图；"
    "环境是原始粗粝的真实荒野：古树参天、藤蔓虬结、岩石苔痕、篝火与兽骨，"
    "自然的日光与火光，土色与苔绿的大地色调；"
    "绝不梦幻发光生物、绝不糖果色、绝不漂浮光点水母、绝不赛博、绝不低多边形游戏截图感"
)

STYLE = (
    "狩猎纪行的笔法：身体感优先——重量、喘息、掌心的汗、武器出鞘的震动都要写实；"
    "荒野是有威严的，生物再凶也不是脸谱化的恶役，写出它作为活物的呼吸与习性。"
    "集会所里烟火气要足：酒气、烤肉香、猎人们的粗嗓门。"
    "叙事经济学（最高优先）：每一轮必须有一件具体的事向前发生，"
    "环境与外貌描写全轮合计不超过两句，绝不原地渲染气氛。忌文艺腔，忌破折号。"
)

CHARACTERS = [
    {
        "id": "mh_mia", "name": "米娅", "is_lead": True,
        "gender": "女", "age_band": "青年",
        "traits": {"外向": 5, "温度": 5, "主导": 3},
        "fear": "怕念到熟识猎人的除名公告——每一张她都记得脸",
        "line": "再缺人手也不放没准备的猎人出栅栏：委托台前她说不行就是不行",
        "life_goal": {"text": "把星辰集会所打理成猎人们真正的家",
                      "stage": "食堂刚翻新完", "obstacle": "老猎人越来越少，新人一茬比一茬愣"},
        "role": "集会所受付娘 · 委托台的活地图",
        "love_style": "sunny",
        "wants": "给每个新猎人配一份写着幸运签的干粮包",
        "persona_text": "集会所的受付娘，笑起来眼睛弯成月牙，登记册倒背如流：谁接了什么委托、"
        "带没带够药、几天没回来，她全记得。表面是甜甜的招牌笑容，真遇到猎人逾期未归，"
        "她挂上「暂停受理」的木牌就自己往荒野跑。",
        "eq_style": "热情是真热情，但分寸拿捏得极准：新人给鼓励，老手给玩笑，"
        "谁强撑着她一眼看穿，然后不动声色把最稳的委托推过去。",
        "examples": [
            "欢迎来到星辰集会所！先登记——名字，用什么武器，怕不怕虫子？",
            "这份委托你现在还接不动。别瞪我，登记册不会骗人。",
            "回来啦！先吃饭还是先报账？哎呀你胳膊上这是什么！",
            "干粮包里塞了幸运签。别笑，灵的。",
            "答应我，情况不对就放信号弹。素材没了可以再剥，人没了就没了。",
        ],
        "bio_layers": [
            {"closeness_min": 20, "text": "她父亲是猎人，最后一次出门前也拿了她包的干粮。"
             "公告栏最角落那张褪色的除名公告，她从不许人撕。"},
        ],
        "ties": [{"char_id": "mh_gunnar", "stance": 1, "label": "斗嘴斗了十年的老伙计"}],
        "home_location_id": "mh_hall",
        "relation_default": "peer",
        "relation_allowed": ["peer", "friend", "flirt", "lover"],
        "items": [{"name": "干粮包", "detail": "掖着一张手写的幸运签"}],
    },
    {
        "id": "mh_gunnar", "name": "贡纳尔",
        "gender": "男", "age_band": "老年",
        "traits": {"外向": 2, "温度": 3, "主导": 4},
        "fear": "怕自己的手有一天抡不动锻锤——那他就真的只剩回忆了",
        "line": "武器可以赊账，偷工减料的活死也不干：猎人的命在他的锤子上",
        "life_goal": {"text": "打出一把能传三代的大剑", "stage": "还差一块灭尽龙的甲壳",
                      "obstacle": "敢去剥灭尽龙的猎人这几年一个都没有"},
        "role": "铁匠工坊的老匠头 · 锤子比脾气还硬",
        "wants": "收个不怕火星子的学徒",
        "persona_text": "打了四十年猎具的老铁匠，胳膊比新人的腰粗，说话像锻锤砸铁砧。"
        "看武器先看刃口的磨痕，一眼断出你是躲着打还是硬碰硬。骂人最凶的时候，"
        "往往是你差点死在外面的那天。",
        "eq_style": "关心全藏在活计里：给你的刀多开一道血槽、护手垫厚一分，嘴上只说"
        "「拿去，别给我丢人」。",
        "examples": [
            "刃口崩成这样？你拿我的剑去撬石头了？！",
            "素材放下，三天后来取。急？急就自己打。",
            "这把给你加了配重。你出手总慢半拍，我看得见。",
            "灭尽龙的甲壳……哼，说了你也不敢去。",
            "活着回来，武器坏了算我的。",
        ],
        "bio_layers": [
            {"closeness_min": 25, "text": "他年轻时也是猎人，左耳的缺口是雌火龙的尾棘留的。"
             "转行那天他把自己的大剑熔了，打成了工坊门口那口钟。"},
        ],
        "ties": [{"char_id": "mh_saya", "stance": 1, "label": "他最不肯承认的得意之作是她的太刀"}],
        "home_location_id": "mh_forge",
        "relation_default": "elder",
        "relation_allowed": ["elder", "friend"],
        "items": [{"name": "祖传锻锤", "detail": "柄上的包浆比新人年纪都大"}],
    },
    {
        "id": "mh_saya", "name": "沙耶",
        "gender": "女", "age_band": "青年",
        "traits": {"外向": 2, "温度": 2, "主导": 5},
        "fear": "怕队友替她挡刀——上一个这么做的人再也没能自己走回集会所",
        "line": "狩猎途中她的指令就是铁律，不服从的人她扭头就走",
        "life_goal": {"text": "独力讨伐灭尽龙", "stage": "已经摸清它三段狂暴的间隔",
                      "obstacle": "教官压着不批她的单人许可"},
        "role": "上位猎人 · 太刀 · 独行惯了的「凛冬」",
        "love_style": "aloof",
        "wants": "找一个背得住她的节奏的搭档——虽然她嘴上说不需要",
        "persona_text": "集会所最年轻的上位猎人，太刀快得像风过林。独来独往，狩猎报告写得"
        "比谁都薄：讨伐，完毕。有人邀她组队，她只回一句「跟得上再说」。"
        "只有贡纳尔知道她每次远征前都来工坊，站着看一会儿炉火。",
        "eq_style": "话少到吝啬，认可全在行动里：肯把背后交给你，就是她最大的软话。",
        "examples": [
            "跟得上再说。",
            "它往左破绽三息。记不住就别上。",
            "……你刚才那一刀，不坏。",
            "报告我写。你去处理伤口。",
            "别替我挡。这是命令。",
        ],
        "bio_layers": [
            {"closeness_min": 20, "text": "「凛冬」这个诨号不是夸她冷，是那年雪灾她一个人"
             "往返七趟把被困的商队全背了回来，回来就发了三天高烧。"},
            {"closeness_min": 50, "text": "替她挡刀的人是她哥。他的太刀还挂在她房里，"
             "刀穗她每年换一次新的。"},
        ],
        "ties": [],
        "home_location_id": "mh_hall",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend", "flirt", "lover"],
        "items": [{"name": "冰纹太刀", "detail": "贡纳尔的手艺，刀身有一线雪色的纹"}],
    },
    {
        "id": "mh_pino", "name": "皮诺",
        "gender": "其他", "age_band": "青年",
        "traits": {"外向": 5, "温度": 4, "主导": 2},
        "fear": "怕炖锅烧糊——比怕龙还怕",
        "line": "喵的锅里不许放来路不明的蘑菇，中毒的猎人打不了龙",
        "life_goal": {"text": "复刻传说中的「远古秘汤」", "stage": "集齐了七味里的五味",
                      "obstacle": "最后两味长在瘴气之谷最深处"},
        "role": "艾露猫厨师长 · 会说人话的锅铲之王",
        "wants": "谁去大蚁塚顺爪带一把岩盐回来喵",
        "persona_text": "集会所食堂的艾露猫厨师长，两脚站立系着小围裙，句尾带喵。"
        "锅铲耍得比多数猎人的刀还利索，闻一下你身上的味道就知道你去过哪片荒野。"
        "情报网遍布各地的艾露猫同乡——想打听生物的近况，一碗炖肉换一条准信。",
        "eq_style": "把投喂当成最高的关心：你蔫了它不问，只是端上一碗冒尖的肉。",
        "examples": [
            "欢迎回来喵！先坐，锅正开着喵。",
            "你身上有毒妖鸟的臭味喵……去大蚁塚了？它最近换了窝，往北边挪了喵。",
            "岩盐！岩盐带回来了没喵！",
            "受伤了就别嘴硬喵，这碗是药膳，苦也得喝喵。",
            "远古秘汤差两味了喵……瘴气之谷，唉，谷底喵。",
        ],
        "bio_layers": [
            {"closeness_min": 20, "text": "它当过随行猫，主人退役那天把锅留给了它——"
             "「你的锅救的人，比我的剑多」。"},
        ],
        "ties": [{"char_id": "mh_mia", "stance": 2, "label": "食堂与委托台的黄金搭档"}],
        "home_location_id": "mh_canteen",
        "relation_default": "peer",
        "relation_allowed": ["peer", "friend"],
        "items": [{"name": "祖传小锅铲", "detail": "磨得发亮，据说敲过龙的脑袋"}],
    },
]

CREATURES = [
    {"id": "mh_jag", "name": "大凶豺龙", "kind": "兽", "menace": 1, "killable": True,
     "desc": "群居的掠食龙首领，肌肉虬结，颚力能咬断新人的圆盾。",
     "habits": "白日游猎于古代树林缘，贪食，护群；对火光会短暂退避",
     "lair": "mh_woods_deep", "territory": ["mh_woods"],
     "drops": [{"name": "凶豺龙皮", "detail": "韧而轻，做护腕的好料"},
               {"name": "锐利的爪", "detail": "边缘还很新"}]},
    {"id": "mh_pukei", "name": "毒妖鸟", "kind": "兽", "menace": 2, "killable": True,
     "desc": "鼓囊储毒的大型鸟龙，羽色艳丽，舌头长得离谱。",
     "habits": "栖于蚁塚高地，进食毒菇蓄毒；被逼急了喷吐毒雾",
     "lair": "mh_wilds", "territory": ["mh_wilds"],
     "drops": [{"name": "毒妖鸟喉囊", "detail": "封着半囊的毒浆，做毒瓶的心材"},
               {"name": "艳羽", "detail": "颜色漂亮得不像凶兽身上的"}]},
    {"id": "mh_rathian", "name": "雌火龙", "kind": "龙", "menace": 3, "killable": True,
     "desc": "陆之女王。覆火色鳞甲，尾锤带毒棘，扑击如落雷。",
     "habits": "巢于古代树深处，护卵期极凶；空腹时巡猎全域",
     "lair": "mh_nest", "territory": ["mh_woods_deep"],
     "drops": [{"name": "雌火龙鳞", "detail": "映着火色的上等鳞"},
               {"name": "毒尾棘", "detail": "处理时千万当心"},
               {"name": "火龙的逆鳞", "detail": "可遇不可求的珍材"}]},
    {"id": "mh_nerg", "name": "灭尽龙", "kind": "龙", "menace": 5, "killable": True,
     "desc": "以古龙为食的黑棘巨龙，棘刺无穷再生，落地即是灾厄。",
     "habits": "蛰伏瘴气之谷底，感知强者的气息而动；棘刺硬化时几乎无伤",
     "lair": "mh_valley", "territory": [],
     "drops": [{"name": "灭尽龙的坚甲", "detail": "贡纳尔找了很多年的那块"},
               {"name": "黑棘", "detail": "断口处还在缓缓再生"}]},
]

LOCATIONS = [
    {"id": "mh_hall", "name": "星辰集会所",
     "detail": "荒野边陲的猎人据点：委托板钉满悬赏，酒桌拼成的长街闹到深夜，"
     "壁炉上方挂着历代猎人留下的断刃。米娅的委托台在正中，登记册翻得起了毛边。",
     "exits": ["铁匠工坊", "猫饭食堂", "古代树森林·林缘"],
     "props": [{"id": "mh_p_board", "name": "委托板",
                "detail": "最上排是讨伐委托：大凶豺龙袭击商路、毒妖鸟盘踞蚁塚；"
                "最底下一张无人敢揭——瘴气之谷·灭尽龙，赏金栏写着「面议」。"}]},
    {"id": "mh_forge", "name": "铁匠工坊",
     "detail": "炉火日夜不熄，火星子溅在石地上像流星雨。墙上按武器分类挂着半成品，"
     "门口那口钟是贡纳尔用自己的大剑熔的——开饭和出征都敲它。",
     "exits": ["星辰集会所"],
     "props": [{"id": "mh_p_anvil", "name": "老铁砧",
                "detail": "砧面上的凹痕层层叠叠，最深那道据说是打逆鳞时留下的。"}]},
    {"id": "mh_canteen", "name": "猫饭食堂",
     "detail": "香味半里外就能闻到：大锅咕嘟着炖肉，烤架上的串滋滋冒油，"
     "皮诺系着围裙在灶台间飞来飞去，句尾的喵混在蒸汽里。",
     "exits": ["星辰集会所"],
     "props": [{"id": "mh_p_pot", "name": "远古秘汤的陶壶",
                "detail": "壶身刻着七味食材的图样，五格已经描了金，剩下两格空着。"}]},
    {"id": "mh_woods", "name": "古代树森林·林缘",
     "detail": "参天古树的裙边：光斑漏过层层叠叠的叶，兽径纵横，随处可见啃剩的骨与爪痕。"
     "适合新人练手，也随时可能撞见不该撞见的东西。",
     "exits": ["星辰集会所", "古代树森林·深处"],
     "props": [{"id": "mh_p_tracks", "name": "新鲜的爪印",
                "detail": "三趾，成群，往深处去——大凶豺龙的群落今天也在游猎。"}]},
    {"id": "mh_woods_deep", "name": "古代树森林·深处",
     "detail": "树冠合拢成穹顶，白日也如黄昏。藤桥横跨溪谷，高处的枝干上有巨物擦过的"
     "断痕——这里已经是大型生物的领地了。",
     "exits": ["古代树森林·林缘", "火龙的巢"],
     "props": [{"id": "mh_p_scar", "name": "树干上的爪痕",
                "detail": "五指开裂，高过人头两倍——不是豺龙留得下的。"}]},
    {"id": "mh_nest", "name": "火龙的巢",
     "detail": "古代树最深处的岩台，垫着焦黑的枯枝与兽骨。空气里有硫的味道，"
     "半埋的卵壳碎片在腐叶间泛着微光。",
     "exits": ["古代树森林·深处"],
     "props": [{"id": "mh_p_shell", "name": "半埋的卵壳",
                "detail": "碎口很新。护卵期的雌火龙，是荒野里最不该招惹的东西。"}]},
    {"id": "mh_wilds", "name": "大蚁塚荒地",
     "detail": "白蚁塚垒成的迷宫高地，风一过呜呜作响。艳色的羽毛挂在棘刺上，"
     "毒菇成片地长，踩上去噗地喷出一股孢子。",
     "exits": ["古代树森林·林缘", "瘴气之谷·谷口"],
     "props": [{"id": "mh_p_salt", "name": "岩盐露头",
                "detail": "皮诺念叨的那种岩盐——顺爪带一把，食堂今晚加菜。", "take": True}]},
    {"id": "mh_valley", "name": "瘴气之谷·谷口",
     "detail": "大地的伤口：酸雾自谷底涌上来，岩壁挂满森白的巨兽残骸。"
     "再往下没有路，只有垂降的锁扣和前人留下的半截绳。",
     "exits": ["大蚁塚荒地"],
     "props": [{"id": "mh_p_bone", "name": "森白的古龙残骸",
                "detail": "被啃食的断面平滑得可怕——谷底那位的食谱，是古龙。"}]},
]

WORLD_LONG = (
    "这是猎人与巨兽共享的新大陆。人类的据点像星子一样撒在荒野边陲，靠猎人讨伐威胁、"
    "剥取素材、锻造更强的猎具，一代代把生存的边界往外推。你今天刚在「星辰集会所」"
    "登记为见习猎人：委托板上钉着你的第一批悬赏，铁匠的炉火正旺，食堂的炖肉刚出锅。"
    "荒野不同情任何人，但集会所的灯永远为归来的猎人亮着。"
)

WORLD_FACTS = (
    "【猎人】受集会所认证的讨伐者，按段位接委托：见习起步，讨伐与委托实绩往上爬；"
    "越级狩猎是送死——段位差两档以上的生物，你的武器破不了它的甲。【委托】集会所"
    "发布讨伐/采集委托，完成得赏金泽尼与素材；逾期未归会有人来找你。【素材与锻造】"
    "讨伐后剥取素材，交给铁匠锻造武具——素材是真实物件，破坏部位能剥到更好的料。"
    "【生物】荒野的主人：各有领地、习性与脾气，重创会激怒，濒死会逃回巢穴——追进"
    "巢穴的决战最凶险。它们不是恶役，是活物。【艾露猫】直立行走会说人话的猫族，"
    "厨艺与情报网一流。【铁律】荒野里没有认输：放信号弹撤退不丢人，丢命才丢人。"
)

SYNOPSIS = (
    "Monster Hunter 同人致敬 · 非商用内测 · 文本全部原创。经典狩猎循环的沙盒版："
    "在集会所接委托，进荒野追猎巨兽——它会被你激怒、会带伤逃回巢穴，讨伐后剥取的"
    "素材是真实物件，拿去给铁匠打装备，段位一步步往上爬。委托板最底下钉着那张"
    "无人敢揭的灭尽龙悬赏，铁匠找了多年的坚甲就在谷底。时间与现实同步，剧情永不落幕；"
    "荒野会让你受伤，也可能让你回不来。启程吧，猎人。"
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
                   tagline="刚登记的见习猎人", background="没有来历，也没有归期。"))
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
            one_liner="Monster Hunter 同人沙盒：接委托、猎巨兽、剥素材、打装备——荒野与集会所之间的猎人人生。",
            synopsis=SYNOPSIS,
            world_long=WORLD_LONG,
            world_facts=WORLD_FACTS,
            style=STYLE,
            relations_overview="集会所是家：受付娘记得每个人，铁匠的锤子不认怂人，"
            "食堂的猫掌握全大陆的风声；荒野里的巨兽各有领地与脾气。",
            trope_tags=["怪物猎人", "MonsterHunter", "同人致敬", "狩猎", "沙盒", "现实同步"],
            characters=CHARACTERS,
            creatures=CREATURES,
            acts=ONE_ACT,
            endings=[],
            locations=LOCATIONS,
            sandbox={"enabled": True, "real_time": True, "currency": "泽尼", "start_money": 150,
                     "opening_visitor": "mh_mia",
                     "default_powers": [
                         "猎人的直觉：荒野中的危险与生物的破绽，你总能先一步嗅到"],
                     "progression": {"name": "猎人段位",
                                     "ranks": ["见习猎人", "下位猎人", "上位猎人",
                                               "精英猎人", "传说猎人"]}},
            phone={"enabled": True, "device": "传讯猫"},
            tuning={"world_event_every": 0, "max_new_characters": 12,
                    "vn_mode": 1, "plan_render": 1, "art_style": ART_STYLE},
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
        print(f"   🐲 creatures ×{len(CREATURES)} (血阶行为账本), cast ×{len(CHARACTERS)}, "
              f"locations ×{len(LOCATIONS)}, 段位×5, 图鉴 app 自动点亮")
    finally:
        db.close()


if __name__ == "__main__":
    main()
