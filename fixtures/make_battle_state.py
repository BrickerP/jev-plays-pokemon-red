"""Save a state on the first turn of the rival battle, so a demo can open in the fight.

`jpp play` spends a minute leaving the house and crossing Pallet Town before anything asks
Jev a question. This drives that opening with Jev switched off, stops on the tick
`classify` would turn into a battle branch, and writes a state to start from.

    POKEMON_ROM=red.gb uv run python fixtures/make_battle_state.py red-battle.state

No key and no network: the code default is enough to walk and to take the starter. The
bedroom state is made first if it is not already there, so this is the only command a
fresh clone needs.

Saved on `battle_ready` and not on `wIsInBattle`: both mon structs are zeroed through the
encounter intro, so a state taken on the flag alone resumes on an empty battle. The
`joy_ignore` half is the same predicate `classify` uses, so the resumed state asks Jev on
its very first tick instead of pressing A at a script that still owns the pad.
"""

import os
import sys
from pathlib import Path

from pyboy import PyBoy

sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_state

from jpp import goals, options, route, symbols as S
from jpp.loop import Driver, battle_ready, classify
from jpp.policy import Policy

BUDGET = 50_000
WALK_STEPS = 300
LAB_DOOR = (5, 11)


def walk_out(driver, emu):
    """Hand-drive the lab exit, the way `make_state.py` hand-drives the intro.

    `route.py` is axis-first with one waypoint per map, which cannot express a way around
    a body: after the starter is handed over the rival stands on the column between the
    player and the door, the straight line is blocked, and `sidesteps` returns nothing
    because stepping aside does not reduce the distance. That is the repo's own v0.1
    limitation. A fixture that only has to *place* the emulator at the battle is allowed
    to walk around him.
    """
    order = ("down", "left", "right", "up")
    for _ in range(WALK_STEPS):
        st = driver.state
        if st.in_battle and battle_ready(st):
            return True
        if st.map_id != S.OAKS_LAB:
            return True
        driver.stuck.clear()  # a body is not a wall; retry every step
        dy = LAB_DOOR[1] - st.y
        dx = LAB_DOOR[0] - st.x
        wanted = []
        if dy:
            wanted.append("down" if dy > 0 else "up")
        if dx:
            wanted.append("right" if dx > 0 else "left")
        free = route.free_directions(driver.collision())
        for direction in [d for d in wanted if d in free] + [
            d for d in order if d in free
        ]:
            before = (st.x, st.y)
            driver.press(direction)
            if (driver.state.x, driver.state.y) != before:
                break
            if driver.state.in_battle or driver.state.map_id != S.OAKS_LAB:
                return True
        else:
            driver.press("a")  # a text box is in the way
    return False


def main():
    rom = os.environ.get("POKEMON_ROM") or "red.gb"
    start = Path(os.environ.get("POKEMON_STATE") or "red-bedroom.state")
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "red-battle.state")
    if not Path(rom).is_file():
        raise SystemExit(f"no ROM at {rom}: set POKEMON_ROM to your own dump")

    emu = PyBoy(rom, window="null")
    emu.set_emulation_speed(0)
    driver = Driver(emu)
    stack = goals.GoalStack()
    policy = Policy(enabled=False)  # code defaults: they walk, they do not win
    try:
        if start.is_file():
            with start.open("rb") as f:
                emu.load_state(f)
        else:
            # one command for a fresh clone: the intro needs the name list handled, which
            # make_state already knows how to do, so borrow it instead of asking for a
            # save state that does not exist yet
            print(f"no {start} yet, driving the intro")
            make_state.play_intro(emu)
            with start.open("wb") as f:
                emu.save_state(f)
            print(f"wrote {start}")
        for i in range(BUDGET):
            driver.tick()
            st = driver.state
            stack.advance(st, driver.latch)
            goal = stack.current
            if goal is None:
                raise SystemExit("the goal stack emptied before a battle")
            if st.in_battle and battle_ready(st):
                if st.joy_ignore & (S.PAD_A | S.PAD_CTRL_PAD):
                    continue  # the menu is up but the intro text still owns the pad
                active, foe = st.battle.active, st.battle.opponent
                print(
                    f"battle at tick {i}: goal={goal.name} kind={st.battle.kind} "
                    f"turn={driver.turn} {active.species} lv{active.level} vs "
                    f"{foe.species} lv{foe.level}"
                )
                with out.open("wb") as f:
                    emu.save_state(f)
                print(f"wrote {out}")
                return
            if goal.name == "win_lab_rival" and st.map_id == S.OAKS_LAB:
                print(f"tick {i}: starter in hand, walking out of the lab by hand")
                if not walk_out(driver, emu):
                    raise SystemExit("could not walk out of the lab")
                continue
            if i % 2000 == 0:
                print(
                    f"tick {i}: {st.map_name} ({st.x},{st.y}) goal={goal.name} "
                    f"party={len(st.party)} battle={st.battle.kind}"
                )
            waypoint = route.waypoint_for(goal, st)
            action, payload = classify(driver, goal, waypoint)
            if action == "wait":
                continue
            if action == "press":
                driver.press(payload)
                continue
            decision = policy.decide(payload)
            for button in options.buttons_for(st, payload, decision.option):
                driver.press(button)
        raise SystemExit(f"no battle inside {BUDGET} ticks")
    finally:
        emu.stop(save=False)


if __name__ == "__main__":
    main()
