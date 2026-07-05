# -*- coding: utf-8 -*-
"""Seed "The Lighthouse at Gull Point" — the first ENGLISH story (story.language="en").

NA-flavored cozy romance with real gated secrets: small town, grumpy/sunshine,
an inherited lighthouse, a keeper who won't say why he stays, and a last letter
that was never mailed. Validates the en pipeline end to end (prompts, deterministic
narration, phone/letters, examples voice lines).

Run:  python seed_gullpoint.py   (idempotent; publishes public v1)
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from datetime import datetime  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Fragment, Persona, Run, Secret, Story, StorySnapshot, User  # noqa: E402
from app.routers.stories import _to_secret, _to_story  # noqa: E402
from app.security import hash_password  # noqa: E402

TITLE = "The Lighthouse at Gull Point"
DEMO_EMAIL = "demo@linguisplay.app"
DEMO_PW = "demo12345"

CHARACTERS = [
    {
        "id": "gp_wren", "name": "Wren Hale", "role": "illustrator; Marta's niece, the new owner",
        "is_lead": False, "playable": True,
        "persona_text": "Twenty-eight, city-worn, travels light. Inherited the Gull Point "
        "lighthouse from her aunt Marta, whom she hadn't visited in six years — a fact "
        "she carries like a stone in her coat pocket.",
        "background": "Came to sign papers and sell the place. That was the plan, anyway.",
        "items": [{"name": "sketchbook", "detail": "half-filled; the last page is a drawing "
                   "of a lighthouse she made at nine"}],
    },
    {
        "id": "gp_elias", "name": "Elias Ward", "role": "the lighthouse keeper",
        "is_lead": True,
        "persona_text": "Late thirties, weathered hands, economical with words the way "
        "sailors are with fresh water. Fixes things before you notice they're broken. "
        "Acts like the lighthouse is his — and in every way that matters, for seven "
        "years, it has been.",
        "background": "Nobody in town remembers hiring him. He was just there one spring, "
        "and Marta never explained.",
        "eq_style": "gruff on the surface, care delivered as logistics; deflects feelings "
        "with weather reports and chores",
        "agenda": "keep paying a debt nobody asked him to pay — and keep the reason buried "
        "with Marta",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend", "flirt", "lover", "enemy"],
        "examples": [
            "Storm glass says otherwise.",
            "…You eat yet? There's chowder. Wasn't made for you, it just exists.",
            "The light doesn't care how you feel. You wind it anyway.",
            "Marta's ladder. Third rung's soft. Use mine.",
        ],
        "bio_layers": [
            {"closeness_min": 12, "text": "He owns exactly one photograph. It lives face-down "
             "in the drawer with the fuses."},
            {"closeness_min": 25, "text": "He can't swim anymore. Not can't — won't. There's "
             "a difference, and he knows which one it is."},
        ],
        "schedule": [
            {"from_act": 1, "location_id": "gp_lantern", "slots": ["夜"]},
            {"from_act": 1, "location_id": "gp_kitchen", "slots": ["晨"]},
        ],  # afternoons unscheduled = out on the rocks somewhere — call him
        "ties": [{"char_id": "gp_june", "stance": 1, "label": "she saves him the corner booth"}],
    },
    {
        "id": "gp_june", "name": "June Okafor", "role": "owner of the Salt & Paper diner",
        "persona_text": "Sixty-ish, silver locs, runs the diner and, informally, the town's "
        "memory. Feeds people information the way she feeds them pie: warm, in slices, "
        "never the whole thing at once.",
        "eq_style": "warmth first, truth second, both eventually; reads you over the rim "
        "of a coffee pot",
        "agenda": "Marta was her best friend. She promised to watch over both of them — "
        "the keeper and the niece — until they figure it out",
        "examples": [
            "Sugar, in this town the tide brings everything back. Twice.",
            "Ask him about the winter of the wreck. Or don't. Some doors you knock on soft.",
        ],
        "home_location_id": "gp_diner",
        "ties": [{"char_id": "gp_elias", "stance": 2, "label": "promised Marta she'd feed him"}],
    },
]

LOCATIONS = [
    {"id": "gp_kitchen", "name": "Lighthouse Kitchen", "detail": "A wood stove, two mugs on "
     "hooks (one says MARTA), a tide chart taped to the fridge with surgical precision. "
     "It smells of coffee and machine oil.",
     "exits": ["Lantern Room", "Salt & Paper Diner", "The Cove"]},
    {"id": "gp_lantern", "name": "Lantern Room", "detail": "Three hundred sixty degrees of "
     "gray Atlantic. The great lens turns with a sound like a slow heartbeat. Everything "
     "brass is polished; everything wooden is worn.",
     "exits": ["Lighthouse Kitchen"],
     "props": [{"name": "keeper's logbook", "detail": "Seven years of weather in a tight, "
                "careful hand. The first winter's pages are water-stained.",
                "fragment_id": "gp_letter2"}]},
    {"id": "gp_diner", "name": "Salt & Paper Diner", "detail": "Six booths, a pie case, a "
     "wall of Polaroids going back forty years. The corner booth has a RESERVED sign that "
     "everyone ignores except one man.",
     "exits": ["Lighthouse Kitchen"]},
    {"id": "gp_cove", "name": "The Cove", "detail": "A crescent of black rock and cold sand "
     "below the light. At low tide you can see the ribs of an old hull, furred with "
     "seaweed, like something the sea is still deciding whether to give back.",
     "exits": ["Lighthouse Kitchen"],
     "unlock": {"act_min": 2}},
]

ACTS = [
    {"id": "a1", "index": 1, "title": "Arrival", "time": {"day": 1, "slot": "晨"},
     "goal": "You came to sell the lighthouse. First, figure out who this keeper is — "
             "and why he acts like he was never hired",
     "advance": {"required_fragment_ids": ["gp_stay1"]},
     "events": [
         {"id": "gp_e_arrive", "what_happens": "Elias sets a second mug on the table without "
          "being asked, then seems annoyed at his own hand for doing it.",
          "who_character_ids": ["gp_elias"]},
     ]},
    {"id": "a2", "index": 2, "title": "Low Tide", "time": {"day": 2},
     "goal": "June knows something about a letter your aunt left. Get it out of her — "
             "gently, over pie",
     "advance": {"required_fragment_ids": ["gp_letter1"]},
     "events": [
         {"id": "gp_e_storm", "what_happens": "The storm glass on the kitchen shelf clouds "
          "over. Elias looks at it twice and says nothing.",
          "who_character_ids": ["gp_elias"]},
         {"id": "gp_e_wreck", "what_happens": "At low tide, the ribs of an old wreck surface "
          "in the cove. Nobody in town will say whose boat it was.",
          "who_character_ids": []},
     ]},
    {"id": "a3", "index": 3, "title": "The Lantern Room", "time": {"day": 3, "slot": "夜"},
     "goal": "The letter is in the lantern room — where it has been for six years. "
             "Go up and read it",
     "choice": {
         "prompt": "The lens turns its slow heartbeat. Elias stands at the rail, not "
                   "looking at you, the letter's envelope still creased from your hands.",
         "options": [
             {"id": "stay", "label": "\"The light stays on. So do I.\"", "flag": "chose_stay",
              "character_id": "gp_elias", "closeness_delta": 4, "romance_delta": 6},
             {"id": "leave", "label": "Book the mainland ferry — some inheritances are "
              "meant to be sold", "flag": "chose_leave"},
         ]},
     "events": [
         {"id": "gp_e_light", "what_happens": "For the first time since you arrived, Elias "
          "lets someone else wind the light.", "who_character_ids": ["gp_elias"]},
     ]},
]

# (title, character_id, sensitivity, known_by, [(fid, layer, content, retrieval_key, unlock, cover)])
SECRETS = [
    ("Why the keeper stays", "gp_elias", "medium", ["gp_elias", "gp_june"], [
        ("gp_stay1", 1,
         "Nobody hired Elias. The winter his boat went down, Marta took him in — fed him, "
         "gave him the keeper's room, never once asked when he was leaving. He stayed to "
         "repay a debt she refused to ever name.",
         "why stay keeper hired job here seven years debt marta took him in",
         {"affinity_min": 8, "act_min": 1, "asks_min": 2},
         "It's a job. Someone has to keep the light. That's the whole story."),
        ("gp_stay2", 2,
         "It was Marta's light that brought him through the rocks that night. He made the "
         "swim. His brother Danny didn't. The wreck in the cove is the *Marigold* — their "
         "boat. He winds her light every night like an apology to both of them.",
         "wreck boat brother danny night storm marigold cove drowned survivor",
         {"affinity_min": 18, "act_min": 2, "asks_min": 3},
         None),
    ]),
    ("Marta's last letter", "gp_june", "medium", ["gp_june", "gp_elias"], [
        ("gp_letter1", 1,
         "Marta left a letter — not with the lawyer, with Elias. Addressed to \"whichever "
         "of you two fools reads it first.\" June watched her seal it at the corner booth "
         "the month before she passed.",
         "letter aunt marta left for me lawyer will note wrote message",
         {"affinity_min": 6, "act_min": 2, "asks_min": 2},
         "Your aunt? She left paperwork, sugar. Everybody leaves paperwork."),
        ("gp_letter2", 2,
         "Tucked in the logbook's water-stained first winter: 'Elias — the light was never "
         "a debt. It was a welcome. Stop paying me back and start living, or I swear I'll "
         "haunt the chowder. And Wren — the place isn't yours to sell, it's yours to "
         "*keep*. There's a difference. Ask him which one it is.'",
         "logbook letter read lantern room hidden pages first winter",
         {"location_id": "gp_lantern", "act_min": 3},
         None),
    ]),
]

ENDINGS = [
    {"id": "gp_end_true", "kind": "true", "title": "Keep the Light",
     "text": "Elias takes the letter back like it's made of shell. \"She'd haunt the "
             "chowder. She would, too.\" He almost smiles — then does, and it changes his "
             "whole face. Below you the town blinks on, and the light sweeps out over the "
             "water, not a debt to anyone anymore. \"Third rung's still soft,\" he says. "
             "\"I'll fix it in the morning. We'll fix it.\"",
     "condition": {"affinity_min": 20, "act_min": 0,
                   "required_fragment_ids": ["gp_letter2"],
                   "required_flags": {"chose_stay": True}}},
    {"id": "gp_end_normal", "kind": "normal", "title": "The Mainland Road",
     "text": "The ferry pulls out at dawn. From the rail you watch the light make its "
             "slow, stubborn turn, and you understand it will keep turning whether anyone "
             "watches or not. In your sketchbook, on the last page, someone has penciled "
             "a small, careful correction to your nine-year-old lighthouse: the lantern "
             "room, drawn true.",
     "condition": {"act_min": 0, "required_flags": {"chose_leave": True}}},
]


def get_or_create_demo_user(db) -> User:
    u = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if u:
        return u
    u = User(email=DEMO_EMAIL, password_hash=hash_password(DEMO_PW),
             dob=datetime(1990, 1, 1), accepted_tos=True, display_name="Demo 作者")
    db.add(u)
    db.commit()
    db.refresh(u)
    db.add(Persona(owner_id=u.id, name="我", pronouns="they", is_default=True))
    db.commit()
    return u


def wipe_existing(db, owner_id: str) -> None:
    for s in db.query(Story).filter(Story.owner_id == owner_id, Story.title == TITLE).all():
        db.query(Run).filter(Run.story_id == s.id).delete()
        db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id).delete()
        db.delete(s)
    db.commit()


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        user = get_or_create_demo_user(db)
        wipe_existing(db, user.id)

        story = Story(
            owner_id=user.id, title=TITLE, language="en",
            one_liner="You inherited a lighthouse. It came with a keeper nobody remembers hiring.",
            synopsis="Wren Hale comes to Gull Point to sell the lighthouse her aunt left "
            "her. But the keeper acts like the place is his, the town won't say whose "
            "wreck rusts in the cove, and there's a letter her aunt never mailed — "
            "addressed to 'whichever of you two fools reads it first.'",
            world_long="A small fishing town on a cold Atlantic coast, present day, "
            "early autumn. The lighthouse stands on the point above a crescent cove; "
            "the town below has one diner, one church, and forty years of Polaroids.",
            world_facts="Four places: Lighthouse Kitchen (connects to everything), "
            "Lantern Room above, Salt & Paper Diner in town, The Cove below the light. "
            "The keeper's logbook lives in the lantern room. Wren carries a sketchbook.",
            relations_overview="Wren (you) inherited the light; Elias has kept it for "
            "seven unexplained years; June runs the diner and knew Marta best.",
            trope_tags=["romance", "cozy", "small-town", "grumpy-sunshine", "slow-burn"],
            characters=CHARACTERS, acts=ACTS, endings=ENDINGS, locations=LOCATIONS,
            phone={"enabled": True, "device": "phone"},
            tuning={"golden_chance": 6, "rom_taper_den": 100},
            visibility="public",
        )
        db.add(story)
        db.flush()

        for title, char_id, sens, known_by, frags in SECRETS:
            sec = Secret(story_id=story.id, character_id=char_id, title=title, sensitivity=sens)
            sec.fragments = [
                Fragment(id=fid, layer=l, content=c, retrieval_key=r,
                         known_by_character_ids=known_by, unlock=u, cover=cov)
                for (fid, l, c, r, u, cov) in frags
            ]
            db.add(sec)
        db.flush()
        db.refresh(story)

        content = {"story": _to_story(story).model_dump(),
                   "secrets": [_to_secret(s).model_dump() for s in story.secrets]}
        content["story"]["version"] = 1
        db.add(StorySnapshot(story_id=story.id, version=1, content=content))
        story.version = 1
        story.status = "published"
        db.commit()

        n_frag = sum(len(f) for *_, f in SECRETS)
        print(f"OK seeded <{TITLE}> story_id={story.id} secrets={len(SECRETS)} fragments={n_frag}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
