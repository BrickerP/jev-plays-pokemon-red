# jev-plays-pokemon-red

[![CI](https://github.com/BrickerP/jev-plays-pokemon-red/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/BrickerP/jev-plays-pokemon-red/actions/workflows/ci.yml)

Pokemon Red played by [Jev](https://typesafe.ai), a model that only outputs probabilities.

Code reads the Game Boy's RAM into a typed snapshot, works out which actions are legal
right now, and hands the model that menu. Jev returns a probability for each option, and
code presses the buttons. The bars in the overlay are those probabilities.

> Copy of [valentynkit/jev-plays-pokemon-red](https://github.com/valentynkit/jev-plays-pokemon-red)
> (MIT, © 2026 Valentyn Kit) with the setup simplified and four real-cartridge stalls
> fixed. See [What this copy changes](#what-this-copy-changes). The clip below is the
> original author's recording on his own cartridge.

![the overlay over a live rival battle](demo/overlay.gif)

## What you need

- Python 3.12 or 3.13, and [uv](https://docs.astral.sh/uv/)
- A TypeSafe API key, the only secret this project uses
- Your own legally obtained Pokemon Red dump. No game data is in this repo and none
  will be added. `.gb` and `.gbc` both work; PyBoy reads the header, not the extension.

## Where the API key goes

```sh
cp .env.example .env     # then open .env and paste the key into TYPESAFE_API_KEY=
```

`.env` is gitignored and loaded automatically. A real environment variable wins over the
file, so `export TYPESAFE_API_KEY=...` also works and is what CI should do.

The free tier answers about five calls per rate-limit window. When it runs out the agent
falls back to its own code default and the overlay prints
`NO ANSWER: RATE LIMITED, CODE DEFAULT` over the bars. The run continues either way: Jev
only ever makes this agent pickier, never looser.

## Quick start

```sh
uv sync
cp .env.example .env                                  # paste your key
export POKEMON_ROM=/path/to/your/red.gb               # or pass --rom every time
```

**Watch a battle.** Two commands, and only the second one spends any credit:

```sh
uv run python fixtures/make_battle_state.py red-battle.state
uv run jpp play --rom "$POKEMON_ROM" --state red-battle.state --overlay --linger 3
```

The first drives the whole opening headless with no key and no network: out of the
bedroom, across Pallet Town, Charmander from Oak, nickname declined, out of the lab, and
it saves the frame the rival battle menu is ready. Well under a minute. The second opens
the window already in that battle, so the bars are there from the first turn. `--linger 3`
holds each answer for three seconds so you can read it.

**Watch the whole run instead**, from Red's bedroom:

```sh
uv run python fixtures/make_state.py red-bedroom.state
uv run jpp play --rom "$POKEMON_ROM" --state red-bedroom.state --overlay
```

Expect a quiet start: from the bedroom to the lab, code walks and Jev is asked nothing,
so the panel shows the live map instead of bars. Both save states are gitignored.

**No key?** Add `--no-jev` to either play command. The game still plays, from code
defaults only, and loses the rival battle.

**No ROM?** Replay the recorded run that ships with the repo:

```sh
uv run jpp overlay --replay fixtures/runs/sample.jsonl
```

## Controls

The overlay owns the window, so it owns the keyboard too.

| Key | Action |
|---|---|
| `Tab` | Take the controller, or give it back |
| Arrows or WASD | D-pad |
| `Z` or `J` | A |
| `X`, `K` or Backspace | B |
| `Enter` | Start |
| `Esc` or `Q` | Quit |

If nothing moves while you hold the pad, a text box is waiting: press `Z`. The game masks
the d-pad during scripted dialogue, and that is the game doing it, not the agent.

## How it works

```
PyBoy --ram bytes--> decode.py --> GameState --> goals.py (active goal)
                                       |
                                       +-> route.py (waypoints + local dodge)
                                       +-> facts.py (HP fractions, type chart, PP)
                                       +-> screen.py (what is drawn, for menus)
                                       +-> options.py (legal actions + intent text)
                                                |
                                   situation classifier
                                   |- routine  --> code presses buttons
                                   +- branch   --> policy.py --> Jev
                                                        |
                                                 overlay.py + runs/*.jsonl
```

Code owns the goal stack, the route, and every piece of arithmetic. Jev is asked only
where the game actually branches, and only ever to pick from options code already proved
legal, so it cannot name a button that does not exist. Every failure path falls back to
the no-Jev behaviour.

## What this copy changes

All four of these only show up on a real cartridge, which is why the upstream test suite
(synthetic RAM, no ROM) is green without them:

- **The naming screen was never recognised.** Its fingerprint pinned `wTopMenuItemY/X`,
  which are the cursor's own row and column, not the panel's origin: read off a cartridge
  the X goes 1, 3, then 15 as the cursor walks the grid. The agent sat on the keyboard
  typing `AAAAAA` and never submitted.
- **START was swallowed while a modal menu was up.** Oak's speech leaves `wJoyIgnore`
  masking START and the d-pad and nothing clears it, so the submit never landed. The
  overlay already did this clear for a human taking the pad; the agent needs it too.
- **Translated cartridges could not get past the two lab prompts.** `yes_no_prompt` reads
  the words YES and NO off the tilemap, which a translated ROM does not draw, so the
  agent answered every prompt with a blind A: right for the starter, wrong for the
  nickname, and into the keyboard. `screen.two_item_choice` now recognises a two-option
  menu structurally (`wMaxMenuItem` 1, A and B watched), and when the question is not
  readable code answers it rather than asking Jev to judge text it cannot see. An
  English ROM still takes the readable path and still goes to Jev.
- **Winning the rival battle stalled the run.** `reach_viridian` had no leg for Oak's lab,
  and the rival intercepts at the door, so the goal flipped while the player was still
  inside, `waypoint_for` returned `None`, and the loop pressed A forever. The lab leg is
  back, and a mat on the map's bottom row is now left by walking south, because a battle
  clears the heading the old code pushed through with.

Setup, not behaviour: `pillow` is declared (the overlay needs `emu.screen`, PyBoy needs
Pillow for it), `.env` is actually read, and `fixtures/make_battle_state.py` is new.

The author's own measurements, the calibration discussion, and the design notes live
upstream and are not reproduced here.

## Development

```sh
uv run pytest -q                       # 104 passed, 6 skipped. Offline, no key, no ROM.
uv run python fixtures/make_ram.py     # regenerate the synthetic RAM fixtures
uv run jpp probe --rom "$POKEMON_ROM"  # walk by hand, watch the decoded state
uv run jpp state --ram fixtures/ram_battle.bin   # the exact request body for a branch
uv run measure runs/run.jsonl          # Brier, decisions/sec and $/hour for a run
```

GitHub Actions runs that same pytest command on Python 3.12 and 3.13. It does not set `POKEMON_ROM` or `TYPESAFE_API_KEY`, so the ROM smoke tests stay skipped.

The three ROM tests skip unless you point them at a cartridge:

```sh
POKEMON_ROM=/path/to/red.gb uv run pytest tests/test_smoke_rom.py -q
```

## Known limits

- One turn of lookahead. No planning, no team building.
- v0.1 targets Viridian City on a hand-written route. Route 1 walks into the ledge at
  `(10, 28)` and stops: one waypoint per map cannot express a way around it.
- A translated ROM gets through the two prompts on this route because code answers them.
  Anything later that needs the text read is still English-only.
- Without a key the code default loses the rival battle, so nothing downstream of it runs.
- A full playthrough needs paid credits; the free tier is five calls a window.

## License

MIT, see [LICENSE](LICENSE). Original work © 2026
[Valentyn Kit](https://github.com/valentynkit); this copy keeps that notice, as the
licence requires.
