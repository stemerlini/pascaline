"""Pascaline: a notebook-style scientific calculator for the terminal."""

from __future__ import annotations

import re
import shutil
import struct
import subprocess
import sys
import threading
from pathlib import Path

import sympy as sp
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from . import __version__, export, store
from .completions import Item, complete
from .engine import FUNCTIONS, Plot, Result
from .kernel import Interrupted, Kernel, Reply
from .plot import GUTTER
from .plot import render as render_plot
from .theme import COLORS, omarchy_theme

PREVIEW_TIMEOUT = 3.0  # seconds a live preview may take before it gives up

TOKEN_RE = re.compile(r"(?P<num>\d+\.?\d*(?:e[+-]?\d+)?)|(?P<name>[A-Za-z_]\w*)|(?P<op>[-+*/^!=<>%])|(?P<other>.)")

HELP = """\
[b]pascaline[/b] — a pocket notebook calculator

[b]Typing[/b]
  2x, 3(x+1), sin x     implicit multiplication / application
  x^2  5!  √2  π  e  i  powers, factorial, constants
  a = 3/4               store a variable
  f(x) = x^2 + 1        define a function, then f(3)
  x^2 - 4 = 0           solve (comma-separate a system: x+y=3, x-y=1)
  cos(x) = x            falls back to numeric roots
  ans  _3               last result, result of cell 3
  [[1,2],[3,4]]^-1      matrices; det(A), inv(A), tr(A)
  diff(f(x), x)  integrate(x^2, (x, 0, 1))  limit(sin(x)/x, x, 0)
  series(e^x, x, 0, 5)  factor  expand  simplify  nCr  gcd  N(pi, 50)
  plot(sin x, cos x, -pi, pi)   sketch; plot(f, (t, 0, 10))
  5 km/h to m/s  3 km + 200 m  2 kWh to J   units (switch on when you use one)
  c0 g0 G_N h_P hbar k_B N_A q_e m_e m_p eps0 mu0 R_gas   physical constants

[b]Keys[/b]
  ⏎        evaluate (live preview while you type)
  ↑ ↓      input history          ctrl+r  search all history
  tab      accept completion (↑↓ pick, then ⏎ works too)
  ( [ {    close themselves; select text and type ( to wrap it
  ctrl+y   copy last result
  ctrl+↑   select cells: ⏎ edit · d delete · y copy · l copy LaTeX · i insert _n · esc back
  ctrl+l   clear the view (variables stay)   ctrl+n  empty this sheet
  ctrl+o   switch sheet / make a new one     ctrl+d  toggle DEG / RAD
  esc      stop a running calculation, clear input, or quit when empty

[b]Commands[/b]
  clear  :deg  :rad  :digits 20  :vars  :new  :latex  :q
  :sheet NAME  :sheets  :rename NAME  :delete NAME
  :export md [path]   :export ipynb [path]   (default: data/exports/)
"""


class Cell(Static):
    """One evaluated line of the sheet: input, then its result."""

    def __init__(self, n: int, src: str, result: Result, hidden: bool = False):
        super().__init__()
        self.n, self.src, self.result = n, src, result
        self.hidden = hidden
        self.deleted = False
        self.display = not hidden
        self._plot_cache: tuple[int, Text] | None = None

    def hide(self) -> None:
        self.hidden = True
        self.display = False

    def update_cell(self, n: int, src: str, result: Result) -> None:
        self.n, self.src, self.result = n, src, result
        self._plot_cache = None
        self.refresh(layout=True)

    def render(self) -> Text:
        t = self.app.current_theme
        muted = f"{t.foreground} dim" if t.foreground else "dim"
        out = Text(no_wrap=True, overflow="ellipsis")
        out.append(f"{self.n:>3} ", style=muted)
        out.append("› ", style=t.primary)
        out.append_text(highlight(self.src, t))
        out.append("\n")
        r = self.result
        if r.kind == "error":
            out.append(f"    ⚠ {r.text}", style=t.error)
        elif r.kind == "plot" and self.app.graph.display:
            out.append("    ◩ ", style=t.accent)
            out.append("sketched in the graph panel", style=muted)
        elif r.kind == "plot":
            width = (self.content_size.width or self.app.size.width - 4) - 4
            if not self._plot_cache or self._plot_cache[0] != width:
                colors = [c for c in (t.primary, t.secondary, t.success, t.warning, t.accent) if c]
                try:
                    pic = render_plot(r.plot, width, 10, colors, muted)
                except Exception as exc:
                    pic = Text(f"⚠ can't sketch: {exc}", style=t.error)
                self._plot_cache = (width, pic)
            pic = self._plot_cache[1].copy()
            out.append("    ")
            out.append_text(Text("\n    ").join(pic.split("\n")))
        else:
            lead = {"solve": "∴ ", "assign": "→ "}.get(r.kind, "= ")
            lines = r.text.split("\n")
            base = len(lines) // 2 if len(lines) > 1 else 0
            style = t.secondary if r.kind == "assign" else f"bold {t.foreground}"
            for k, line in enumerate(lines):
                out.append("    ")
                out.append(lead if k == base or r.kind == "solve" else "  ", style=muted)
                out.append(line.rstrip(), style=style)
                out.append("\n")
            if r.approx:
                for line in r.approx.split("\n"):
                    out.append("    ≈ ", style=muted)
                    out.append(line.rstrip(), style=t.warning)
                    out.append("\n")
        out.rstrip()
        return out


def highlight(src: str, t) -> Text:
    out = Text()
    for m in TOKEN_RE.finditer(src):
        kind, tok = m.lastgroup, m.group()
        if kind == "num":
            out.append(tok, style=t.warning)
        elif kind == "name":
            nxt = src[m.end() : m.end() + 1]
            out.append(tok, style=t.primary if (nxt == "(" or tok in FUNCTIONS) else t.foreground)
        elif kind == "op":
            out.append(tok, style=t.secondary)
        else:
            out.append(tok)
    return out


def cell_aspect() -> float:
    """Height / width of one terminal cell, from the terminal's pixel size."""
    import fcntl
    import termios

    for stream in (sys.__stdout__, sys.__stderr__, sys.__stdin__):
        try:
            rows, cols, xpx, ypx = struct.unpack("HHHH", fcntl.ioctl(stream.fileno(), termios.TIOCGWINSZ, b"\0" * 8))
        except (OSError, AttributeError, ValueError):
            continue
        if rows and cols and xpx and ypx:
            return (ypx / rows) / (xpx / cols)
    return 2.0


class GraphPanel(Static):
    """The right-hand pane: the latest sketch, drawn in a square."""

    TITLE_ROWS, FOOT_ROWS = 2, 3  # title + gap; x axis, x labels, legend

    def __init__(self, **kw):
        super().__init__(**kw)
        self.plot: Plot | None = None
        self.label = ""
        self.preview: tuple[Plot, str] | None = None
        self.aspect = 2.0

    def show(self, plot: Plot | None, label: str = "") -> None:
        self.plot, self.label, self.preview = plot, label, None
        self.refresh()

    def show_preview(self, preview: tuple[Plot, str] | None) -> None:
        if preview != self.preview:
            self.preview = preview
            self.refresh()

    def square(self, rows: int) -> int:
        """Columns that make `rows` look square on screen."""
        return max(1, round(rows * self.aspect))

    def render(self) -> Text:
        t = self.app.current_theme
        muted = f"{t.foreground} dim"
        plot, label = self.preview or (self.plot, self.label)
        if plot is None:
            hint = Text("\n\n  no sketch yet\n\n", style=muted)
            hint.append("  plot(sin x, cos x, -pi, pi)\n", style=t.accent)
            hint.append("  plot(f, (t, 0, 10))", style=t.accent)
            return hint
        w, h = self.content_size
        rows = max(4, min(h - self.TITLE_ROWS - self.FOOT_ROWS, int((w - GUTTER) / self.aspect)))
        out = Text(no_wrap=True, overflow="ellipsis")
        out.append(label, style=f"bold {t.foreground}")
        if self.preview:
            out.append("  preview", style=f"{t.warning} italic")
        out.append("\n\n")
        colors = [c for c in (t.primary, t.secondary, t.success, t.warning, t.accent) if c]
        try:
            out.append_text(render_plot(plot, GUTTER + self.square(rows), rows, colors, muted))
        except Exception as exc:
            out.append(f"can't sketch: {exc}", style=t.error)
        return out


PAIRS = {"(": ")", "[": "]", "{": "}"}
WORD_BEFORE = re.compile(r"[A-Za-z_]\w*$")


class MathInput(Input):
    """The prompt: history on ↑↓, completion menu, brackets that close themselves."""

    BINDINGS = [
        Binding("up", "arrow(-1)", show=False),
        Binding("down", "arrow(1)", show=False),
        Binding("tab", "app.accept_completion", show=False),
    ]

    def action_arrow(self, step: int) -> None:
        self.app.arrow(step)

    def action_submit(self):
        if self.app.menu_navigated():
            self.app.action_accept_completion()
            return None
        return super().action_submit()

    async def _on_key(self, event) -> None:
        ch = event.character if event.is_printable else None
        here = self.cursor_position
        nxt = self.value[here : here + 1]
        if ch in PAIRS:
            event.stop()
            event.prevent_default()
            start, end = sorted(self.selection)
            if start != end:  # wrap the selection
                inner = self.value[start:end]
                self.replace(ch + inner + PAIRS[ch], start, end)
                self.cursor_position = end + 2
            elif nxt == "" or nxt in " )]},":
                self.insert_text_at_cursor(ch + PAIRS[ch])
                self.cursor_position -= 1
            else:
                self.insert_text_at_cursor(ch)
            return
        if ch and ch in ")]}" and nxt == ch and self.selection.is_empty:
            event.stop()
            event.prevent_default()
            self.cursor_position += 1  # step over the bracket that is already there
            return
        await super()._on_key(event)

    def action_delete_left(self) -> None:
        here = self.cursor_position
        prev, nxt = self.value[here - 1 : here], self.value[here : here + 1]
        if self.selection.is_empty and prev in PAIRS and nxt == PAIRS[prev]:
            self.delete(here - 1, here + 1)
        else:
            super().action_delete_left()


class CompletionMenu(OptionList, can_focus=False):
    """Matches for the word under the cursor, shown just above the prompt."""

    def show(self, items: list[Item]) -> None:
        self.items = items
        self.navigated = False
        t = self.app.current_theme
        width = max(len(i.name + i.signature) for i in items) + 3
        self.clear_options()
        for item in items:
            line = Text(item.name, style=f"bold {t.primary}" if item.kind != "var" else f"bold {t.secondary}")
            line.append(item.signature, style=t.foreground)
            line.append(" " * max(2, width - len(item.name + item.signature)))
            line.append(item.help, style=f"{t.foreground} dim")
            self.add_option(Option(line))
        self.highlighted = 0
        self.display = True

    def hide(self) -> None:
        self.display = False
        self.navigated = False

    @property
    def current(self) -> Item | None:
        if not self.display or self.highlighted is None:
            return None
        return self.items[self.highlighted]


class Sheet(VerticalScroll, can_focus=True):
    BINDINGS = [
        Binding("up,k", "move(-1)", show=False),
        Binding("down,j", "move(1)", show=False),
        Binding("home,g", "move(-9999)", show=False),
        Binding("end,G", "move(9999)", show=False),
        Binding("enter,e", "app.edit_cell", show=False),
        Binding("d,delete", "app.delete_cell", show=False),
        Binding("y", "app.copy_cell", show=False),
        Binding("l", "app.copy_cell_latex", show=False),
        Binding("i", "app.insert_ref", show=False),
        Binding("escape", "app.leave_cells", show=False),
    ]

    def action_move(self, step: int) -> None:
        self.app.move_selection(step)


class PickerScreen(ModalScreen[str | None]):
    """A filterable list: history search, sheet switcher."""

    BINDINGS = [Binding("escape", "dismiss(None)", show=False)]

    def __init__(self, items: list[tuple[str, str]], placeholder: str, create: str | None = None):
        super().__init__()
        self.items = items  # (value, label)
        self.placeholder = placeholder
        self.create = create  # e.g. "new sheet": typing a new name offers to create it

    def compose(self) -> ComposeResult:
        with Vertical(id="history-box"):
            yield Input(placeholder=self.placeholder, id="history-filter")
            yield OptionList(id="history-list")

    def on_mount(self) -> None:
        self.fill("")

    def fill(self, query: str) -> None:
        q = query.strip()
        ol = self.query_one(OptionList)
        ol.clear_options()
        options = [Option(label, id=f"v:{value}") for value, label in self.items if q.lower() in label.lower()]
        if self.create and q and all(value != q for value, _ in self.items):
            options.insert(0, Option(f"+ {self.create} “{q}”", id=f"v:{q}"))
        ol.add_options(options[:500])
        ol.highlighted = 0 if ol.option_count else None

    @on(Input.Changed, "#history-filter")
    def filter(self, event: Input.Changed) -> None:
        self.fill(event.value)

    def on_key(self, event) -> None:
        ol = self.query_one(OptionList)
        if event.key in ("up", "down"):
            ol.action_cursor_up() if event.key == "up" else ol.action_cursor_down()
            event.stop()

    @on(Input.Submitted, "#history-filter")
    def pick_from_filter(self) -> None:
        ol = self.query_one(OptionList)
        if ol.highlighted is not None:
            self.dismiss(ol.get_option_at_index(ol.highlighted).id[2:])

    @on(OptionList.OptionSelected)
    def pick(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id[2:])


def history_items(history: list[str]) -> list[tuple[str, str]]:
    seen, out = set(), []
    for line in reversed(history):
        if line not in seen:
            seen.add(line)
            out.append((line, line))
    return out


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,q,question_mark,f1", "dismiss", show=False)]

    def compose(self) -> ComposeResult:
        yield Static(HELP, id="help-box")


class Pascaline(App):
    CSS_PATH = "pascaline.tcss"
    TITLE = "pascaline"
    BINDINGS = [
        Binding("ctrl+q", "quit", show=False, priority=True),
        Binding("escape", "escape", show=False),
        Binding("ctrl+r", "search_history", show=False, priority=True),
        Binding("ctrl+y", "copy_last", show=False, priority=True),
        Binding("ctrl+l", "clear_view", show=False, priority=True),
        Binding("ctrl+n", "new_sheet", show=False, priority=True),
        Binding("ctrl+o", "pick_sheet", show=False, priority=True),
        Binding("ctrl+d", "toggle_angle", show=False, priority=True),
        Binding("ctrl+up", "enter_cells", show=False, priority=True),
        Binding("f1", "help", show=False),
    ]

    def __init__(self):
        super().__init__()
        self.sheet_name = store.current_sheet()
        sheet = store.load_sheet(self.sheet_name)
        self.digits = int(sheet.get("digits", 12))
        self.degrees = bool(sheet.get("degrees", False))
        self.saved_cells = store.sheet_cells(sheet)
        self.kernel = Kernel(self.digits, self.degrees)  # runs the sheet
        self.preview_kernel = Kernel(self.digits, self.degrees)  # runs live previews, may be killed any time
        self._preview_lock = threading.Lock()
        self._preview_state: tuple[list[str], int, bool] | None = ([], self.digits, self.degrees)
        self.names: dict[str, tuple[str, str]] = {}  # your variables, as the kernel last reported them
        self._pending = 0  # cells submitted but not back yet
        self._theme_stamp = ""
        self.history = store.load_history()
        self.hist_pos: int | None = None
        self.draft = ""
        self.editing: Cell | None = None
        self.selected: Cell | None = None
        self._preview_src: str | None = None
        self._menu_suppressed = False

    # -- layout ------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            with Vertical(id="left"):
                with Sheet(id="sheet"):
                    yield Static(
                        f"pascaline {__version__} · type math, ⏎ to evaluate · ? for help", id="welcome"
                    )
                with Vertical(id="bottom"):
                    yield CompletionMenu(id="menu")
                    with Horizontal(id="prompt-row"):
                        yield Label("›", id="prompt")
                        yield MathInput(
                            placeholder="2^10 + √2   ·   x^2 - 4 = 0   ·   plot(sin x)",
                            id="input",
                            select_on_focus=False,
                        )
                    yield Static("", id="preview")
            yield GraphPanel(id="graph")
        yield Static("", id="status")

    def on_mount(self) -> None:
        if not self.apply_omarchy_theme():
            self.theme = "tokyo-night"
        self.set_interval(2, self.apply_omarchy_theme)
        self.menu.hide()
        self.graph.aspect = cell_aspect()
        self.layout_panes()
        self.input.focus()
        self.update_status()
        if self.saved_cells:
            self.recompute([c for c, _ in self.saved_cells], [h for _, h in self.saved_cells])

    def apply_omarchy_theme(self) -> bool:
        """Follow the Omarchy theme, also when it changes while the app is open."""
        try:
            stamp = COLORS.read_text()
        except OSError:
            return False
        if stamp == self._theme_stamp:
            return True
        self._theme_stamp = stamp
        name = f"omarchy-{abs(hash(stamp)) % 10**8}"
        theme = omarchy_theme(name)
        if not theme:
            return False
        self.register_theme(theme)
        self.theme = name
        self.refresh_cells()
        return True

    def refresh_cells(self) -> None:
        if not self.is_mounted:
            return
        for cell in self.all_cells:
            cell.refresh()
        self.graph.refresh()

    def on_unmount(self) -> None:
        self.kernel.close()
        self.preview_kernel.close()

    @property
    def input(self) -> MathInput:
        return self.query_one("#input", MathInput)

    @property
    def sheet(self) -> Sheet:
        return self.query_one("#sheet", Sheet)

    @property
    def all_cells(self) -> list[Cell]:
        """Every cell, including the ones cleared from view (they still define variables)."""
        return [c for c in self.query(Cell) if not c.deleted]

    @property
    def cells(self) -> list[Cell]:
        return [c for c in self.all_cells if not c.hidden]

    @property
    def graph(self) -> GraphPanel:
        return self.query_one("#graph", GraphPanel)

    LEFT_MIN = 46  # columns the commands pane always keeps

    def layout_panes(self) -> None:
        """Size the graph pane so its plot area is square; drop it when the window is narrow."""
        width, height = self.size
        g = self.graph
        rows = height - 1 - 2 - g.TITLE_ROWS - g.FOOT_ROWS  # status bar, border
        panel = GUTTER + g.square(rows) + 4  # border + padding
        if width - panel < self.LEFT_MIN:
            panel = width - self.LEFT_MIN
        show = panel >= GUTTER + 24
        if show:
            g.styles.width = panel
        if g.display != show:
            g.display = show
            for cell in self.cells:
                if cell.result.kind == "plot":
                    cell.refresh(layout=True)

    @property
    def menu(self) -> CompletionMenu:
        return self.query_one("#menu", CompletionMenu)

    # -- completion --------------------------------------------------------

    def update_menu(self) -> None:
        if self._menu_suppressed:
            self._menu_suppressed = False
            self.menu.hide()
            return
        before = self.input.value[: self.input.cursor_position]
        m = WORD_BEFORE.search(before)
        word = m.group() if m and not before[: m.start()].endswith(".") else ""
        items = complete(word, self.names) if len(word) >= 2 else []
        if not items or (len(items) == 1 and items[0].name == word):
            self.menu.hide()
        else:
            self.menu.show(items)

    def menu_navigated(self) -> bool:
        return self.menu.display and self.menu.navigated

    def arrow(self, step: int) -> None:
        menu = self.menu
        if menu.display:
            menu.navigated = True
            menu.action_cursor_up() if step < 0 else menu.action_cursor_down()
        else:
            self.step_history(step)

    def action_accept_completion(self) -> None:
        item = self.menu.current
        if not item:
            return
        inp = self.input
        value, here = inp.value, inp.cursor_position
        start = WORD_BEFORE.search(value[:here]).start()
        end = here + re.match(r"\w*", value[here:]).end()
        after = value[end:]
        text = item.name
        cursor = start + len(text)
        if item.callable and item.signature:
            if after.startswith("("):
                cursor += 1
            else:
                text += "()"
                cursor += 1
        self._menu_suppressed = True
        inp.value = value[:start] + text + after
        inp.cursor_position = cursor
        self.menu.hide()

    @on(OptionList.OptionSelected, "#menu")
    def menu_clicked(self, event: OptionList.OptionSelected) -> None:
        self.menu.highlighted = event.option_index
        self.action_accept_completion()
        self.input.focus()

    def update_status(self) -> None:
        mode = "DEG" if self.degrees else "RAD"
        n = len(self.cells)
        left = f" {self.sheet_name} · {mode} · {self.digits} sig · {n} cell{'s' * (n != 1)}"
        if self.kernel.busy:
            left += " · computing (esc stops)"
        if self.editing:
            left += f" · editing [{self.editing.n}]"
        right = "⏎ eval  ^R search  ^↑ cells  ^Y copy  ^L clear  ^O sheets  ? help "
        width = self.size.width or 80
        self.query_one("#status", Static).update(
            Text(left) + Text(" " * max(1, width - len(left) - len(right))) + Text(right)
        )
        self.query_one("#welcome").display = n == 0


    def on_resize(self) -> None:
        self.layout_panes()
        self.update_status()

    # -- evaluating --------------------------------------------------------

    @on(Input.Submitted, "#input")
    def submit(self, event: Input.Submitted) -> None:
        src = event.value.strip()
        if not src:
            return
        store.append_history(src, self.history)
        self.hist_pos = None
        self.input.value = ""
        self.set_preview("")
        self.menu.hide()
        if src in ("?", "help", "clear", "cls") or (src.startswith(":") and src[1:2].isalpha()):
            self.command(src)
            return
        if self.editing:
            target, self.editing = self.editing, None
            self.input.remove_class("-editing")
            srcs = [c.src if c is not target else src for c in self.all_cells]
            self.recompute(srcs)
        else:
            n = len(self.all_cells) + 1 + self._pending
            self._pending += 1
            self.evaluate(src, n)

    @work(thread=True, group="eval")
    def evaluate(self, src: str, n: int) -> None:
        self.call_from_thread(self.computing)
        try:
            reply = self.kernel.call("run", src, n, True)
        except Interrupted as exc:
            self.call_from_thread(self.eval_stopped, src, str(exc))
            return
        self.call_from_thread(self.add_cell, n, src, reply)

    def computing(self) -> None:
        self.set_preview(Text("  ⋯ computing — esc to stop", style=f"{self.current_theme.warning} italic"))
        self.update_status()

    def eval_stopped(self, src: str, why: str) -> None:
        """The kernel was restarted empty: rerun the sheet without the line that was stopped."""
        self._pending = max(0, self._pending - 1)
        self.set_preview("")
        if not self.input.value:
            self.input.value = src
            self.input.cursor_position = len(src)
        self.notify(f"{why}; the sheet is being rerun", severity="warning", timeout=3)
        self.recompute([c.src for c in self.all_cells])

    def add_cell(self, n: int, src: str, reply: Reply) -> None:
        self._pending = max(0, self._pending - 1)
        self.names = reply.names
        result = reply.results[0]
        self.set_preview("")
        if result.kind == "plot":
            self.graph.show(result.plot, f"[{n}] {src}")
        else:
            self.graph.show_preview(None)
        self.sheet.mount(Cell(n, src, result))
        self.sheet.scroll_end(animate=False)
        self.after_change()

    @work(thread=True, group="eval")
    def recompute(self, srcs: list[str], hidden: list[bool] | None = None) -> None:
        """Rerun the whole sheet from scratch, top to bottom, like 'Run all'."""
        self.call_from_thread(self.update_status)
        try:
            self.kernel.configure(self.digits, self.degrees)
            reply = self.kernel.call("run_all", srcs)
        except Interrupted as exc:
            stopped = Result("error", f"not run: {exc}. Edit a cell to rerun the sheet")
            reply = Reply([stopped] * len(srcs))
        self.call_from_thread(self.show_all, srcs, reply, hidden)

    def show_all(self, srcs: list[str], reply: Reply, hidden: list[bool] | None = None) -> None:
        results = reply.results
        self.names = reply.names
        cells = self.all_cells
        for k, (src, res) in enumerate(zip(srcs, results, strict=True)):
            if k < len(cells):
                cells[k].update_cell(k + 1, src, res)
            else:
                self.sheet.mount(Cell(k + 1, src, res, hidden=bool(hidden and hidden[k])))
        for extra in cells[len(srcs) :]:
            extra.remove()
        if self.selected and self.selected not in cells[: len(srcs)]:
            self.selected = None
        if not self.selected:
            self.sheet.scroll_end(animate=False)
        self.call_after_refresh(self.show_latest_plot)
        self.after_change()

    def show_latest_plot(self) -> None:
        for cell in reversed(self.cells):
            if cell.result.kind == "plot":
                self.graph.show(cell.result.plot, f"[{cell.n}] {cell.src}")
                return
        self.graph.show(None)

    def after_change(self) -> None:
        cells = [(c.src, c.hidden) for c in self.all_cells]
        store.save_sheet(self.sheet_name, cells, self.degrees, self.digits)
        self.update_status()

    # -- live preview ------------------------------------------------------

    @on(Input.Changed, "#input")
    def changed(self, event: Input.Changed) -> None:
        self.update_menu()
        src = event.value.strip()
        if not src or src.startswith(":") or src == "?":
            self.set_preview("")
            self.graph.show_preview(None)
            return
        self._preview_src = src
        state = ([c.src for c in self.all_cells], self.digits, self.degrees)
        self.set_timer(0.05, lambda: self.preview(src, state))

    @work(thread=True, group="preview")
    def preview(self, src: str, state: tuple[list[str], int, bool]) -> None:
        with self._preview_lock:
            if src != self._preview_src:
                return  # typing moved on
            k = self.preview_kernel
            try:
                self._sync_preview_kernel(state)
                reply = k.call("run", src, None, False, timeout=PREVIEW_TIMEOUT)
            except Interrupted:
                self._preview_state = None  # restarted empty; resync next time
                self.call_from_thread(self.preview_gave_up, src)
                return
        self.call_from_thread(self.show_preview, src, reply.results[0])

    def _sync_preview_kernel(self, state: tuple[list[str], int, bool]) -> None:
        """Bring the preview kernel to the sheet's state, running only what's new."""
        srcs, digits, degrees = state
        k, have = self.preview_kernel, self._preview_state
        if have and have[1:] == (digits, degrees) and srcs[: len(have[0])] == have[0]:
            for i, s in enumerate(srcs[len(have[0]) :], start=len(have[0]) + 1):
                k.call("run", s, i, True)
        else:
            k.configure(digits, degrees)
            k.call("run_all", srcs)
        self._preview_state = (list(srcs), digits, degrees)

    def preview_gave_up(self, src: str) -> None:
        if src == self.input.value.strip():
            self.set_preview(Text("  … too slow to preview; ⏎ computes it (esc stops)", style="dim italic"))

    def show_preview(self, src: str, res: Result) -> None:
        if src != self.input.value.strip():
            return
        t = self.current_theme
        if res.kind != "plot":
            self.graph.show_preview(None)
        if res.kind == "error":
            self.set_preview(Text(f"  {res.text}", style=f"{t.foreground} dim italic"))
        elif res.kind == "plot":
            self.graph.show_preview((res.plot, src))
            self.set_preview(Text("  ⏎ to keep the sketch", style=t.accent))
        else:
            self.set_preview(Text("  = ", style="dim") + Text(one_line(res), style=t.accent))

    def set_preview(self, content) -> None:
        self.query_one("#preview", Static).update(content)

    # -- input history -----------------------------------------------------

    def step_history(self, step: int) -> None:
        if not self.history:
            return
        if self.hist_pos is None:
            if step > 0:
                return
            self.draft = self.input.value
            self.hist_pos = len(self.history)
        self.hist_pos = max(0, self.hist_pos + step)
        if self.hist_pos >= len(self.history):
            self.hist_pos = None
            self.input.value = self.draft
        else:
            self.input.value = self.history[self.hist_pos]
        self.input.cursor_position = len(self.input.value)

    def action_search_history(self) -> None:
        def chosen(line: str | None) -> None:
            if line:
                self.input.value = line
                self.input.cursor_position = len(line)
            self.input.focus()

        self.push_screen(PickerScreen(history_items(self.history), "search history…"), chosen)

    # -- cell selection ----------------------------------------------------

    def action_enter_cells(self) -> None:
        cells = self.cells
        if not cells:
            return
        self.select(self.selected if self.selected in cells else cells[-1])
        self.sheet.focus()

    def select(self, cell: Cell | None) -> None:
        if self.selected:
            self.selected.remove_class("-selected")
        self.selected = cell
        if cell:
            cell.add_class("-selected")
            cell.scroll_visible(animate=False)
            if cell.result.kind == "plot":
                self.graph.show(cell.result.plot, f"[{cell.n}] {cell.src}")

    def move_selection(self, step: int) -> None:
        cells = self.cells
        if not cells:
            return
        k = cells.index(self.selected) if self.selected in cells else len(cells) - 1
        self.select(cells[max(0, min(len(cells) - 1, k + step))])

    def action_leave_cells(self) -> None:
        self.select(None)
        self.input.focus()

    def action_edit_cell(self) -> None:
        if not self.selected:
            return
        self.editing = self.selected
        self.input.value = self.selected.src
        self.input.cursor_position = len(self.input.value)
        self.input.add_class("-editing")
        self.action_leave_cells()
        self.update_status()

    def action_delete_cell(self) -> None:
        if not self.selected:
            return
        cells = self.cells
        k = cells.index(self.selected)
        gone = self.selected
        keep = [c for c in self.all_cells if c is not gone]
        gone.remove_class("-selected")
        self.selected = cells[k + 1] if k + 1 < len(cells) else (cells[k - 1] if k else None)
        if self.selected:
            self.selected.add_class("-selected")
        gone.deleted = True
        gone.remove()
        self.recompute([c.src for c in keep])
        if not self.selected:
            self.action_leave_cells()

    def action_copy_cell(self) -> None:
        if self.selected:
            self.copy(self.selected.result)

    def action_copy_cell_latex(self) -> None:
        if self.selected:
            self.copy(self.selected.result, latex=True)

    def action_insert_ref(self) -> None:
        if not self.selected:
            return
        ref = f"_{self.selected.n}"
        self.action_leave_cells()
        self.input.insert_text_at_cursor(ref)

    # -- misc actions ------------------------------------------------------

    def action_escape(self) -> None:
        if self.kernel.busy:
            self.kernel.interrupt()
        elif self.menu.display:
            self.menu.hide()
        elif self.editing:
            self.editing = None
            self.input.remove_class("-editing")
            self.input.value = ""
            self.update_status()
        elif self.input.value:
            self.input.value = ""
            self.hist_pos = None
        else:
            self.exit()

    def action_copy_last(self, latex: bool = False) -> None:
        for cell in reversed(self.cells):
            if cell.result.kind not in ("error", "plot"):
                self.copy(cell.result, latex)
                return
        self.notify("nothing to copy", severity="warning")

    def copy(self, result: Result, latex: bool = False) -> None:
        text = result.latex if latex else result.copy_text
        if result.kind in ("error", "plot") or not text:
            self.notify("nothing to copy", severity="warning")
            return
        self.to_clipboard(text)

    def to_clipboard(self, text: str) -> None:
        if shutil.which("wl-copy"):
            subprocess.run(["wl-copy", "--", text], check=False)
        else:
            self.copy_to_clipboard(text)
        self.notify(f"copied {text if len(text) < 40 else text[:37] + '…'}", timeout=2)

    def action_clear_view(self) -> None:
        """Like `clear` in a terminal: the screen empties, variables stay."""
        for cell in self.cells:
            cell.hide()
        self.select(None)
        self.graph.show(None)
        self.after_change()

    def action_new_sheet(self) -> None:
        """Start over: cells and variables both go."""
        self.graph.show(None)
        for cell in self.all_cells:
            cell.deleted = True
            cell.remove()
        self.select(None)
        self.editing = None
        self.input.remove_class("-editing")
        self.recompute([])

    def action_toggle_angle(self) -> None:
        self.degrees = not self.degrees
        self.notify("degrees" if self.degrees else "radians", timeout=1.5)
        self.recompute([c.src for c in self.all_cells])

    # -- sheets ------------------------------------------------------------

    def action_pick_sheet(self) -> None:
        def label(name: str) -> str:
            n = len(store.sheet_cells(store.load_sheet(name)))
            mark = "● " if name == self.sheet_name else "  "
            return f"{mark}{name}  ({n} cell{'s' * (n != 1)})"

        names = store.list_sheets()
        if self.sheet_name not in names:
            names.insert(0, self.sheet_name)

        def chosen(name: str | None) -> None:
            self.input.focus()
            if name:
                self.open_sheet(name)

        self.push_screen(PickerScreen([(n, label(n)) for n in names], "sheet name…", create="new sheet"), chosen)

    def open_sheet(self, name: str) -> None:
        if not store.valid_name(name):
            self.notify("sheet names: letters, digits, space . _ + -", severity="warning")
            return
        if name == self.sheet_name:
            return
        self.after_change()  # save the one we leave
        data = store.load_sheet(name)
        self.sheet_name = name
        store.set_current_sheet(name)
        self.digits = int(data.get("digits", 12))
        self.degrees = bool(data.get("degrees", False))
        for cell in self.all_cells:
            cell.deleted = True
            cell.remove()
        self.select(None)
        self.editing = None
        self.input.remove_class("-editing")
        self.graph.show(None)
        cells = store.sheet_cells(data)
        self.recompute([c for c, _ in cells], [h for _, h in cells])
        self.notify(f"sheet {name}" + ("" if cells else " (new)"), timeout=1.5)

    def rename_sheet(self, new: str) -> None:
        if not store.valid_name(new):
            self.notify("usage: :rename NEW-NAME", severity="warning")
            return
        try:
            self.after_change()
            store.rename_sheet(self.sheet_name, new)
        except FileExistsError:
            self.notify(f"there is already a sheet {new}", severity="warning")
            return
        self.sheet_name = new
        store.set_current_sheet(new)
        self.update_status()

    def delete_sheet(self, name: str) -> None:
        if not name or name not in store.list_sheets():
            self.notify("usage: :delete NAME (an existing sheet)", severity="warning")
        elif name == self.sheet_name:
            self.notify("switch to another sheet first (ctrl+o)", severity="warning")
        else:
            store.delete_sheet(name)
            self.notify(f"deleted sheet {name}")

    # -- export ------------------------------------------------------------

    def export(self, arg: str) -> None:
        kind, _, path = arg.partition(" ")
        kind = kind or "md"
        if kind not in ("md", "markdown", "ipynb", "notebook", "jupyter"):
            self.notify("usage: :export md [path]  or  :export ipynb [path]", severity="warning")
            return
        ext = "md" if kind in ("md", "markdown") else "ipynb"
        cells = [(c.n, c.src, c.result) for c in self.all_cells]
        if not cells:
            self.notify("nothing to export", severity="warning")
            return
        text = export.to_markdown(self.sheet_name, cells) if ext == "md" else export.to_notebook(self.sheet_name, cells)
        target = Path(path.strip()) if path.strip() else export.default_path(self.sheet_name, ext)
        if target.suffix != f".{ext}":
            target = target / f"{self.sheet_name}.{ext}" if target.is_dir() else target.with_suffix(f".{ext}")
        written = export.write(target, text)
        self.notify(f"saved {written}", title="export", timeout=6)

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def command(self, src: str) -> None:
        cmd, _, arg = src.lstrip(":").strip().partition(" ")
        if cmd in ("?", "help", "h"):
            self.action_help()
        elif cmd in ("deg", "rad"):
            if self.degrees != (cmd == "deg"):
                self.action_toggle_angle()
        elif cmd in ("digits", "sig", "fix"):
            if not arg.strip().isdigit() or not 1 <= int(arg) <= 1000:
                self.notify("usage: :digits 1-1000", severity="warning")
                return
            self.digits = int(arg)
            self.recompute([c.src for c in self.all_cells])
        elif cmd == "vars":
            body = "\n".join(f"{n}{sig} = {summary}"[:80] if not sig else f"{n}{sig}"
                             for n, (sig, summary) in sorted(self.names.items())) or "no variables"
            self.notify(body, title="variables", timeout=8)
        elif cmd in ("clear", "cls"):
            self.action_clear_view()
        elif cmd in ("new", "reset"):
            self.action_new_sheet()
        elif cmd == "latex":
            self.action_copy_last(latex=True)
        elif cmd == "export":
            self.export(arg.strip())
        elif cmd == "sheet":
            self.open_sheet(arg.strip()) if arg.strip() else self.action_pick_sheet()
        elif cmd == "sheets":
            self.action_pick_sheet()
        elif cmd == "rename":
            self.rename_sheet(arg.strip())
        elif cmd == "delete":
            self.delete_sheet(arg.strip())
        elif cmd in ("q", "quit", "exit"):
            self.exit()
        else:
            self.notify(f"unknown command :{cmd} — try ?", severity="warning")


def one_line(res: Result) -> str:
    if res.inline:
        approx = "   ".join(res.approx.split("\n")) if res.approx else ""
        return f"{res.inline}   ({approx})" if approx and len(res.inline) < 60 else res.inline
    if res.approx and "\n" not in res.approx:
        exact = res.text if "\n" not in res.text else None
        return f"{exact}  ≈ {res.approx}" if exact else f"≈ {res.approx}"
    if "\n" not in res.text:
        return res.text
    if res.value is not None:
        return sp.sstr(res.value).replace("**", "^")
    return " ".join(res.text.split())
