"""Reading what is drawn, because every "is a menu up" byte lies on a cartridge."""

from jpp import screen, symbols as S

CODES = {" ": 0x7F, "?": 0xE6, ",": 0xF4}


def _write(mem, row, col, text):
    for i, ch in enumerate(text):
        code = CODES.get(ch)
        if code is None:
            code = 0x80 + ord(ch) - ord("A") if ch.isupper() else 0xA0 + ord(ch) - ord("a")
        mem[S.TILE_MAP + row * screen.WIDTH + col + i] = code


def _blank():
    mem = bytearray(0x10000)
    for i in range(screen.WIDTH * screen.HEIGHT):
        mem[S.TILE_MAP + i] = 0x7F
    return mem


def test_the_screen_buffer_decodes_to_the_words_on_it():
    mem = _blank()
    _write(mem, 16, 1, "CHARMANDER?")
    assert screen.text_lines(mem)[16].strip() == "CHARMANDER?"


def test_a_yes_no_menu_is_read_off_the_screen_with_its_question():
    mem = _blank()
    _write(mem, 8, 16, "YES")
    _write(mem, 10, 16, "NO")
    _write(mem, 14, 1, "give a nickname to")
    _write(mem, 16, 1, "CHARMANDER?")
    prompt, choices = screen.yes_no_prompt(mem)
    assert choices == ["YES", "NO"]
    assert prompt == "give a nickname to CHARMANDER?"


def test_the_naming_keyboard_is_the_displaynamingscreen_fingerprint():
    """A on this screen types a letter. Start submits; empty name keeps the species."""
    mem = _blank()
    mem[S.MAX_MENU_ITEM] = 7
    mem[S.MENU_WATCHED_KEYS] = 0xFF
    assert screen.naming_keyboard(mem)
    mem[S.MAX_MENU_ITEM] = 3  # leftover from the intro name list
    assert screen.naming_keyboard(mem) is False


def test_the_naming_keyboard_ignores_the_cursor_position():
    """wTopMenuItemY/X are where the cursor is, not where the panel is.

    Read off a cartridge: the X is 1, then 3, then 15 as the cursor walks the keyboard.
    A fingerprint that pinned either one never fired, and the agent typed AAAAAA.
    """
    mem = _blank()
    mem[S.MAX_MENU_ITEM] = 7
    mem[S.MENU_WATCHED_KEYS] = 0xFF
    for y, x in ((3, 1), (4, 1), (4, 15)):
        mem[S.TOP_MENU_ITEM_Y], mem[S.TOP_MENU_ITEM_X] = y, x
        assert screen.naming_keyboard(mem)


def test_yes_inside_ordinary_dialogue_is_not_a_menu():
    """Both words have to be visible, or narration trips the detector."""
    mem = _blank()
    _write(mem, 14, 1, "YES I remember")
    assert screen.yes_no_prompt(mem) is None
