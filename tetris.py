#!/usr/bin/env python3
"""
Tetris CLI - A fully functional Tetris game for the terminal.
Controls:
  A / Left Arrow  : Move left
  D / Right Arrow : Move right
  S / Down Arrow  : Soft drop
  W / Up Arrow    : Rotate clockwise
  Space           : Hard drop
  P               : Pause / Resume
  R               : Restart
  Q               : Quit
"""

import sys
import os
import time
import random
import threading

# ──────────────────────────────────────────────
# Platform-specific input handling
# ──────────────────────────────────────────────
if sys.platform == "win32":
    import msvcrt

    def _getch_nowait():
        """Return a key string if one is available, else None. Windows."""
        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            # Arrow keys on Windows send 0x00 or 0xe0 followed by a code
            if ch in ('\x00', '\xe0'):
                ch2 = msvcrt.getwch()
                return {
                    'H': 'UP',
                    'P': 'DOWN',
                    'K': 'LEFT',
                    'M': 'RIGHT',
                }.get(ch2, None)
            return ch.lower()
        return None

    def setup_terminal():
        """No special setup needed on Windows."""
        pass

    def restore_terminal():
        """No restore needed on Windows."""
        pass

else:
    import tty
    import termios
    import select

    _orig_settings = None

    def setup_terminal():
        """Put terminal in raw mode (no echo, no line buffering)."""
        global _orig_settings
        fd = sys.stdin.fileno()
        _orig_settings = termios.tcgetattr(fd)
        tty.setraw(fd)

    def restore_terminal():
        """Restore original terminal settings."""
        global _orig_settings
        if _orig_settings is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _orig_settings)

    def _getch_nowait():
        """Return a key string if one is available, else None. Unix."""
        fd = sys.stdin.fileno()
        r, _, _ = select.select([fd], [], [], 0)
        if r:
            ch = os.read(fd, 32).decode('utf-8', errors='ignore')
            # Escape sequences for arrow keys
            if ch == '\x1b[A' or ch == '\x1bOA':
                return 'UP'
            if ch == '\x1b[B' or ch == '\x1bOB':
                return 'DOWN'
            if ch == '\x1b[D' or ch == '\x1bOD':
                return 'LEFT'
            if ch == '\x1b[C' or ch == '\x1bOC':
                return 'RIGHT'
            if ch == '\x1b':
                return None  # lone escape, ignore
            if ch:
                return ch[0].lower()
        return None


# ──────────────────────────────────────────────
# ANSI helpers
# ──────────────────────────────────────────────
RESET  = "\x1b[0m"
BOLD   = "\x1b[1m"
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
CLEAR_SCREEN = "\x1b[2J"
HOME = "\x1b[H"

def move_to(row, col):
    return f"\x1b[{row};{col}H"

def fg(r, g, b):
    return f"\x1b[38;2;{r};{g};{b}m"

def bg(r, g, b):
    return f"\x1b[48;2;{r};{g};{b}m"

# ──────────────────────────────────────────────
# Tetromino definitions
# ──────────────────────────────────────────────
# Each piece is a list of rotation states.
# Each rotation state is a list of (row, col) offsets from the pivot.
TETROMINOES = {
    'I': {
        'color': (0, 240, 240),   # Cyan
        'shapes': [
            [(0,0),(0,1),(0,2),(0,3)],
            [(0,2),(1,2),(2,2),(3,2)],
            [(2,0),(2,1),(2,2),(2,3)],
            [(0,1),(1,1),(2,1),(3,1)],
        ]
    },
    'O': {
        'color': (240, 240, 0),   # Yellow
        'shapes': [
            [(0,0),(0,1),(1,0),(1,1)],
            [(0,0),(0,1),(1,0),(1,1)],
            [(0,0),(0,1),(1,0),(1,1)],
            [(0,0),(0,1),(1,0),(1,1)],
        ]
    },
    'T': {
        'color': (160, 0, 240),   # Purple
        'shapes': [
            [(0,1),(1,0),(1,1),(1,2)],
            [(0,1),(1,1),(1,2),(2,1)],
            [(1,0),(1,1),(1,2),(2,1)],
            [(0,1),(1,0),(1,1),(2,1)],
        ]
    },
    'S': {
        'color': (0, 240, 0),     # Green
        'shapes': [
            [(0,1),(0,2),(1,0),(1,1)],
            [(0,1),(1,1),(1,2),(2,2)],
            [(1,1),(1,2),(2,0),(2,1)],
            [(0,0),(1,0),(1,1),(2,1)],
        ]
    },
    'Z': {
        'color': (240, 0, 0),     # Red
        'shapes': [
            [(0,0),(0,1),(1,1),(1,2)],
            [(0,2),(1,1),(1,2),(2,1)],
            [(1,0),(1,1),(2,1),(2,2)],
            [(0,1),(1,0),(1,1),(2,0)],
        ]
    },
    'J': {
        'color': (0, 0, 240),     # Blue
        'shapes': [
            [(0,0),(1,0),(1,1),(1,2)],
            [(0,1),(0,2),(1,1),(2,1)],
            [(1,0),(1,1),(1,2),(2,2)],
            [(0,1),(1,1),(2,0),(2,1)],
        ]
    },
    'L': {
        'color': (240, 160, 0),   # Orange
        'shapes': [
            [(0,2),(1,0),(1,1),(1,2)],
            [(0,1),(1,1),(2,1),(2,2)],
            [(1,0),(1,1),(1,2),(2,0)],
            [(0,0),(0,1),(1,1),(2,1)],
        ]
    },
}

PIECE_NAMES = list(TETROMINOES.keys())

# ──────────────────────────────────────────────
# Board constants
# ──────────────────────────────────────────────
BOARD_ROWS = 20
BOARD_COLS = 10

# Each cell is either None (empty) or a color tuple (r,g,b)
EMPTY = None

# ──────────────────────────────────────────────
# Scoring
# ──────────────────────────────────────────────
SCORE_TABLE = {1: 100, 2: 300, 3: 500, 4: 800}  # lines cleared → score (×level)
LINES_PER_LEVEL = 10  # lines needed to advance a level

# Drop interval in seconds per level (level 1..15+)
def drop_interval(level):
    # Starts at 1.0s, drops roughly 0.07s per level, floor at 0.05s
    return max(0.05, 1.0 - (level - 1) * 0.07)


# ──────────────────────────────────────────────
# Game state
# ──────────────────────────────────────────────
class Tetris:
    def __init__(self):
        self.reset()

    def reset(self):
        # Board: list of BOARD_ROWS lists, each with BOARD_COLS cells
        self.board = [[EMPTY] * BOARD_COLS for _ in range(BOARD_ROWS)]
        self.score = 0
        self.level = 1
        self.lines_cleared = 0
        self.game_over = False
        self.paused = False
        self.bag = []          # 7-bag randomizer
        self.current = None    # dict: name, color, shapes, rotation, row, col
        self.next_piece = None
        self._spawn_next()
        self._spawn_next()     # fill current and next

    # ── Bag randomizer (7-bag) ──────────────────
    def _next_from_bag(self):
        if not self.bag:
            self.bag = PIECE_NAMES[:]
            random.shuffle(self.bag)
        return self.bag.pop()

    # ── Spawn logic ────────────────────────────
    def _spawn_next(self):
        """Promote next→current and generate a new next_piece."""
        self.current = self.next_piece
        name = self._next_from_bag()
        info = TETROMINOES[name]
        self.next_piece = {
            'name': name,
            'color': info['color'],
            'shapes': info['shapes'],
            'rotation': 0,
            'row': 0,
            'col': BOARD_COLS // 2 - 2,
        }
        if self.current is None:
            return  # first call, current stays None until second call

        # Check game-over: if the spawned piece immediately collides
        if not self._valid(self.current, self.current['row'], self.current['col'],
                           self.current['rotation']):
            self.game_over = True

    # ── Geometry helpers ───────────────────────
    def _cells(self, piece, row, col, rotation):
        """Return list of (r, c) absolute board positions for a piece."""
        shape = piece['shapes'][rotation]
        return [(row + dr, col + dc) for dr, dc in shape]

    def _valid(self, piece, row, col, rotation):
        """True if the piece at (row, col) with given rotation is within bounds and not colliding."""
        for r, c in self._cells(piece, row, col, rotation):
            if c < 0 or c >= BOARD_COLS:
                return False
            if r >= BOARD_ROWS:
                return False
            if r >= 0 and self.board[r][c] is not EMPTY:
                return False
        return True

    # ── Movement ───────────────────────────────
    def move_left(self):
        p = self.current
        if p and self._valid(p, p['row'], p['col'] - 1, p['rotation']):
            p['col'] -= 1

    def move_right(self):
        p = self.current
        if p and self._valid(p, p['row'], p['col'] + 1, p['rotation']):
            p['col'] += 1

    def rotate(self):
        """Rotate clockwise with simple wall-kick attempts."""
        p = self.current
        if not p:
            return
        new_rot = (p['rotation'] + 1) % 4
        # Try original position, then kick left/right by 1 and 2
        for kick_col in [0, -1, 1, -2, 2]:
            if self._valid(p, p['row'], p['col'] + kick_col, new_rot):
                p['rotation'] = new_rot
                p['col'] += kick_col
                return

    def soft_drop(self):
        """Move down one row; if can't, lock the piece."""
        p = self.current
        if p and self._valid(p, p['row'] + 1, p['col'], p['rotation']):
            p['row'] += 1
            return True  # moved
        else:
            self._lock()
            return False  # locked

    def hard_drop(self):
        """Drop piece to the lowest valid position instantly."""
        p = self.current
        if not p:
            return
        while self._valid(p, p['row'] + 1, p['col'], p['rotation']):
            p['row'] += 1
            self.score += 2  # bonus per hard-drop row
        self._lock()

    def gravity_tick(self):
        """Called by the game loop at the drop interval."""
        if self.game_over or self.paused:
            return
        self.soft_drop()

    # ── Locking & line clearing ─────────────────
    def _lock(self):
        """Stamp the current piece onto the board, clear full lines, spawn next."""
        p = self.current
        for r, c in self._cells(p, p['row'], p['col'], p['rotation']):
            if 0 <= r < BOARD_ROWS and 0 <= c < BOARD_COLS:
                self.board[r][c] = p['color']

        cleared = self._clear_lines()
        if cleared:
            pts = SCORE_TABLE.get(cleared, cleared * 200) * self.level
            self.score += pts
            self.lines_cleared += cleared
            self.level = self.lines_cleared // LINES_PER_LEVEL + 1

        self._spawn_next()

    def _clear_lines(self):
        """Remove full rows, return count."""
        full = [r for r in range(BOARD_ROWS) if all(c is not EMPTY for c in self.board[r])]
        for r in full:
            del self.board[r]
            self.board.insert(0, [EMPTY] * BOARD_COLS)
        return len(full)

    # ── Ghost piece ─────────────────────────────
    def ghost_row(self):
        """Return the row where the current piece would land."""
        p = self.current
        if not p:
            return p
        row = p['row']
        while self._valid(p, row + 1, p['col'], p['rotation']):
            row += 1
        return row


# ──────────────────────────────────────────────
# Rendering
# ──────────────────────────────────────────────
# Layout constants (1-based terminal rows/cols)
BOARD_TOP  = 2   # terminal row where board starts
BOARD_LEFT = 3   # terminal col where board left border is
CELL_W = 2       # each cell is 2 chars wide ("██" or "  ")

INFO_COL = BOARD_LEFT + BOARD_COLS * CELL_W + 4  # info panel column

BORDER_COLOR = fg(100, 100, 120) + bg(20, 20, 30)
EMPTY_BG     = bg(15, 15, 20)
GHOST_CHAR   = "░░"
BLOCK_CHAR   = "██"
EMPTY_CHAR   = "  "

def _color_cell(color, char=BLOCK_CHAR):
    r, g, b = color
    return fg(r, g, b) + bg(r // 4, g // 4, b // 4) + char + RESET

def _ghost_cell():
    return fg(60, 60, 80) + EMPTY_BG + GHOST_CHAR + RESET

def _empty_cell():
    return EMPTY_BG + EMPTY_CHAR + RESET

def render(game, buf):
    """
    Build the entire frame into `buf` (list of strings), then flush once.
    Uses absolute cursor positioning to avoid scroll/flicker.
    """
    out = []

    # ── Title bar ──────────────────────────────
    out.append(move_to(1, 1))
    out.append(BOLD + fg(200, 200, 255) + bg(10, 10, 40))
    title = "  T E T R I S  CLI  "
    out.append(title.center(BOARD_COLS * CELL_W + 4 + 30))
    out.append(RESET)

    # ── Compute ghost row ──────────────────────
    ghost_r = game.ghost_row() if not game.game_over else None

    # Build sets of occupied cells for current piece and ghost
    cur_cells = set()
    ghost_cells = set()
    if game.current and not game.game_over:
        p = game.current
        cur_cells = set(game._cells(p, p['row'], p['col'], p['rotation']))
        if ghost_r is not None and ghost_r != p['row']:
            ghost_cells = set(game._cells(p, ghost_r, p['col'], p['rotation']))

    # ── Board rows ─────────────────────────────
    for row in range(BOARD_ROWS):
        term_row = BOARD_TOP + row
        out.append(move_to(term_row, BOARD_LEFT))
        # Left border
        out.append(BORDER_COLOR + "│" + RESET)
        for col in range(BOARD_COLS):
            if (row, col) in cur_cells:
                out.append(_color_cell(game.current['color']))
            elif (row, col) in ghost_cells:
                out.append(_ghost_cell())
            elif game.board[row][col] is not EMPTY:
                out.append(_color_cell(game.board[row][col]))
            else:
                out.append(_empty_cell())
        # Right border
        out.append(BORDER_COLOR + "│" + RESET)

    # ── Bottom border ──────────────────────────
    out.append(move_to(BOARD_TOP + BOARD_ROWS, BOARD_LEFT))
    out.append(BORDER_COLOR + "└" + "──" * BOARD_COLS + "┘" + RESET)

    # ── Top border ─────────────────────────────
    out.append(move_to(BOARD_TOP - 1, BOARD_LEFT))
    out.append(BORDER_COLOR + "┌" + "──" * BOARD_COLS + "┐" + RESET)

    # ── Info panel ─────────────────────────────
    def info_line(row, label, value, label_color=(160, 160, 200), val_color=(255, 255, 100)):
        out.append(move_to(BOARD_TOP + row, INFO_COL))
        out.append(fg(*label_color) + f"{label:<10}" + fg(*val_color) + BOLD + str(value) + RESET)

    out.append(move_to(BOARD_TOP, INFO_COL))
    out.append(BOLD + fg(200, 200, 255) + "── INFO ──" + RESET)

    info_line(2,  "Score:",  f"{game.score:,}")
    info_line(3,  "Level:",  game.level)
    info_line(4,  "Lines:",  game.lines_cleared)

    # Status
    out.append(move_to(BOARD_TOP + 6, INFO_COL))
    if game.game_over:
        status_str = fg(255, 60, 60) + BOLD + "GAME OVER" + RESET
    elif game.paused:
        status_str = fg(255, 200, 0) + BOLD + " PAUSED " + RESET
    else:
        status_str = fg(60, 255, 60) + BOLD + " PLAYING" + RESET
    out.append(fg(160, 160, 200) + "Status:   " + status_str)

    # Next piece preview
    out.append(move_to(BOARD_TOP + 8, INFO_COL))
    out.append(BOLD + fg(200, 200, 255) + "── NEXT ──" + RESET)
    _render_preview(game.next_piece, out, INFO_COL, BOARD_TOP + 9)

    # Controls
    ctrl_row = BOARD_TOP + 15
    out.append(move_to(ctrl_row, INFO_COL))
    out.append(BOLD + fg(200, 200, 255) + "─ CONTROLS─" + RESET)
    controls = [
        ("A/←", "Move Left"),
        ("D/→", "Move Right"),
        ("S/↓", "Soft Drop"),
        ("W/↑", "Rotate"),
        ("SPC", "Hard Drop"),
        ("P",   "Pause"),
        ("R",   "Restart"),
        ("Q",   "Quit"),
    ]
    for i, (key, desc) in enumerate(controls):
        out.append(move_to(ctrl_row + 1 + i, INFO_COL))
        out.append(fg(255, 200, 80) + f"{key:<5}" + fg(160, 160, 180) + desc + RESET)

    # ── Game Over overlay ──────────────────────
    if game.game_over:
        center_col = BOARD_LEFT + 1
        mid = BOARD_TOP + BOARD_ROWS // 2 - 1
        _overlay_box(out, mid, center_col, [
            "  GAME OVER  ",
            f" Score: {game.score:,} ",
            "",
            " R: Restart ",
            "  Q: Quit   ",
        ])

    # ── Pause overlay ──────────────────────────
    elif game.paused:
        center_col = BOARD_LEFT + 1
        mid = BOARD_TOP + BOARD_ROWS // 2 - 1
        _overlay_box(out, mid, center_col, [
            "  PAUSED  ",
            "",
            "P: Resume ",
            "R: Restart",
            " Q: Quit  ",
        ])

    # Flush
    sys.stdout.write("".join(out))
    sys.stdout.flush()


def _render_preview(piece, out, col, start_row):
    """Render 4×4 preview of the next piece."""
    if not piece:
        return
    shape = piece['shapes'][0]
    # Normalise to top-left
    min_r = min(r for r, c in shape)
    min_c = min(c for r, c in shape)
    cells = {(r - min_r, c - min_c) for r, c in shape}

    for row in range(4):
        out.append(move_to(start_row + row, col))
        out.append("          ")  # clear 10 chars
        out.append(move_to(start_row + row, col))
        for c in range(4):
            if (row, c) in cells:
                out.append(_color_cell(piece['color']))
            else:
                out.append(_empty_cell())


def _overlay_box(out, top_row, left_col, lines):
    """Draw a simple centered overlay box."""
    width = max(len(l) for l in lines) + 2
    bg_str = bg(30, 30, 60)
    border = fg(200, 200, 255) + bg_str

    out.append(move_to(top_row, left_col))
    out.append(border + "┌" + "─" * width + "┐" + RESET)
    for i, line in enumerate(lines):
        out.append(move_to(top_row + 1 + i, left_col))
        padded = line.center(width)
        out.append(border + "│" + fg(255, 255, 200) + bg_str + padded + border + "│" + RESET)
    out.append(move_to(top_row + 1 + len(lines), left_col))
    out.append(border + "└" + "─" * width + "┘" + RESET)


# ──────────────────────────────────────────────
# Main game loop
# ──────────────────────────────────────────────
def main():
    setup_terminal()
    sys.stdout.write(HIDE_CURSOR + CLEAR_SCREEN + HOME)
    sys.stdout.flush()

    game = Tetris()
    render_buf = []

    # Gravity timer state
    last_drop = time.monotonic()

    try:
        while True:
            now = time.monotonic()

            # ── Input handling ────────────────────
            key = _getch_nowait()
            if key is not None:
                if key == 'q':
                    break
                elif key == 'r':
                    game.reset()
                    last_drop = time.monotonic()
                elif key == 'p' and not game.game_over:
                    game.paused = not game.paused
                elif not game.game_over and not game.paused:
                    if key in ('a', 'left'):
                        game.move_left()
                    elif key in ('d', 'right'):
                        game.move_right()
                    elif key in ('w', 'up'):
                        game.rotate()
                    elif key in ('s', 'down'):
                        game.soft_drop()
                        last_drop = time.monotonic()
                    elif key == ' ':
                        game.hard_drop()
                        last_drop = time.monotonic()

            # ── Gravity ───────────────────────────
            if not game.game_over and not game.paused:
                interval = drop_interval(game.level)
                if now - last_drop >= interval:
                    game.gravity_tick()
                    last_drop = now

            # ── Render ────────────────────────────
            render(game, render_buf)

            # ── Frame throttle ────────────────────
            time.sleep(0.016)  # ~60 fps cap

    finally:
        # Always restore terminal
        sys.stdout.write(SHOW_CURSOR + RESET)
        sys.stdout.write(CLEAR_SCREEN + HOME)
        sys.stdout.flush()
        restore_terminal()
        print("Thanks for playing Tetris CLI!")


if __name__ == "__main__":
    main()
