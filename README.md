# Pascaline

A notebook calculator for [Omarchy](https://omarchy.org), named after the
[Pascaline](https://en.wikipedia.org/wiki/Pascaline), the mechanical calculator
Blaise Pascal built in 1642.

It feels like a scientific programmable Casio in a terminal: type math, see
the result while you type, press ⏎ to keep it as a numbered cell. Cells form
a small notebook: variables and functions carry over, any cell can be edited
and everything below it reruns, and the sheet comes back next time.

```
  1 › 2^10 + √2
    = √2 + 1024
    ≈ 1025.41421356

  2 › f(x) = x^2 - 2
    → f(x) = x² - 2

  3 › f(x) = 0
    ∴ x = -√2
    ∴ x = √2
    ≈ x ≈ -1.41421356237
    ≈ x ≈ 1.41421356237

  4 › plot(f(x), sin x, -3, 3)
    ◩ sketched in the graph panel
```

The window has two panes: commands and results on the left, and on the right
a graph panel that always draws its plot area square, sized from the terminal's
real cell proportions. It shows the latest sketch and previews `plot(...)` while
you type. Selecting an older plot cell brings it back. In a narrow window the
panel steps aside and sketches appear inline.

## Install

```sh
tools/install-omarchy     # venv, `pascaline` command, apps menu, shortcut
tools/uninstall-omarchy   # undo
```

**SUPER + CTRL + Q** (or the Calculator key) opens Pascaline as a small floating window (900×440; rerun the installer with
`PASCALINE_WIDTH=… PASCALINE_HEIGHT=…` to change it),
or focuses it if it is already open. Esc quits when the input is empty.
The installer takes these keys over from `omacalc`; the uninstaller gives them back.

From a shell: `pascaline '2^64 - 1'` prints one result and exits.

## What you can type

| Input | Meaning |
|---|---|
| `sqrt(2)`, `x**2`, `round(x, 2)`, `max(a, b)`, `math.pi` | plain Python works as is |
| `2x`, `3(x+1)`, `sin x` | Casio shortcuts: implicit multiplication / application |
| `x^2`, `5!`, `√2`, `π`, `e`, `i` | power, factorial, constants |
| `a = 3/4` | store a variable |
| `f(x) = x^2 + 1` | define a function |
| `x^2 - 4 = 0` | solve; `x+y=3, x-y=1` solves a system |
| `cos(x) = x` | numeric roots when there is no closed form |
| `ans`, `_3` | last result, result of cell 3 |
| `[[1,2],[3,4]]^-1` | matrices; `det`, `inv`, `tr` |
| `diff`, `integrate`, `limit`, `series`, `factor`, `expand`, `simplify`, `N(pi, 50)` | anything from SymPy |
| `plot(sin x, cos x, -pi, pi)` | braille sketch of one or more functions |

Exact answers come with a decimal approximation, like the S⇔D key.

## Typing

After two letters a menu pops up above the prompt with matching functions,
their arguments and a one-line description; your own variables and functions
come first. Tab takes the highlighted one and drops the cursor inside the
brackets, so `sq` Tab `2` gives `sqrt(2)`. ⏎ always evaluates unless you moved
through the menu with ↑↓. Brackets close themselves and Backspace on an empty
pair removes both.

## Keys

| Key | Action |
|---|---|
| ⏎ | evaluate (live preview while typing) |
| ↑ ↓ | input history |
| ctrl+r | search the whole history |
| tab | accept the completion (or ↑↓ to pick, then ⏎) |
| `(` `[` `{` | close themselves; with text selected they wrap it |
| ctrl+↑ | select cells: ⏎ edit · d delete · y copy · i insert `_n` · esc back |
| ctrl+y | copy the last result |
| ctrl+d | toggle DEG / RAD |
| ctrl+l | clear the view, variables stay (or type `clear`) |
| ctrl+n | new sheet, forget everything |
| ? / F1 | help |
| esc | clear input, or quit when empty |

Commands: `clear`, `:deg`, `:rad`, `:digits 20`, `:vars`, `:new`, `:q`.

## Data

Everything stays in this folder: `data/history.txt` (every line you evaluated)
and `data/sheet.json` (the current sheet). Set `PASCALINE_DATA` to keep them elsewhere.

## Development

```sh
.venv/bin/pytest
.venv/bin/ruff check src tests
```
