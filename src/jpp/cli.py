"""`jpp state | probe | play | overlay`."""

import argparse
import json
import sys
import time
from pathlib import Path

from . import goals, options, policy
from .decode import decode

RUNS = Path("runs")


def _goal(name, state, latch=None):
    if name:
        return next(g for g in goals.GOALS if g.name == name)
    stack = goals.GoalStack()
    stack.advance(state, latch or _EmptyLatch())
    return stack.current or goals.GOALS[-1]


class _EmptyLatch:
    result = None
    WIN = 0x00


def _file(path: str) -> Path:
    """argparse-level existence check, so a typo is one line and not a traceback."""
    where = Path(path).expanduser()
    if not where.is_file():
        raise argparse.ArgumentTypeError(f"no such file: {where}")
    return where


def _pyboy(rom: Path, window: bool, unthrottled: bool):
    """Two separate switches. The overlay wants a frame but not a second window: pygame
    and pyboy ship different SDL2 builds, and letting both open one crashes the process.
    """
    from pyboy import PyBoy

    emu = PyBoy(str(rom), window="SDL2" if window else "null")
    if unthrottled:
        emu.set_emulation_speed(0)  # the decisions/sec number is taken here
    return emu


def cmd_state(args):
    """Build the exact request body a branch would send, from a RAM image."""
    mem = args.ram.read_bytes()
    state = decode(mem)
    goal = _goal(args.goal, state)
    if state.in_battle:
        branch = options.battle_branch(
            state, goal, items=options.bag(mem), turn=args.turn
        )
    else:
        waypoint = (state.x + 2, state.y + 3)
        branch = options.tie_branch(state, goal, waypoint, ["left", "right"])
    print(
        json.dumps(
            {
                "model": policy.MODEL,
                "state": branch.state,
                "questions": policy.questions_for(branch),
            },
            indent=1,
        )
    )


def cmd_probe(args):
    from .loop import probe

    emu = _pyboy(args.rom, window=True, unthrottled=False)
    try:
        probe(emu, ticks=args.ticks)
    finally:
        emu.stop(save=False)


def cmd_play(args):
    from .loop import play

    RUNS.mkdir(exist_ok=True)
    log = Path(args.out) if args.out else RUNS / "run.jsonl"
    emu = _pyboy(
        args.rom,
        window=not (args.headless or args.overlay or args.frames),
        unthrottled=args.headless and not args.overlay,
    )
    if args.state:
        with open(args.state, "rb") as f:
            emu.load_state(f)
    client = policy.JevClient(replay_dir=args.replay)
    on_decision, on_frame, human = None, None, None
    if args.frames:
        on_decision, on_frame = _frame_capture(Path(args.frames), args.every)
    elif args.overlay:
        on_decision, on_frame, human = _overlay_watch(
            emu, fps=args.overlay_fps, linger_s=args.linger
        )
    try:
        records = play(
            emu,
            policy.Policy(client, enabled=not args.no_jev),
            max_decisions=args.max_decisions,
            log_path=log,
            on_decision=on_decision,
            on_frame=on_frame,
            human=human,
        )
    finally:
        emu.stop(save=False)
    print(f"{len(records)} decisions -> {log}")


def _overlay_watch(emu, fps=60, linger_s=0.0):
    """One pygame window: the Game Boy frame on top, live debug / Jev bars below.

    PyBoy cannot open its own SDL window at the same time. Decode every frame so the
    panel is not black while the script is walking. The headline number is still call
    latency, never this clock.
    """
    from . import screen, symbols as S
    from .decode import decode
    from .overlay import Overlay

    overlay = Overlay("jev plays pokemon", live=True, fps=fps)
    labelled: list[dict] = []

    def _paint():
        overlay.set_live(decode(emu.memory))
        if not overlay.draw(emu.screen.ndarray):
            raise SystemExit("overlay closed")

    def on_decision(record):
        from . import measure

        labelled.append(record)
        overlay.feed(record, labelled=measure.pairs(labelled))
        if linger_s <= 0:
            _paint()
            return
        hold_until = time.monotonic() + linger_s
        while time.monotonic() < hold_until:
            _paint()

    def on_frame(_emu):
        overlay.forced = screen.naming_keyboard(emu.memory)
        if overlay.taking_over and overlay.forced:
            # leftover mask from Oak's speech ignores Start and the d-pad
            emu.memory[S.JOY_IGNORE] = 0
        _paint()

    return on_decision, on_frame, overlay


def _frame_capture(out: Path, every: int):
    """Draw the overlay over the live game and dump a PNG per captured frame.

    Every emulator frame passes through, so the game moves at its own speed in the clip
    rather than at the agent's decision rate; `every` thins 60 fps down to the video rate.
    """
    import pygame

    from . import measure
    from .overlay import Overlay

    out.mkdir(parents=True, exist_ok=True)
    overlay = Overlay("jev plays pokemon", live=True)
    seen: list[dict] = []
    count = [0, 0]

    def on_decision(record):
        seen.append(record)
        overlay.feed(record, labelled=measure.pairs(seen))

    def on_frame(emu):
        count[0] += 1
        if count[0] % every:
            return
        overlay.draw(emu.screen.ndarray)
        pygame.image.save(overlay.screen, str(out / f"f{count[1]:05d}.png"))
        count[1] += 1

    return on_decision, on_frame


def cmd_overlay(args):
    from .overlay import render_frames, run_replay

    rate = 1.5 if args.demo and args.rate == 2.0 else args.rate
    if args.frames:
        n = render_frames(
            args.replay,
            Path(args.frames),
            fps=args.fps,
            rate=rate,
            seconds=args.seconds,
            skip=args.skip,
            include_stand_ins=args.include_stand_ins,
        )
        print(f"{n} frames -> {args.frames}")
        return
    run_replay(args.replay, rate=rate, include_stand_ins=args.include_stand_ins)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="jpp")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("state", help="print the Jev request for a RAM image")
    p.add_argument("--ram", required=True, type=_file)
    p.add_argument("--goal", choices=[g.name for g in goals.GOALS])
    p.add_argument("--turn", type=int, default=None)
    p.set_defaults(func=cmd_state)

    p = sub.add_parser(
        "probe", help="walk the route by hand and watch the decoded state"
    )
    p.add_argument("--rom", required=True, type=_file)
    p.add_argument("--ticks", type=int, default=100_000)
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("play", help="run the agent")
    p.add_argument("--rom", required=True, type=_file)
    p.add_argument("--headless", action="store_true")
    p.add_argument(
        "--overlay",
        action="store_true",
        help="one 1080x1350 window: game on top, live debug / Jev bars below",
    )
    p.add_argument("--max-decisions", type=int, default=50)
    p.add_argument("--out")
    p.add_argument(
        "--replay", help="answer from recorded fixtures instead of the network"
    )
    p.add_argument(
        "--no-jev", action="store_true", help="code defaults only, for a baseline"
    )
    p.add_argument("--state", help="save state to start from, eg red-bedroom.state")
    p.add_argument("--frames", help="dump the overlay over the live game here, as PNGs")
    p.add_argument("--every", type=int, default=2, help="capture 1 frame in N (60/N fps)")
    p.add_argument(
        "--overlay-fps",
        type=int,
        default=60,
        help="pygame cap while --overlay is on; 60 is cartridge speed",
    )
    p.add_argument(
        "--linger",
        type=float,
        default=0.0,
        help="seconds to hold the bars after each Jev answer",
    )
    p.set_defaults(func=cmd_play)

    p = sub.add_parser(
        "overlay", help="the 1080x1350 window, live or replaying a run file"
    )
    p.add_argument("--replay", required=True, type=_file)
    p.add_argument("--rate", type=float, default=2.0, help="decisions per second")
    p.add_argument(
        "--demo", action="store_true", help="1.5 decisions/sec, watchable on camera"
    )
    p.add_argument("--frames", help="dump one PNG per frame here instead of a window")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--seconds", type=float, default=None)
    p.add_argument("--skip", type=int, default=0, help="start at this decision")
    p.add_argument(
        "--include-stand-ins",
        action="store_true",
        help="also draw rows tagged source=fake; never use this for a clip",
    )
    p.set_defaults(func=cmd_overlay)

    args = parser.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
