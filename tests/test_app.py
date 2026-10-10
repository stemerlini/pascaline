import pytest

from pascaline import store
from pascaline.app import Pascaline


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(store, "HISTORY", tmp_path / "history.txt")
    monkeypatch.setattr(store, "SHEETS", tmp_path / "sheets")
    monkeypatch.setattr(store, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(store, "EXPORTS", tmp_path / "exports")
    return tmp_path


async def type_line(app, pilot, line):
    app.input.value = line
    await pilot.press("enter")
    await app.workers.wait_for_complete()
    await pilot.pause()


async def test_evaluate_history_and_restore(data):
    app = Pascaline()
    async with app.run_test() as pilot:
        await type_line(app, pilot, "a = 2")
        await type_line(app, pilot, "a^10")
        assert [c.result.text for c in app.cells] == ["a = 2", "1024"]
        await pilot.press("up")
        assert app.input.value == "a^10"
        await pilot.press("up", "down", "down")
        assert app.input.value == ""
    assert (data / "history.txt").read_text() == "a = 2\na^10\n"

    app = Pascaline()  # the sheet comes back, variables included
    async with app.run_test() as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert [c.result.text for c in app.cells] == ["a = 2", "1024"]
        await type_line(app, pilot, "a + 1")
        assert app.cells[-1].result.text == "3"


async def test_edit_reruns_dependants():
    app = Pascaline()
    async with app.run_test() as pilot:
        await type_line(app, pilot, "a = 2")
        await type_line(app, pilot, "a^2")
        await pilot.press("ctrl+up", "up", "enter")
        assert app.input.value == "a = 2"
        await type_line(app, pilot, "a = 5")
        assert [c.result.text for c in app.cells] == ["a = 5", "25"]


async def test_delete_and_new_sheet():
    app = Pascaline()
    async with app.run_test() as pilot:
        for line in ("1+1", "2+2", "3+3"):
            await type_line(app, pilot, line)
        await pilot.press("ctrl+up", "up", "d")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert [c.src for c in app.cells] == ["1+1", "3+3"]
        assert [c.n for c in app.cells] == [1, 2]
        await pilot.press("escape", "ctrl+l")
        await pilot.pause()
        assert app.cells == []


async def test_live_preview():
    app = Pascaline()
    async with app.run_test() as pilot:
        app.input.value = "1/4"
        await pilot.pause(0.2)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "0.25" in str(app.query_one("#preview").render())


async def test_toggle_degrees_and_escape_quits():
    app = Pascaline()
    async with app.run_test() as pilot:
        await type_line(app, pilot, "sin(90)")
        await pilot.press("ctrl+d")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.cells[0].result.text == "1"
        await pilot.press("escape")
    assert app.return_code == 0


async def test_history_search():
    app = Pascaline()
    async with app.run_test() as pilot:
        await type_line(app, pilot, "2^8")
        await type_line(app, pilot, "sqrt(16)")
        await pilot.press("ctrl+r")
        await pilot.press(*"sq", "enter")
        await pilot.pause()
        assert app.input.value == "sqrt(16)"


async def test_brackets_close_themselves():
    app = Pascaline()
    async with app.run_test() as pilot:
        await pilot.press("s", "q", "r", "t", "(")
        assert (app.input.value, app.input.cursor_position) == ("sqrt()", 5)
        await pilot.press("2", ")")
        assert (app.input.value, app.input.cursor_position) == ("sqrt(2)", 7)
        await pilot.press("left", "backspace", "backspace")  # empty pair goes as one
        assert app.input.value == "sqrt"
        app.input.value = ""
        await pilot.press("(", "backspace")
        assert app.input.value == ""


async def test_completion_menu():
    app = Pascaline()
    async with app.run_test() as pilot:
        await pilot.press("s", "q")
        await pilot.pause()
        assert app.menu.display and app.menu.current.name == "sqrt"
        await pilot.press("tab")
        assert (app.input.value, app.input.cursor_position) == ("sqrt()", 5)
        assert not app.menu.display
        await pilot.press("1", "6", "right", "+", "c", "o")
        await pilot.pause()
        assert app.menu.current.name == "cos"
        await pilot.press("down")  # cosh, then ⏎ picks it instead of evaluating
        await pilot.press("enter")
        assert app.input.value == "sqrt(16)+cosh()"
        assert app.cells == []


async def test_enter_evaluates_while_menu_open():
    app = Pascaline()
    async with app.run_test() as pilot:
        await type_line(app, pilot, "ab = 4")
        await pilot.press("a", "b")
        await pilot.pause()
        assert app.menu.display and app.menu.current.name == "ab"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.cells[-1].result.text == "4"
        assert not app.menu.display


async def test_clear_view_keeps_variables(data):
    app = Pascaline()
    async with app.run_test() as pilot:
        await type_line(app, pilot, "a = 6")
        await type_line(app, pilot, "plot(sin x)")
        assert app.graph.plot is not None
        await pilot.press("ctrl+l")
        await pilot.pause()
        assert app.cells == [] and app.graph.plot is None
        await type_line(app, pilot, "a * 7")
        assert [c.n for c in app.cells] == [3]
        assert app.cells[0].result.text == "42"

    app = Pascaline()  # cleared cells stay cleared, their variables still exist
    async with app.run_test() as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert [c.src for c in app.cells] == ["a * 7"]
        await type_line(app, pilot, "a")
        assert app.cells[-1].result.text == "6"
        await pilot.press("ctrl+n")
        await pilot.pause()
        await type_line(app, pilot, "a")
        assert app.cells[-1].result.text == "a"


async def test_typed_clear_command():
    app = Pascaline()
    async with app.run_test() as pilot:
        await type_line(app, pilot, "1+1")
        await type_line(app, pilot, "clear")
        assert app.cells == []


async def test_graph_panel_is_square():
    app = Pascaline()
    async with app.run_test(size=(180, 42)) as pilot:
        await type_line(app, pilot, "plot(x^2, -2, 2)")
        assert app.graph.display and app.graph.plot is not None
        g = app.graph
        rows = 42 - 1 - 2 - g.TITLE_ROWS - g.FOOT_ROWS
        assert g.outer_size.width == 9 + round(rows * 2.0) + 4
        assert "sketched in the graph panel" in app.cells[0].render().plain
    app = Pascaline()
    async with app.run_test(size=(60, 30)) as pilot:  # too narrow: plots go inline
        await type_line(app, pilot, "plot(x^2, -2, 2)")
        assert not app.graph.display
        assert "⠀" in app.cells[0].render().plain or "━" in app.cells[0].render().plain


async def test_escape_stops_a_slow_cell():
    app = Pascaline()
    async with app.run_test() as pilot:
        await type_line(app, pilot, "a = 3")
        app.input.value = "nextprime(10^4000)"
        await pilot.press("enter")
        await pilot.pause(0.6)
        assert app.kernel.busy
        await pilot.press("escape")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.input.value == "nextprime(10^4000)"  # given back to edit
        assert [c.src for c in app.cells] == ["a = 3"]
        app.input.value = ""
        await type_line(app, pilot, "a * 2")  # the sheet was rerun: a is back
        assert app.cells[-1].result.text == "6"


async def test_sheets(data):
    app = Pascaline()
    async with app.run_test() as pilot:
        await type_line(app, pilot, "a = 1")
        await type_line(app, pilot, ":sheet physics")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.sheet_name == "physics" and app.cells == []
        await type_line(app, pilot, "a")
        assert app.cells[-1].result.text == "a"  # sheets don't share variables
        await type_line(app, pilot, ":sheet main")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert [c.src for c in app.cells] == ["a = 1"]
        await type_line(app, pilot, ":rename work")
        assert app.sheet_name == "work"
    assert sorted(p.stem for p in (data / "sheets").glob("*.json")) == ["physics", "work"]
    app = Pascaline()  # reopens on the last sheet
    async with app.run_test() as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.sheet_name == "work" and [c.src for c in app.cells] == ["a = 1"]


async def test_sheet_picker_creates(data):
    app = Pascaline()
    async with app.run_test() as pilot:
        await pilot.press("ctrl+o")
        await pilot.press(*"lab", "enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.sheet_name == "lab"


async def test_export(data):
    import json

    app = Pascaline()
    async with app.run_test() as pilot:
        for line in ("a = 3/4", "x^2 = 2", "plot(sin x)"):
            await type_line(app, pilot, line)
        await type_line(app, pilot, f":export md {data / 'out.md'}")
        await type_line(app, pilot, f":export ipynb {data / 'out'}")
    md = (data / "out.md").read_text()
    assert "**[1]** `a = 3/4`" in md and r"\sqrt{2}" in md
    nb = json.loads((data / "out.ipynb").read_text())
    assert nb["nbformat"] == 4 and any('a = _1 = calc("3/4")' in "".join(c["source"]) for c in nb["cells"])


async def test_theme_follows_omarchy(tmp_path, monkeypatch):
    from pascaline import app as app_module

    colors = tmp_path / "colors.toml"
    colors.write_text('background = "#000000"\nforeground = "#ffffff"\nblue = "#0000ff"\n')
    monkeypatch.setattr(app_module, "COLORS", colors)
    monkeypatch.setattr("pascaline.theme.COLORS", colors)
    app = Pascaline()
    async with app.run_test() as pilot:
        first = app.theme
        assert first.startswith("omarchy")
        colors.write_text('background = "#ffffff"\nforeground = "#000000"\nblue = "#ff0000"\n')
        app.apply_omarchy_theme()
        await pilot.pause()
        assert app.theme != first and app.current_theme.background == "#ffffff"
