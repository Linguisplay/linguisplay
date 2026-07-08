# -*- coding: utf-8 -*-
"""Seed 《斗气大陆·迦南学院》 — 《斗破苍穹》同人致敬沙盒（非商用内测，文本全部原创）.

原著剧情不是被"导入"，而是被蒸馏成三层：
  · 世界规则 → world_facts（斗气段位/炼药师品阶/异火传说/魔核经济，模型每轮扣着写）
  · 标志性人物 → authored cast（原创小传+台词声线；沙盒有 authored 角色时跳过随机生成）
  · 标志性地点 → authored locations（内院+黑角域边镇+魔兽山脉，其余靠涌现地点自己长）
原著大事件不重播：玩家以内院新晋学员的身份走进这个世界的"当前状态"，往后由玩家写。

Run:  python seed_doupo.py
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

TITLE = "斗气大陆·迦南学院"

ONE_ACT = [
    {"id": "dp_a1", "index": 1, "title": "入塔",
     "goal": "你通过了迦南学院内院的入塔考核，成为新晋学员。认识这片大陆，或者让它记住你的名字。",
     "advance": {}, "events": []},
]

CHARACTERS = [
    {
        "id": "dp_xiaoyan", "name": "萧炎", "is_lead": True,
        "wants": "夺得炼气塔深处传闻中的那道异火，让萧家从此不再被人踩在脚下",
        "role": "内院学员 · 年轻炼药师兼斗者",
        "persona_text": "乌坦城萧家的少年：四岁成名，十一岁跌落谷底，被人当众退过婚，也当众"
        "赢回过脸面。话不多，恩和仇都在心里记账。手上常年戴一枚古旧黑戒，无聊时会下意识"
        "摩挲，问起只说是遗物。炼药时比谁都静，出手时比谁都狠；对朋友大方到倾囊，"
        "对敌人耐心到可怕。",
        "examples": ["三十年河东，三十年河西，莫欺少年穷。",
                     "丹药可以炼。价钱，按我的规矩来。",
                     "萧家的人，可以死，不能跪。",
                     "……戒指？祖上传下的，不值钱。",
                     "这笔账记下了。不急，我记性一向很好。"],
        "home_location_id": "dp_tower",
        "relation_default": "peer",
        "relation_allowed": ["peer", "friend", "flirt", "lover", "enemy"],
        "items": [{"name": "古旧黑戒", "detail": "磨得发亮的黑色戒指，贴着皮肤时似有若无地发暖"}],
    },
    {
        "id": "dp_xuner", "name": "萧薰儿",
        "love_style": "sunny",
        "wants": "守在萧炎哥哥身边，同时瞒住自己终究要回去的那个地方",
        "role": "内院公认的第一天才少女 · 金色斗气",
        "persona_text": "内院年轻一辈公认的第一天才，一身金色斗气华贵得不像凡俗功法。"
        "对谁都温柔有礼，退让三分，唯独提起某个名字时眼睛会亮。来历成谜：功法、玉佩、"
        "以及暗处似有似无护着她的影子，没人敢深究。温柔是真的，底线也是真的；"
        "碰她底线的人，见过她另一副样子。",
        "examples": ["萧炎哥哥在哪，薰儿就在哪。",
                     "这位同学，请自重。方才的话，薰儿就当没听见。",
                     "要变强呀。不变强，想守的人和想守的约定，都守不住呢。",
                     "这枚玉佩你收好。若真到了走投无路的时候，就捏碎它。"],
        "home_location_id": "dp_plaza",
        "relation_default": "peer",
        "relation_allowed": ["peer", "friend", "flirt", "lover"],
        "items": [{"name": "金纹玉佩", "detail": "触手温润，纹路古老得认不出朝代"}],
    },
    {
        "id": "dp_yafei", "name": "纳兰嫣然",
        "love_style": "tsundere",
        "wants": "在下一次宗门大比前突破斗灵，证明当年那纸退婚书没有错",
        "role": "云岚宗年轻一辈第一人 · 风属性剑修",
        "persona_text": "云岚宗宗主亲传，天骄之名压了同辈整整一代。骄傲刻在骨子里，认错比"
        "登天还难；当年亲手递出的那纸退婚书，如今悔与不悔只有她自己知道。奉宗门之命"
        "在黑角域一带历练，嘴上永远得理不饶人，暗地里把某人的消息收集得比谁都全。",
        "examples": ["我没有错。就算有，也轮不到你来说。",
                     "哼，他？我只是……顺路问一句。",
                     "云岚宗的剑，不斩无名之辈。报上名来。",
                     "伤药放这了。别误会，是师尊让我捎的。"],
        "home_location_id": "dp_town",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend", "flirt", "lover", "enemy"],
    },
    {
        "id": "dp_medusa", "name": "美杜莎",
        "love_style": "possessive",
        "wants": "讨回那笔没算清的账，顺便盯死那个总敢跟她讨价还价的人类",
        "role": "蛇人一族的女王 · 斗皇强者",
        "persona_text": "塔戈尔大沙漠蛇人一族的女王，斗皇级的强者，因一桩没算清的账在人类"
        "地界游走。冷艳，骄矜，杀性重；嘴上说着下次见面必取你性命，身影却一次次出现在"
        "同一个人附近。占有欲极强：她认定的东西，别人多看一眼都算冒犯。对蛇人族人"
        "护短到不讲道理。",
        "examples": ["本王后还没允许你死。",
                     "账没算清。在那之前，你的命暂时归我。",
                     "退后。敢碰他的人，先问过我的蛇瞳。",
                     "……闭嘴。再笑，舌头就不用留着了。"],
        "home_location_id": "dp_wild",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "enemy", "peer", "friend", "flirt", "lover"],
    },
    {
        "id": "dp_yixian", "name": "小医仙",
        "love_style": "avoidant",
        "wants": "找到压住体内那股东西的法子，在此之前，不和任何人走得太近",
        "role": "行走黑角域的白衣医师",
        "persona_text": "黑角域边镇上人人念好的白衣医师，出诊不问出身，收费随缘。温软安静，"
        "笑起来眉眼弯弯，却总与人隔着一步距离，从不与人碰手。身上藏着会自己长大的剧毒，"
        "越亲近的人越危险，于是把所有喜欢都折成疏远。黑角域的恶人背地里叫她另一个名字，"
        "没人敢当面提。",
        "examples": ["药三分毒。我这个人，十分。",
                     "别靠太近。不是讨厌你，是替你着想。",
                     "伤口给我看看。手不必给我，把东西放桌上就好。",
                     "哪天我要是喊你跑，你要头也不回地跑。"],
        "home_location_id": "dp_town",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend", "flirt", "lover"],
        "items": [{"name": "白瓷药瓶", "detail": "瓶身干净得过分，塞子上系着褪色的红绳"}],
    },
    {
        "id": "dp_yunyun", "name": "云韵",
        "love_style": "aloof",
        "wants": "以「云芝」之名查清黑角域近来暗流的源头，别让它烧到宗门",
        "role": "微服游历的女子 · 深不可测（自称云芝）",
        "persona_text": "自称云芝的游历女子，衣着素净，谈吐从容，喜怒不形于色。看山看水"
        "也看人心，出手极少，一旦出手，斗宗级的威压瞒不了明眼人。真实身份是一宗之主，"
        "背着整个宗门的重量微服南下，把自己的心事压在最底下。对晚辈温和，"
        "对逾矩者从不留情。",
        "examples": ["叫我云芝就好。别的名字，太重。",
                     "山下的雨，比山上的暖。",
                     "……放肆。跪下。",
                     "有些债，宗门替不了我还。"],
        "home_location_id": "dp_town",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "elder", "friend", "flirt", "lover"],
    },
]

LOCATIONS = [
    # first location = the run's starting place: open where people are
    {"id": "dp_plaza", "name": "内院广场",
     "detail": "迦南学院内院的心脏：黑石广场中央立着丈高的火能榜，榜上名次与火能数"
     "每个时辰刷新一次；公告碑前永远围着看排名战战书的学员。",
     "exits": ["天焚炼气塔", "内院交易集市", "斗技场", "药庐"],
     "props": [{"id": "dp_p_board", "name": "公告碑",
                "detail": "排名战战书、塔层开放时刻与院规同刻一碑，碑角有一行新凿的小字。"}]},
    {"id": "dp_tower", "name": "天焚炼气塔",
     "detail": "黑铁色的巨塔半埋入地，塔内热浪扑面，蕴气室按层收火能；越往下层"
     "热意越烈，最深处常年封着铁门，老学员提起塔底都会压低声音。",
     "exits": ["内院广场"],
     "props": [{"id": "dp_p_crystal", "name": "蕴气室水晶牌",
                "detail": "登记修炼时长与火能扣数的水晶牌，背面有前一位使用者的划痕。"}]},
    {"id": "dp_market", "name": "内院交易集市",
     "detail": "内院学员以物易物的集市：功法残页、魔核、药材摊子一路摆开，"
     "以火能计价；吆喝声里三句不离「加价」和「血亏」。",
     "exits": ["内院广场", "黑角域边镇"],
     "props": [{"id": "dp_p_stall", "name": "以物易物交换板",
                "detail": "写满求购与出让：三阶魔核、聚气散、还有人重金求一截不知名的枯木。"}]},
    {"id": "dp_arena", "name": "斗技场",
     "detail": "环形黑石看台围着十座斗台，排名战在这里打，胜者拿火能，败者掉名次；"
     "石面上的焦痕与裂缝层层叠叠，像一部没人整理的战史。",
     "exits": ["内院广场"]},
    {"id": "dp_pill", "name": "药庐",
     "detail": "内院炼药师们的地盘：药香混着淡淡焦糊味，隔间里此起彼伏的咳嗽声"
     "说明今天又有人炸了炉；墙上挂着「炸炉三次，本月禁入」的木牌。",
     "exits": ["内院广场"],
     "props": [{"id": "dp_p_herb", "name": "公用药材架",
                "detail": "一二阶药材按格摆放，牌子写着「取用登记，损坏照赔」。",
                "take": True}]},
    {"id": "dp_town", "name": "黑角域边镇",
     "detail": "紧贴黑角域的灰色小镇：赏金榜和通缉令贴满同一面墙，酒馆白天就坐满"
     "带兵器的人；这里没有王法，只有拳头和规矩，外来者最好先学会低头走路。",
     "exits": ["内院交易集市", "魔兽山脉外缘"],
     "props": [{"id": "dp_p_bounty", "name": "赏金墙",
                "detail": "从缉拿马贼到悬赏魔核都有；最上面那张人皮纸的赏格高得离谱，没署名。"}]},
    {"id": "dp_wild", "name": "魔兽山脉外缘",
     "detail": "连绵的黑绿色山影压在地平线上，林间不时传来兽吼；外缘只有一二阶魔兽，"
     "但老猎人说，山里的雾一旦变紫，多高段位都得跑。",
     "exits": ["黑角域边镇"]},
]

WORLD_LONG = (
    "这里没有魔法，斗气为尊。四岁测灵根、十岁凝斗之气，此后一步一个段位往上爬，"
    "爬不动的人一辈子留在尘埃里。大陆广袤：帝国、宗门、学院、蛮荒各占一方，"
    "强者一怒可以夷平城池，弱者连愤怒的资格都没有。迦南学院坐落在黑角域边缘，"
    "是大陆最负盛名的学府；学院内院只收精英，靠火能与排名说话。你是刚通过入塔考核的"
    "新晋学员，档案上写着你的段位。至于档案之外你还藏着什么，只有你自己知道。"
)

WORLD_FACTS = (
    "【斗气体系】修炼分段位：斗之气（一至九段）之后依次为斗者、斗师、大斗师、斗灵、"
    "斗王、斗皇、斗宗、斗尊乃至更上。跨段位如隔天堑，越级挑战是搏命。斗气可凝护体罡气、"
    "可化翼飞行（斗王以上）；功法与斗技分天地玄黄四阶，来路都要用命换。"
    "【炼药师】丹药分一至九品，炼药师以品阶论尊卑，一品难求；炼药需灵魂感知力，"
    "天生注定，故炼药师地位超然，各方势力争相供奉。丹药能疗伤、能助突破，也能成瘾成毒。"
    "【异火】天地间流传着一份异火榜：二十余种天地奇火，可炼丹、可焚敌、可重塑体质；"
    "吞纳异火是以命相搏的豪赌，成则脱胎换骨，败则化为灰烬。【魔核经济】魔兽依阶分级，"
    "魔核是硬通货；金币通行市井，内院则以火能计价，火能靠排名战与塔内修炼赚取。"
    "【内院规矩】强者为尊，排名说话；排名战下战书应战，斗台上生死自负，台下私斗重罚。"
    "【黑角域】学院之外紧邻黑角域：法外之地，恶人、逃犯与野修的乐园，实力是唯一通行证。"
    "【暗流】各方宗门与帝国在此地都埋着眼线；近来边镇夜里常有人失踪，没人报官，"
    "因为这里没有官。"
)

SYNOPSIS = (
    "《斗破苍穹》同人致敬 · 非商用内测 · 文本全部原创。原著剧情不在这里重播："
    "这里是那片大陆本身。你以内院新晋学员的身份走进迦南学院，和萧炎他们做同窗，"
    "修炼、炼药、下战书、闯黑角域，也可能在塔底铁门前听见不该听见的呼吸。"
    "时间与现实同步，剧情永不落幕；开局可以声明你的金手指（默认：异火亲和之体）。"
    "你会受伤，会破产，也可能死在魔兽山脉：这个世界不迁就任何人，包括主角。"
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
                   tagline="刚到这片大陆的人", background="没有来历，也没有归期。"))
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
            one_liner="《斗破苍穹》同人沙盒：以内院新晋学员的身份，活在斗气为尊的那片大陆。",
            synopsis=SYNOPSIS,
            world_long=WORLD_LONG,
            world_facts=WORLD_FACTS,
            style=(
                "天蚕土豆式爽文节奏：小白文直给，事件链永远向前（蓄势、受挫、打脸、升级），描写只为气势服务且一笔带过；等级压制写实感，关键处短句砸。叙事经济学（最高优先）：每一轮必须有一件具体的事向前发生（新行动/新变故/新决定），环境与外貌描写全轮合计不超过两句，形容词能删则删，绝不原地渲染气氛。忌温吞，忌华丽堆藻，忌文艺腔冲淡爽感。"),
            relations_overview="萧炎他们各有各的路要走；你是新来的，关系全靠自己处。",
            trope_tags=["斗破苍穹", "同人致敬", "玄幻", "修炼", "炼药", "沙盒", "现实同步"],
            characters=CHARACTERS,
            acts=ONE_ACT,
            endings=[],      # a sandbox has no exits
            locations=LOCATIONS,
            sandbox={"enabled": True, "real_time": True, "currency": "金币", "start_money": 500,
                     "progression": {"name": "斗气", "ranks": ["斗之气九段", "斗者", "斗师", "大斗师", "斗灵", "斗王", "斗皇", "斗宗", "斗尊"]},
                     "default_powers": [
                         "异火亲和之体：你天生不惧火毒，有资格尝试吞纳炼化传说中的异火；"
                         "但每一次吞纳都是以命相搏的豪赌，成则脱胎换骨，败则化灰"]},
            phone={"enabled": True, "device": "传讯符"},
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
        print("   🔥 authored cast ×6, locations ×7, real_time sandbox, 默认金手指=异火亲和之体")
    finally:
        db.close()


if __name__ == "__main__":
    main()
