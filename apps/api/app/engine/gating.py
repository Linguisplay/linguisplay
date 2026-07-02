"""The gated-RAG core — the product differentiator and the security boundary.

Fragments of a character's secret are revealed in layers, each guarded by an
unlock_schema whose conditions are ALL ANDed:

    affinity_min · act_min · asks_min · trigger_event_ids · location_id

These are evaluated server-side BEFORE any semantic (pgvector) retrieval, so a
locked fragment's `content` can never reach the LLM prompt, the phone Notes app,
or the vector index. Only the sanitized `retrieval_key` is ever embeddable, and
even that only for unlocked fragments. This module is pure (no I/O, no DB) so it
can be exhaustively unit-tested — get this wrong and the whole premise leaks.

Vocabulary:
  reveal — fragment is unlocked AND the speaker knows it → its content may be used.
  hint   — locked, but the player is close (all-but-one condition met) → the NPC
           may tease/allude, never state the content.
  hide   — locked and not close → the NPC deflects naturally, as if nothing is there.
"""

from __future__ import annotations

from typing import Any

Frag = dict[str, Any]
State = dict[str, Any]


def iter_fragments(content: dict[str, Any]) -> list[Frag]:
    """Flatten pinned_content.secrets[].fragments[] and stamp secret context onto each."""
    out: list[Frag] = []
    for secret in content.get("secrets", []) or []:
        sid = secret.get("id")
        s_char = secret.get("character_id")
        for f in secret.get("fragments", []) or []:
            out.append(
                {
                    **f,
                    "secret_id": sid,
                    "secret_title": secret.get("title", ""),
                    # fragment may override which character it belongs to; default to the secret's
                    "character_id": f.get("character_id", s_char),
                }
            )
    return out


def _asks_for(state: State, secret_id: str | None) -> int:
    return int((state.get("asks") or {}).get(secret_id, 0))


def _conditions(frag: Frag, state: State) -> list[bool]:
    """Return the AND-list of per-condition booleans for this fragment."""
    u = frag.get("unlock") or {}
    triggered = set(state.get("triggered_event_ids") or [])
    needed_events = u.get("trigger_event_ids") or []
    loc_need = u.get("location_id")  # the player must BE here (物理探索维度)
    return [
        int(state.get("affinity", 0)) >= int(u.get("affinity_min") or 0),
        int(state.get("act", 1)) >= int(u.get("act_min") or 0),
        _asks_for(state, frag.get("secret_id")) >= int(u.get("asks_min") or 0),
        all(e in triggered for e in needed_events),
        (not loc_need) or state.get("location_id") == loc_need,
    ]


def fragment_unlocked(frag: Frag, state: State) -> bool:
    return all(_conditions(frag, state))


def evaluate_unlocks(state: State, fragments: list[Frag]) -> list[str]:
    """Fragments that become newly unlocked under `state` (excludes already-unlocked).

    Unlocking is sticky: once a fragment id is in unlocked_fragment_ids it stays,
    even if the player's affinity later drops. Callers persist the union.
    """
    already = set(state.get("unlocked_fragment_ids") or [])
    newly: list[str] = []
    for f in fragments:
        fid = f.get("id")
        if fid in already:
            continue
        if fragment_unlocked(f, state):
            newly.append(fid)
    return newly


def _speaker_knows(frag: Frag, speaker_id: str | None) -> bool:
    """A fragment is usable by a speaker who knows it. Empty known_by = narrator-level
    (any speaker may reference). A non-empty list gates by membership."""
    known_by = frag.get("known_by_character_ids") or []
    if not known_by:
        return True
    return speaker_id in known_by


def classify_guard(frag: Frag, state: State) -> str:
    """reveal | hint | hide for a single fragment under the current state."""
    if frag.get("id") in set(state.get("unlocked_fragment_ids") or []):
        return "reveal"
    conds = _conditions(frag, state)
    # "close" = exactly one condition still unmet → the NPC may hint.
    return "hint" if conds.count(False) == 1 else "hide"


def build_context(
    speaker_id: str | None,
    fragments: list[Frag],
    state: State,
    newly_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble what the LLM is allowed to know this turn for `speaker_id`.

    SECURITY: `reveal` is the ONLY channel that carries fragment content. `hint`
    carries the secret *title* (a topic label the author wrote knowing it may
    surface as a tease), never the fragment body. `hide` carries nothing.

    `new_reveal` is the subset of reveal unlocked THIS turn — the NPC should voice
    these as the step forward, rather than re-dumping everything already known.
    """
    newly = set(newly_ids or [])
    reveal: list[dict[str, str]] = []
    new_reveal: list[dict[str, str]] = []
    hint_titles: set[str] = set()
    has_hidden = False

    for f in fragments:
        if not _speaker_knows(f, speaker_id):
            continue
        guard = classify_guard(f, state)
        if guard == "reveal":
            item = {"secret_title": f.get("secret_title", ""), "content": f.get("content", "")}
            reveal.append(item)
            if f.get("id") in newly:
                new_reveal.append(item)
        elif guard == "hint":
            hint_titles.add(f.get("secret_title", ""))
        else:
            has_hidden = True

    return {
        "reveal": reveal,             # all unlocked fragment bodies the NPC may use
        "new_reveal": new_reveal,     # unlocked THIS turn — voice these as the step
        "hint_topics": sorted(t for t in hint_titles if t),  # topics to tease only
        "has_hidden": has_hidden,     # if true, NPC should deflect probes naturally
    }
