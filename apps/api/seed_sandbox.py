"""Seed the 🏖 endless SANDBOX stories.

Each is a published sandbox shell: the player may define/append a worldview at run
creation (their run's private pinned copy takes it), the opening cast is conjured from
the world, time syncs to the REAL world, and the plot never ends. The player can die;
death strips 说/做 and leaves them a watcher.

Run:  python seed_sandbox.py
Idempotent: wipes prior copies (same titles + demo owner) and their runs/snapshots,
then recreates and publishes them.
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

ONE_ACT = [
    {"id": "a1", "index": 1, "title": "无尽",
     "goal": "这个世界刚刚注意到你。去认识它，或者让它认识你。",
     "advance": {}, "events": []},
]

SANDBOXES = [
    {
        "title": "无界之地",
        "one_liner": "你来定义这个世界。时间与现实同步，剧情永不落幕，但你会死。",
        "synopsis": "一个无尽沙盒：开局写下你想要的世界观，世界就照它生长。人物、地点、事端都在你走动时"
        "生成；这里的一天就是现实的一天，夜里的约定要等到真正的明晚才作数。没有结局，没有存档点，"
        "只有一路发生并且不可撤销的事。你可能受伤、可能垂危、也可能死去。死者不能说话，不能动手，"
        "只能看着这个世界在没有你之后继续下去。",
        "world_long": "一座名为「无界」的滨海小城：老城区的巷子窄得两人错身要侧肩，新区的玻璃楼一到夜里"
        "亮得像另一个城市。港口每天有船进出，带来陌生的人和说不清来路的货。城里人人都有正经营生，"
        "也人人都有不愿说破的事。你是刚落脚的新面孔，没有人认识你。这既是麻烦，也是机会。",
        "world_facts": "这是一个由玩家在开局定义的世界；以运行时的【世界观/场景设定】为唯一事实基础。",
        "relations_overview": "所有人物都在你踏入这个世界之后才诞生，关系由你亲手织成。",
        "trope_tags": ["沙盒", "开放世界", "现实同步", "永不落幕"],
        "phone": {"enabled": True, "device": "手机"},
        "tuning": {"world_event_every": 0, "max_new_characters": 12},
    },
    {
        "title": "九龙城寨·浮生",
        "one_liner": "三不管的城中之城。你租下一间天台屋，从今天起在这里讨生活。",
        "synopsis": "不查案、不破局，就在城寨里活下去：找一门营生、认几张脸、欠几笔人情、惹一点是非。"
        "这里的一天就是现实的一天，面档明早开市就真得明早再来。城寨不会给你剧本，它只会给你后果："
        "帮谁、得罪谁、赚到的和赔出去的，都记在这座城的账上。没有结局；你要是死在巷子里，"
        "城寨会照常醒来，只是再没有你说话的份。",
        "world_long": "一九八几年的九龙城寨：三万多人叠在两百多栋违建里，天线和晾衣杆把天空割成碎片，"
        "巷子深处白天也要开灯。城寨三不管，警察不进来，规矩由街坊会和堂口一起立。无牌牙医、鱼蛋作坊、"
        "云吞面档、发廊、麻雀馆挤在同一条巷里；楼上是补习社，楼下在分账。水管电线都是私拉的，"
        "谁家断了水，整层楼都知道。你是新搬进来的，租了一间天台屋，交了三个月押金，口袋里剩的钱不多了。",
        "world_facts": "【空间】城寨是一座立体迷宫：巷道最窄处不足一米，楼与楼在半空以天桥和排水管相连；"
        "地下水道有人走私，天台是另一个世界，天线森林下晒着腊味和床单。"
        "【规矩】警察不进城寨；纠纷找街坊会或堂口话事人评理；生人问路要先报来意；欠债可以慢慢还，"
        "但不能装不认。【生计】无牌诊所、作坊、面档、麻雀馆是城寨的血脉；租金按尺算，现金交易，"
        "手艺人最受敬重。【基调】港风市井人情戏：嘴硬心软的街坊、各怀心事的堂口、白天见得着的善意"
        "和入夜才露头的凶险。",
        "relations_overview": "城寨里的人物在你搬进来之后陆续与你相遇；谁把你当街坊、谁盯上你的押金，"
        "都看你怎么做人。",
        "trope_tags": ["九龙城寨", "港风", "市井", "沙盒", "现实同步"],
        "phone": {"enabled": True, "device": "传呼机"},
        "tuning": {"world_event_every": 0, "max_new_characters": 12},
    },
    {
        "title": "转生异世界·后宫物语",
        "one_liner": "卡车、白光、两轮月亮。你转生到了剑与魔法的异世界，这一世的桃花运好得离谱。",
        "synopsis": "经典日式异世界转生：带着前世全部记忆在陌生的草原上醒来，半天路程外就是冒险者公会城"
        "「晨钟镇」。接委托、练剑学法、探遗迹，从 F 级慢慢往上爬；这个世界格外眷顾你，"
        "遇到的人也总会多看你两眼。骑士、法师、精灵、公会前台，每个人都有自己的骄傲与心结，"
        "情感线大胆推进但绝不倒贴。时间与现实同步，永不落幕；异世界也会死人，包括你。",
        "world_long": "你记得的最后一件事，是深夜加班后过马路时那对刺眼的车灯。再睁眼，你躺在一片"
        "陌生的草原上，头顶挂着两轮月亮。这里是剑与魔法的世界「艾尔特兰」：城邦由冒险者公会维系秩序，"
        "人族、精灵、兽人、龙裔混居，古代遗迹里沉睡着旧帝国的魔导器，北境流传着魔王复苏的谣言。"
        "你带着前世的全部记忆，而这个世界似乎格外眷顾你：学什么都快得离谱，还总能在别人身上"
        "看出些他们没说出口的东西。公会城「晨钟镇」就在半天路程之外，炊烟已经望得见了。",
        "world_facts": "【设定】玩家是转生者，保有前世（现代地球）的全部记忆，对这个世界的常识"
        "反而一无所知；转生特典是学习速度惊人、直觉敏锐。【世界】冒险者公会发布委托、评定等级"
        "（F 到 S）；魔法凭亲和力，剑技凭修行；教会能治疗但收费；北境有魔王复苏的传闻，无人证实。"
        "【基调】轻小说式的异世界日常与冒险：升级、结伴、被形形色色的人在意。感情线大胆推进，"
        "角色们对玩家动心比常人快，但各有骄傲与心结，绝不无缘无故倒贴；吃醋、争风、暗中较劲"
        "都可以发生。",
        "relations_overview": "同伴与心动对象都在冒险途中相遇；后宫不是白来的，每一份心动都要你亲手挣。",
        "trope_tags": ["异世界", "转生", "后宫", "轻小说", "沙盒"],
        "phone": {"enabled": True, "device": "传讯水晶"},
        # 后宫向：心动涨幅的衰减放缓一点，其余同款
        "tuning": {"world_event_every": 0, "max_new_characters": 12, "rom_taper_den": 160},
    },
]


def get_or_create_demo_user(db) -> User:
    u = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if u:
        return u
    u = User(
        email=DEMO_EMAIL,
        password_hash=hash_password(DEMO_PW),
        dob=datetime(1990, 1, 1),
        accepted_tos=True,
        display_name="Demo 作者",
    )
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
        for sb in SANDBOXES:
            wipe_existing(db, user.id, sb["title"])
            story = Story(
                owner_id=user.id,
                title=sb["title"],
                one_liner=sb["one_liner"],
                synopsis=sb["synopsis"],
                world_long=sb["world_long"],
                world_facts=sb["world_facts"],
                relations_overview=sb["relations_overview"],
                trope_tags=sb["trope_tags"],
                characters=[],   # conjured per-run from the worldview
                acts=ONE_ACT,
                endings=[],      # a sandbox has no exits
                locations=[],    # the start place is synthesized; the map grows emergently
                sandbox={"enabled": True, "real_time": True},
                phone=sb.get("phone"),
                tuning=sb["tuning"],
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
            print(f"✅ Seeded 《{sb['title']}》  story_id={story.id}")
        print("   🏖 all sandboxes: real_time on, no endings, cast conjured per run.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
