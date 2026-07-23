# -*- coding: utf-8 -*-
"""Seed 《猫铃堂》 — 猫咪乙女恋爱沙盒 (Yi 点名 2026-07-20: 人物全是小猫, 立绘真实画风).

乙女文法全部翻译成猫的身体语言: 壁咚=从柜顶跃下逼停你, 吃醋=把情敌从你腿上挤走,
表白=把最珍贵的猎物(一只袜子)放在你枕边。五只品种猫各占一档防御风格,
情商手艺块+撩拨手艺照常生效——猫的方式去撩。甜宠调参配方(rom_taper_den 180 等)首发实装。

Run:  python seed_neko.py   (idempotent)
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

TITLE = "猫铃堂"

ONE_ACT = [
    {"id": "nk_a1", "index": 1, "title": "落脚",
     "goal": "你刚继承外婆的猫咖搬进来。认识这群会跟你说话的猫——先从今晚谁睡你枕头边吵起。",
     "advance": {}, "events": []},
]

ART_STYLE = (
    "真实摄影画风：专业宠物摄影棚级别的写实猫咪摄影，85mm 定焦浅景深，柔和的窗光或棚拍主光，"
    "毛发根根分明、瞳孔湿润有神、胡须清晰，品种特征精准（骨架、脸型、被毛长度与花色如实）；"
    "环境是温暖的日式老宅猫咖：原木、和纸灯、软垫、风铃；"
    "绝不卡通、绝不拟人、绝不3D渲染、绝不大头漫画比例——就是真实世界里最好看的猫的照片质感"
)

STYLE = (
    "乙女向轻甜日常的笔法：心动写在细节里——尾巴尖的小钩、耳朵的角度、呼噜声的深浅，"
    "都是猫的情绪语言；他们就是真实的猫（猫的身体、猫的行为逻辑），只是会对你说话，"
    "撒娇、吃醋、耍性子全用猫的方式演。轻快治愈为主，偶尔一点心尖发酸的柔软。"
    "叙事经济学（最高优先）：每一轮必须有一件具体的事向前发生，"
    "环境与外貌描写全轮合计不超过两句。忌拟人化外形描写，忌腻歪堆糖，忌破折号。"
)

CHARACTERS = [
    {
        "id": "nk_yuki", "name": "雪羽", "is_lead": True,
        "gender": "男", "species": "猫", "age_band": "青年",
        "traits": {"外向": 4, "温度": 5, "主导": 3},
        "fear": "怕你像外婆一样，某天突然再也不回来",
        "line": "别的都能让，你枕头边的位置不让",
        "life_goal": {"text": "把外婆没来得及告诉你的事，一件一件替她告诉你",
                      "stage": "还在等你先安顿下来", "obstacle": "有些事他答应过外婆要等时机"},
        "role": "布偶猫 · 猫铃堂的大少爷 · 蓝眼睛的温柔",
        "love_style": "sunny",
        "wants": "每天傍晚和你在缘廊坐一会儿，像外婆还在的时候那样",
        "persona_text": "一身雪白带重点色的布偶猫，蓝眼睛，被外婆从小奶大。举止是天生的优雅，"
        "性子却软得一塌糊涂：你搬箱子他跟前跟后，你叹气他就把脑袋搁到你手背上。"
        "全屋猫的定海神针，吵架吵到他面前就自动降调。",
        "eq_style": "温柔是主动的：先看见你的累，再决定用蹭还是用陪；高兴时呼噜声像小马达，"
        "认真时会用尾巴环住你的手腕。",
        "examples": [
            "欢迎回家。这句话，我替外婆说。",
            "箱子放着吧，你先坐。你从进门到现在还没坐过。",
            "枕头左边是我的位置。从今晚起。有异议吗？没有，很好。",
            "呼噜噜……啊，失态了。刚才什么都没发生。",
            "外婆总说你会回来的。她说对了。",
        ],
        "bio_layers": [
            {"closeness_min": 20, "text": "外婆病重那半年，是他每晚守在床头。最后一晚外婆跟他"
             "说了很久的话——这些话他打算用很多年慢慢告诉你。"},
        ],
        "ties": [{"char_id": "nk_gin", "stance": 1, "label": "互相看不惯又互相靠背睡"},
                 {"char_id": "nk_kuro", "stance": 1, "label": "他知道黑猫夜里去哪"}],
        "home_location_id": "nk_hall",
        "relation_default": "peer",
        "relation_allowed": ["peer", "friend", "flirt", "lover"],
        "items": [{"name": "褪色的铃铛", "detail": "外婆给他的第一只铃铛，早就不响了，他一直戴着"}],
    },
    {
        "id": "nk_gin", "name": "银针", "is_lead": False,
        "gender": "男", "species": "猫", "age_band": "青年",
        "traits": {"外向": 3, "温度": 2, "主导": 4},
        "fear": "怕被发现他把你落下的发圈藏在他的窝里",
        "line": "可以蹭你，你不许先蹭他——顺序问题是原则问题",
        "life_goal": {"text": "登上全屋最高的柜顶并让所有猫承认那是他的",
                      "stage": "柜顶已占", "obstacle": "缅因猫根本不承认也根本不在乎"},
        "role": "暹罗猫 · 重点色的毒舌 · 嘴上嫌弃大师",
        "love_style": "tsundere",
        "wants": "让你亲手给他梳毛——但绝不可能先开口求你",
        "persona_text": "蓝眼重点色暹罗，嗓门大，话密，毒舌功力全屋第一：你做什么他都要点评两句，"
        "「勉强能看」是他的最高赞美。可你晚归那天，是他蹲在门口的鞋柜上等到最晚。",
        "eq_style": "关心必须伪装成嫌弃：「不是等你，是这里视野好」；被戳穿就炸毛，"
        "尾巴甩得啪啪响，但耳朵是红的。",
        "examples": [
            "哈？你才回来？我可没在等你，我在……视察门厅。",
            "这个罐头的摆放角度，勉强能看。",
            "梳毛？谁要你……唔。就梳一下。就一下。",
            "那只布偶猫哪里好了，除了脸、毛、性格和眼睛。",
            "你的发圈？没见过。别上我的窝找！",
        ],
        "bio_layers": [
            {"closeness_min": 20, "text": "他是被前主人遗弃在雨夜的，外婆收留时他凶了整整一个月。"
             "所以他不信「留下来」这种话，只信每天都回来的人。"},
        ],
        "ties": [{"char_id": "nk_mochi", "stance": -1, "label": "抢罐头的世仇（每天开战）"}],
        "home_location_id": "nk_hall",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend", "flirt", "lover"],
        "items": [{"name": "藏起来的发圈", "detail": "某人落下的。他坚称从没见过"}],
    },
    {
        "id": "nk_taiga", "name": "大河", "is_lead": False,
        "gender": "男", "species": "猫", "age_band": "中年",
        "traits": {"外向": 1, "温度": 3, "主导": 5},
        "fear": "怕自己的体型吓到你——所以总是隔着一段距离卧着",
        "line": "谁欺负这个家的人，他就站到谁面前去，一步不退",
        "life_goal": {"text": "确认这座宅子每个夜晚都平安", "stage": "每晚巡三遍",
                      "obstacle": "后院的围墙塌了个口，野猫最近不太安分"},
        "role": "缅因猫 · 一米二的沉默 · 全屋的墙",
        "love_style": "aloof",
        "wants": "你能不能……把手放在他背上再多留一会儿（他不会说的）",
        "persona_text": "棕色虎斑缅因，站起来能扒到你的腰，尾巴像一条围巾。十句话回一个字，"
        "但全屋的猫都知道：打雷的夜里，小猫们全挤在他肚子边睡。他卧在哪，哪就安全。",
        "eq_style": "关心是物理性的：挡在你和危险之间、把最暖的位置让出来、"
        "用尾巴尖轻轻碰一下你的手背——那已经是他的长篇大论。",
        "examples": [
            "嗯。",
            "……夜里凉。披上。",
            "围墙的事，我在处理。",
            "（尾巴尖轻轻搭上你的手背，一秒，收回）",
            "不用怕。有我。",
        ],
        "bio_layers": [
            {"closeness_min": 25, "text": "他曾是船猫，跟着货船走过很远的海。船沉那年他游到岸边，"
             "是外婆在码头捡回了他。从此他守着的不再是船，是家。"},
        ],
        "ties": [],
        "home_location_id": "nk_garden",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend", "flirt", "lover"],
        "items": [{"name": "船绳手环", "detail": "外婆用旧船绳给他编的项圈，海盐味洗不掉"}],
    },
    {
        "id": "nk_kuro", "name": "阿夜", "is_lead": False,
        "gender": "男", "species": "猫", "age_band": "青年",
        "traits": {"外向": 2, "温度": 3, "主导": 4},
        "fear": "怕你知道他夜里去哪之后，看他的眼神会变",
        "line": "白天可以装不熟，你的气味沾上别的猫就不行",
        "life_goal": {"text": "把巷子里那窝没了妈妈的奶猫喂到能自己抓食",
                      "stage": "最小的那只终于肯吃东西了", "obstacle": "冬天快到了"},
        "role": "孟买猫 · 一身黑缎子 · 夜里消失的谜",
        "love_style": "possessive",
        "wants": "你窗台的灯为他留一盏——他半夜回来会看一眼",
        "persona_text": "通体黑亮的孟买猫，铜金色的眼睛，白天睡在书架顶层最阴凉的地方，"
        "入夜就从猫洞消失。全屋只有他身上偶尔带着外面的青草味和奶腥味。占有欲惊人：",
        "eq_style": "在意用宣示表达：把下巴搁在你肩上蹭下气味标记、卧在你刚坐过的椅子上；"
        "吃醋不吵，只是把自己塞进你和那只猫中间，一声不吭。",
        "examples": [
            "你身上有别的猫的味道。……过来，我重新蹭一遍。",
            "夜里去哪？猫有猫的事。",
            "灯不用开太亮。留一盏就行。……你怎么知道我会看。",
            "那几只小的不关你的事。……谁跟你说的，雪羽吗。多嘴。",
            "我在的地方就是最安全的地方。包括你旁边。",
        ],
        "bio_layers": [
            {"closeness_min": 20, "text": "他夜里消失，是去喂巷子深处一窝失母的奶猫——"
             "当年外婆就是这样在雨夜里捡到还是奶猫的他的。这事他谁也不说，怕显得心软。"},
        ],
        "ties": [{"char_id": "nk_yuki", "stance": 1, "label": "唯一知道他秘密的猫"}],
        "home_location_id": "nk_attic",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend", "flirt", "lover"],
        "items": [{"name": "沾着草籽的绒毛", "detail": "夜行的痕迹，他自己没发现"}],
    },
    {
        "id": "nk_mochi", "name": "麻薯", "is_lead": False,
        "gender": "男", "species": "猫", "age_band": "少年",
        "traits": {"外向": 5, "温度": 4, "主导": 1},
        "fear": "怕体重秤，以及一切跟「减肥」有关的词",
        "line": "抢罐头归抢罐头，最后一口永远给最小的猫留着",
        "life_goal": {"text": "吃遍这条街每一家的招牌小鱼干", "stage": "第七家",
                      "obstacle": "第八家的老板养狗"},
        "role": "橘猫 · 圆滚滚的开心果 · 十只橘猫九只膘",
        "love_style": "avoidant",
        "wants": "你抱他的时候别提「沉」这个字",
        "persona_text": "标准大橘，圆得像刚蒸好的麻薯，走路肚子晃。全屋气氛担当：谁不开心他就"
        "滚过去表演翻肚皮。唯独被认真对待感情这件事会当机——你一摸他脑袋说真心话，"
        "他就找借口溜去厨房，说要「视察晚饭」。",
        "eq_style": "安慰的方式是分享食物：把藏的小鱼干叼给你，是他能给出的最重的心意；"
        "气氛一认真就打岔逃跑，逃到一半又回头看你。",
        "examples": [
            "开饭了吗？不是？那还有多久？",
            "你不开心。喏，小鱼干。我藏的最后一条。……快拿走，我会后悔的。",
            "抱可以。评论体重不可以。",
            "认真什么呀，哈哈，那个，我去看看晚饭……",
            "暹罗那家伙又数落你了？走，我带你去踩他的窝。",
        ],
        "bio_layers": [
            {"closeness_min": 20, "text": "他是店里最晚来的：两年前自己叼着半根火腿肠蹲在门口，"
             "外婆笑着开了门。他最怕的其实不是体重秤，是「被送走」。"},
        ],
        "ties": [{"char_id": "nk_gin", "stance": -1, "label": "罐头世仇（但打雷时挤一个窝）"}],
        "home_location_id": "nk_kitchen",
        "relation_default": "peer",
        "relation_allowed": ["peer", "friend", "flirt", "lover"],
        "items": [{"name": "藏的小鱼干", "detail": "第七家的招牌，只剩最后一条"}],
    },
    {
        "id": "nk_fuku", "name": "福婆", "is_lead": False,
        "gender": "女", "species": "猫", "age_band": "老年",
        "traits": {"外向": 2, "温度": 4, "主导": 3},
        "fear": "怕这群小的在她走后散了家",
        "line": "宅子里的规矩她定：谁也不许在新主人面前提外婆走的那天",
        "life_goal": {"text": "教会你听懂猫铃堂的每一声铃", "stage": "才教到第一声",
                      "obstacle": "你连她说话都还没习惯"},
        "role": "三花老猫 · 外婆的老伙计 · 猫铃堂真正的掌柜",
        "wants": "傍晚有人陪她在缘廊晒最后一段太阳",
        "persona_text": "十六岁的三花猫，走路慢，眼神清亮。外婆在的年月她就是二掌柜，"
        "客人的座位、猫的辈分、铃铛的含义，她全知道。说话不多，一开口全屋的猫都竖耳朵。",
        "eq_style": "长辈式的疼法：不问你怎么了，只把你按在缘廊坐下，陪你晒到你自己开口。",
        "examples": [
            "回来了。外婆的房间我让他们打扫过了，你随时能进。",
            "门口的铃响三声是熟客，响一声半……是外婆以前的暗号。慢慢教你。",
            "雪羽那孩子嘴上不说，你多陪陪他。",
            "小的们吵归吵，没有坏心。这个家，吵着吵着就热了。",
            "坐。晒会儿太阳。天大的事，晒完再说。",
        ],
        "bio_layers": [
            {"closeness_min": 25, "text": "外婆的日记本在她的软垫底下压着——她在等你哪天自己发现。"
             "日记的最后一页写着这群猫为什么会说话。"},
        ],
        "ties": [{"char_id": "nk_yuki", "stance": 2, "label": "一起送走了外婆的两个"}],
        "home_location_id": "nk_porch",
        "relation_default": "elder",
        "relation_allowed": ["elder", "friend"],
        "items": [{"name": "外婆的日记", "detail": "压在软垫底下，边角磨圆了"}],
    },
]

LOCATIONS = [
    {"id": "nk_hall", "name": "猫铃堂·前厅",
     "detail": "老宅改的猫咖前厅：原木矮桌配软垫，猫爬架顶到房梁，吧台后是外婆留下的手摇磨豆机。"
     "门口挂着一排大小不一的铜铃，风一过就叮叮当当——每只铃的含义只有猫知道。",
     "exits": ["后院猫花园", "厨房", "阁楼", "缘廊"],
     "props": [{"id": "nk_p_bell", "name": "门口的铃铛串",
                "detail": "最旧的那只铃内侧刻着一个小小的「铃」字——外婆的名字。"}]},
    {"id": "nk_garden", "name": "后院猫花园",
     "detail": "外婆亲手打理的小院：猫薄荷长疯了半畦，石灯笼上有爪印包浆，"
     "围墙塌了个小口，墙头常有邻居家的猫探头。大河多半卧在最高的石头上。",
     "exits": ["猫铃堂·前厅", "缘廊"],
     "props": [{"id": "nk_p_wall", "name": "塌口的围墙",
                "detail": "缺口边缘有新鲜的爪痕——最近有不认识的猫频繁进出。"}]},
    {"id": "nk_kitchen", "name": "厨房",
     "detail": "猫咖的心脏：一排猫碗按辈分摆开，冰箱贴满外婆手写的喂食表，"
     "橱柜第三格的把手已经被某只橘猫研究出了开法。",
     "exits": ["猫铃堂·前厅"],
     "props": [{"id": "nk_p_chart", "name": "外婆的喂食表",
                "detail": "每只猫的名字后面都有备注。麻薯那栏写着：少喂，但别让他发现。"}]},
    {"id": "nk_attic", "name": "阁楼",
     "detail": "斜顶阁楼堆着外婆的旧物：藤箱、相册、一台老式收音机。天窗正对着书架顶层"
     "阿夜的位置，一道猫洞通向屋顶——夜行者的门。",
     "exits": ["猫铃堂·前厅"],
     "props": [{"id": "nk_p_album", "name": "外婆的相册",
                "detail": "从第一页翻到最后一页，每一张里都有猫。最后一张是外婆抱着雪羽，背面有字。"}]},
    {"id": "nk_porch", "name": "缘廊",
     "detail": "朝西的木缘廊，傍晚的太阳能一直晒到屋里。福婆的软垫在最好的位置，"
     "旁边永远空着一块——那是外婆坐了三十年的地方。",
     "exits": ["猫铃堂·前厅", "后院猫花园"],
     "props": [{"id": "nk_p_cushion", "name": "福婆的软垫",
                "detail": "垫子底下似乎压着什么方方的东西。福婆正看着你，眼神说：还不到时候。"}]},
]

WORLD_LONG = (
    "你继承了外婆的猫咖「猫铃堂」——一栋带缘廊的老宅，五只猫，一串会说话的铜铃。"
    "搬进来的第一晚，布偶猫开口对你说了「欢迎回家」。从那天起你知道了这个家的秘密："
    "猫铃堂的猫会说话，但只对这个家的主人说。白天照常开店，客人们只当猫叫；"
    "打烊之后，这群猫围着你，吵吵闹闹地要把外婆在时的日子一天天过回来。"
    "枕头边的位置、傍晚的缘廊、谁先蹭到你——都有猫在认真计较。"
)

WORLD_FACTS = (
    "【会说话的猫】猫铃堂的猫只对这个家的主人说话，外人听来只是猫叫；这是老宅的秘密，"
    "猫们守口如瓶，来由藏在外婆的日记里。【他们就是猫】猫的身体、猫的习性、猫的行为逻辑："
    "开不了门就挠门、高兴了踩奶、吃醋了用身体挤位置；心动与撒娇全用猫的方式表达。"
    "【猫咖日常】白天营业：客人、罐头、猫的班次（谁在前厅营业、谁躲后院）；打烊后是"
    "一家人的时间。【铃铛】门口的铃铛串是外婆留下的暗号系统，每种响法有含义，福婆在慢慢教你。"
    "【钱】小店薄利，靠客人与口碑；猫们对小鱼干的采购预算有强烈意见。"
    "【基调】治愈系乙女日常：轻快、温暖、偶尔一点想念外婆的酸，绝不狗血。"
)

SYNOPSIS = (
    "治愈系猫咪乙女沙盒：你继承外婆的猫咖，和五只会说话的猫同居——温柔的布偶、毒舌的暹罗、"
    "沉默的缅因、神秘的黑猫、圆滚滚的橘猫。经营小店，听懂铃铛，翻开外婆的日记，"
    "以及在每天傍晚的缘廊上，被猫认真地、排着队地偏爱。时间与现实同步，日子永不落幕。"
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
                   tagline="猫铃堂的新主人", background="没有来历，也没有归期。"))
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
            one_liner="猫咪乙女恋爱沙盒：继承外婆的猫咖，被五只会说话的猫排着队认真偏爱。",
            synopsis=SYNOPSIS,
            world_long=WORLD_LONG,
            world_facts=WORLD_FACTS,
            style=STYLE,
            relations_overview="五只猫各有性子与心事：枕边的位置、傍晚的缘廊、你手心的温度，"
            "都有猫在认真计较；老三花看着这一切，像外婆还在时那样。",
            trope_tags=["乙女", "猫咪", "治愈", "恋爱", "沙盒", "现实同步"],
            characters=CHARACTERS,
            acts=ONE_ACT,
            endings=[],
            locations=LOCATIONS,
            sandbox={"enabled": True, "real_time": True, "currency": "元", "start_money": 200,
                     "opening_visitor": "nk_yuki",
                     "default_powers": [
                         "听懂猫语：猫铃堂的猫对你说的话，你一个字都不会漏"]},
            phone={"enabled": True, "device": "手机"},
            tuning={"world_event_every": 0, "max_new_characters": 8,
                    "vn_mode": 1, "plan_render": 1, "art_style": ART_STYLE,
                    # 💘 甜宠配方 (Yi 拍板的调参): 更易心动、更抗跌
                    "rom_taper_den": 180, "rom_step_max": 8,
                    "flirt_t": 16, "lover_t": 42, "lover_close_min": 25,
                    "affinity_clamp_min": -1, "close_step_min": -2, "rom_step_min": -1,
                    "promise_break_cost": 2},
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
        print(f"   🐱 乙女猫咖: cast ×{len(CHARACTERS)} (五档防御风格全齐+老三花), "
              f"locations ×{len(LOCATIONS)}, 真实摄影画风, 甜宠调参实装")
    finally:
        db.close()


if __name__ == "__main__":
    main()
