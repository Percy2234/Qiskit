
import math
import random

import numpy as np
import pygame
from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector

# ---------------- Settings ----------------
W, H = 960, 540
GROUND_H = 70
FPS = 60
GRAVITY = 0.45
FLAP = -8.0
START_SPEED = 2.2      # game starts slow
MAX_SPEED = 4.8        # speeds up
SPEED_STEP = 0.08      # extra speed per pipe passed
FLIP_SLOW = 0.7        # world moves slower while upside down
FLIP_GRAVITY = 0.7     # gravity is weaker while upside down (easier to control)
FLIP_RAMP = 30         # frames (0.5 s) for gravity to fade back in after a flip
FLIP_WARN = 60         # frames (1 s) the GRAVITY UP / DOWN warning stays on screen
FLIP_GAP_BONUS = 25    # both gaps are wider on the first pipe after turning upside down
INTRO_FRAMES = 150     # 2.5 s "TEAM JORDAN presents" splash at launch
ORB_CHANCE = 0.35      # chance a pipe has a power-up orb
FIRST_PIPE_X = 680     # where the first pipe starts (smaller = reach it sooner)
GATE_GAP = 145         # height of each of the two gaps in a pipe
PIPE_GAP = 170         # gap of a normal (single-entrance) pipe
GATE_CHANCE = 0.45     # chance a pipe has two entrances with gates (from the 2nd pipe on)
RY_FLIP = 0.4          # RY gate: 40% flip, 60% stay
RY_THETA = math.pi / 3 # 75%chance stay, 25% flip
GATE_COLS = {"X": (225, 60, 80), "RY": (140, 90, 230)}
PIPE_W = 58             # pipe thickness (was 80)
PIPE_SPACING = 300

# colours
SKY_TOP, SKY_BOT = (70, 160, 240), (190, 235, 255)
FLIP_TOP, FLIP_BOT = (90, 40, 170), (230, 160, 240)      # sky while upside down
PIPE_LIGHT, PIPE_MID, PIPE_DARK = (140, 225, 110), (80, 175, 70), (40, 110, 40)
BIRD = (150, 110, 230)                                   # original purple qubit bird
BIRD_DARK = (100, 70, 190)
GOLD = (255, 215, 70)
WHITE = (255, 255, 255)
INK = (30, 25, 60)


# ---------------- Quantum part ----------------
def build_circuit(upside_down, gate, theta_speed):
    """q0 = the bird's gravity qubit. Load its current state, then apply the gate it flew through.
    Angles set the probabilities (P(1) = sin^2(theta/2))."""
    qc = QuantumCircuit(3)
    if upside_down:
        qc.x(0)                      # prepare |1> if the bird is currently upside down
    if gate == "X":
        qc.x(0)                      # X: always flips  |0> <-> |1>
    elif gate == "RY":
        qc.ry(RY_THETA, 0)           # RY: 60% stay, 40% flip (same from |0> or |1>)
    # gate None (normal pipe): q0 is left alone, so gravity stays the same
    qc.ry(theta_speed, 1)
    # q2 decides slower / faster, but ONLY gets an H gate when q0 = 0 (not upside down).
    # X-CH-X = "controlled on |0>": if the bird is upside down, q2 stays |0> -> never FAST.
    # The rule lives inside the circuit (q0 and q2 become entangled), not in an if-statement.
    qc.x(0)
    qc.ch(0, 2)
    qc.x(0)
    return qc


def measure_once(qc):
    """Measure the circuit once. Qiskit bit order: rightmost character is q0."""
    counts = Statevector(qc).sample_counts(shots=1)
    bits = next(iter(counts))  # e.g. '101' (q2 q1 q0)
    q = [bits[-1 - i] == "1" for i in range(len(bits))]  # q[0] = q0, q[1] = q1, ...
    return bits, q


POWERUPS = {
    "0": ("GHOST", (220, 220, 255)),
    "1": ("DOUBLE", (255, 215, 70)),
}


def measure_powerup():
    """One qubit, one H gate: |0> or |1>, 50/50 -> GHOST or DOUBLE."""
    qc = QuantumCircuit(1)
    qc.h(0)
    bits = next(iter(Statevector(qc).sample_counts(shots=1)))
    return bits, POWERUPS[bits]


def prob_one(theta):
    return math.sin(theta / 2) ** 2


# ---------------- Drawing helpers ----------------
def gradient(top, bot, w=W, h=H):
    surf = pygame.Surface((w, h))
    for y in range(h):
        k = y / h
        c = [int(top[i] + (bot[i] - top[i]) * k) for i in range(3)]
        pygame.draw.line(surf, c, (0, y), (w, y))
    return surf


def text(surf, font, msg, pos, color=WHITE, center=True, shadow=True):
    """Text with a soft drop shadow so it stands out on any background."""
    if shadow:
        s = font.render(msg, True, (20, 15, 50))
        r = s.get_rect(center=pos) if center else s.get_rect(topleft=pos)
        s.set_alpha(140)
        surf.blit(s, r.move(3, 3))
    t = font.render(msg, True, color)
    r = t.get_rect(center=pos) if center else t.get_rect(topleft=pos)
    surf.blit(t, r)


def outlined(surf, font, msg, pos, color, outline=INK, w=3):
    """Chunky outlined title text."""
    base = font.render(msg, True, outline)
    r = base.get_rect(center=pos)
    for dx in range(-w, w + 1):
        for dy in range(-w, w + 1):
            if dx * dx + dy * dy <= w * w:
                surf.blit(base, r.move(dx, dy))
    surf.blit(font.render(msg, True, color), r)


def draw_cloud(surf, x, y, s, alpha=230):
    c = pygame.Surface((int(140 * s), int(70 * s)), pygame.SRCALPHA)
    for dx, dy, r in [(30, 45, 25), (60, 32, 32), (95, 42, 26), (75, 50, 22), (45, 52, 20)]:
        pygame.draw.circle(c, (255, 255, 255, alpha), (int(dx * s), int(dy * s)), int(r * s))
    surf.blit(c, (x, y))


# ---------------- Game objects ----------------
class Particle:
    def __init__(self, x, y, color, speed=4, life=40, size=4):
        a = random.uniform(0, math.tau)
        v = random.uniform(1, speed)
        self.x, self.y = x, y
        self.vx, self.vy = math.cos(a) * v, math.sin(a) * v
        self.color, self.life, self.max_life, self.size = color, life, life, size

    def update(self):
        self.x += self.vx
        self.y += self.vy
        self.vx *= 0.95
        self.vy *= 0.95
        self.life -= 1

    def draw(self, surf):
        k = self.life / self.max_life
        r = max(1, int(self.size * k))
        glow = pygame.Surface((r * 6, r * 6), pygame.SRCALPHA)
        pygame.draw.circle(glow, (*self.color, int(70 * k)), (r * 3, r * 3), r * 3)
        pygame.draw.circle(glow, (*self.color, int(255 * k)), (r * 3, r * 3), r)
        surf.blit(glow, (self.x - r * 3, self.y - r * 3))


class Bird:
    def __init__(self):
        self.x = W * 0.28
        self.y = H * 0.45
        self.vy = 0.0
        self.r = 20
        self.flipped = False
        self.flip_ramp = 0     # counts down after a flip; gravity fades in as it reaches 0
        self.trail = []

    def set_flipped(self, flipped):
        """Change gravity direction smoothly: stop the bird, then fade gravity back in."""
        if flipped != self.flipped:
            self.flipped = flipped
            self.vy = 0.0
            self.flip_ramp = FLIP_RAMP
            return True
        return False

    def gravity_factor(self):
        """Weaker gravity while upside down."""
        return FLIP_GRAVITY if self.flipped else 1.0

    def flap(self):
        # scale flap with gravity so jump height stays similar
        f = FLAP * math.sqrt(self.gravity_factor())
        self.vy = -f if self.flipped else f

    def update(self):
        ramp = 1.0 - self.flip_ramp / FLIP_RAMP          # 0 right after a flip -> 1 after 0.5 s
        if self.flip_ramp > 0:
            self.flip_ramp -= 1
        g = GRAVITY * self.gravity_factor() * ramp * (-1 if self.flipped else 1)
        self.vy += g
        self.vy = max(-11, min(11, self.vy))
        self.y += self.vy
        self.trail.append((self.x, self.y))
        self.trail = self.trail[-14:]

    def rect(self):
        return pygame.Rect(self.x - self.r + 4, self.y - self.r + 4, 2 * self.r - 8, 2 * self.r - 8)

    def draw(self, surf, t, ghost=False):
        # glowing quantum trail
        n = len(self.trail)
        for i, (tx, ty) in enumerate(self.trail[:-1]):
            k = i / n
            s = pygame.Surface((30, 30), pygame.SRCALPHA)
            pygame.draw.circle(s, (200, 170, 255, int(120 * k)), (15, 15), int(3 + 9 * k))
            surf.blit(s, (tx - 15 - (n - i) * 2, ty - 15))

        # ---- Quantum Falcon: angular body, swept wing, fierce eye, hooked beak ----
        body = pygame.Surface((100, 100), pygame.SRCALPHA)
        cx, cy, s = 48, 50, 1.3
        dark, mid, light = (70, 40, 160), (130, 90, 225), (190, 160, 255)
        lw = 2

        def pts(points, dy=0.0):
            return [(cx + x * s, cy + (y + dy) * s) for x, y in points]

        # soft purple glow behind the bird
        pygame.draw.circle(body, (200, 170, 255, 50), (cx, cy), 30)
        # tail spikes
        for d in (-6, 0, 6):
            pygame.draw.polygon(body, dark, pts([(-14, d - 3), (-32, d * 1.8), (-14, d + 3)]))
        # angular body + belly panel
        shape = [(-16, -2), (-6, -14), (10, -14), (22, -6), (24, 2), (12, 12), (-6, 12)]
        pygame.draw.polygon(body, mid, pts(shape))
        pygame.draw.polygon(body, light, pts([(-4, 2), (12, 2), (8, 10), (-4, 10)]))
        pygame.draw.polygon(body, INK, pts(shape), lw)
        # swept wing that flaps up and down
        wf = math.sin(t * 0.45) * 7
        wing = [(-2, -4), (-26, -26 + wf), (-18, -6 + wf * 0.5), (-30, -10 + wf), (-12, 4)]
        pygame.draw.polygon(body, dark, pts(wing))
        pygame.draw.polygon(body, light, pts([(-4, -4), (-22, -20 + wf), (-14, -4 + wf * 0.3)]))
        pygame.draw.polygon(body, INK, pts(wing), lw)
        # fierce eye with slanted brow
        pygame.draw.polygon(body, WHITE, pts([(8, -8), (18, -7), (16, -2), (8, -3)]))
        pygame.draw.circle(body, INK, (cx + 14 * s, cy - 5 * s), 2.4)
        pygame.draw.line(body, INK, (cx + 6 * s, cy - 11 * s), (cx + 19 * s, cy - 8 * s), 3)
        # hooked beak
        beak = [(22, -6), (34, -2), (30, 4), (24, 2)]
        pygame.draw.polygon(body, (255, 180, 40), pts(beak))
        pygame.draw.polygon(body, (210, 120, 20), pts([(24, 2), (30, 4), (26, 6)]))
        pygame.draw.polygon(body, INK, pts(beak), 1)
        # glowing gold crest (the |psi> antenna, now sharp)
        crest_glow = 2 + math.sin(t * 0.2) * 1.5
        pygame.draw.polygon(body, (255, 240, 150), pts([(-1, -14), (4, -26 - crest_glow), (9, -14)]))
        pygame.draw.polygon(body, GOLD, pts([(0, -14), (4, -24), (8, -14)]))

        angle = max(-30, min(60, self.vy * 4 * (-1 if self.flipped else 1)))
        body = pygame.transform.rotate(body, -angle)
        if self.flipped:
            body = pygame.transform.flip(body, False, True)
        if ghost:
            body.set_alpha(110 + int(60 * math.sin(t * 0.5)))   # see-through flicker
        surf.blit(body, body.get_rect(center=(self.x, self.y)))


class Pipe:
    _font = None

    def __init__(self, x, allow_orb=True, allow_gate=True):
        self.x = x
        self.passed = False
        self.chosen = None                               # which gap the bird flew through
        self.has_gates = allow_gate and random.random() < GATE_CHANCE
        if self.has_gates:
            # two entrances, each with a gate
            self.gap = GATE_GAP
            self.mid_h = random.randint(60, 90)          # block between the two gaps
            max_top = (H - GROUND_H) - 30 - 2 * self.gap - self.mid_h
            self.top_h = random.randint(30, max(30, max_top))
            self.gates = random.sample(["X", "RY"], 2)   # [upper gap gate, lower gap gate]
        else:
            # normal pipe: one entrance, no gate
            self.gap = PIPE_GAP
            self.gap_y = random.randint(130, H - GROUND_H - 130)
            self.gates = []
        self.orb = allow_orb and random.random() < ORB_CHANCE
        self.orb_gap = random.randint(0, 1) if self.has_gates else 0

    def gaps(self):
        """(top, bottom) of each gap: two for a gate pipe, one for a normal pipe."""
        if not self.has_gates:
            return [(self.gap_y - self.gap // 2, self.gap_y + self.gap // 2)]
        g1 = (self.top_h, self.top_h + self.gap)
        g2_top = g1[1] + self.mid_h
        return [g1, (g2_top, g2_top + self.gap)]

    def gap_center(self, i):
        a, b = self.gaps()[i]
        return (a + b) / 2

    def widen(self, extra):
        """Make the gap(s) bigger, taking the space from the blocks."""
        self.gap += extra
        if not self.has_gates:
            return
        self.top_h = max(20, self.top_h - extra // 2)
        self.mid_h = max(40, self.mid_h - extra // 2)
        overflow = self.gaps()[1][1] - (H - GROUND_H - 20)
        if overflow > 0:
            self.top_h = max(20, self.top_h - overflow)

    def orb_pos(self):
        # the orb floats just in front of one gap, so grabbing it means picking that gate
        return self.x - 60, self.gap_center(self.orb_gap)

    def draw_orb(self, surf, t):
        if not self.orb:
            return
        ox, oy = self.orb_pos()
        oy += math.sin(t * 0.1 + self.x * 0.01) * 6
        g = pygame.Surface((70, 70), pygame.SRCALPHA)
        pulse = 3 * math.sin(t * 0.2)
        # bright gold halo so the orb stands out on both blue and purple skies
        pygame.draw.circle(g, (255, 220, 80, 70), (35, 35), int(32 + pulse))
        pygame.draw.circle(g, (255, 235, 140, 120), (35, 35), int(24 + pulse))
        pygame.draw.circle(g, (40, 200, 255), (35, 35), 17)
        pygame.draw.circle(g, (255, 255, 255), (35, 35), 17, 3)
        # orbiting "electrons"
        for k in range(3):
            a = t * 0.12 + k * math.tau / 3
            pygame.draw.circle(g, GOLD, (int(35 + math.cos(a) * 24), int(35 + math.sin(a) * 10)), 3)
        surf.blit(g, (ox - 35, oy - 35))
        q = pygame.font.SysFont("arial", 15, bold=True).render("|?>", True, WHITE)
        surf.blit(q, q.get_rect(center=(ox, oy)))

    def rects(self):
        gs = self.gaps()
        rs = [pygame.Rect(self.x, 0, PIPE_W, gs[0][0])]                       # top block
        if self.has_gates:
            rs.append(pygame.Rect(self.x, gs[0][1], PIPE_W, gs[1][0] - gs[0][1]))  # middle block
        rs.append(pygame.Rect(self.x, gs[-1][1], PIPE_W, H - GROUND_H - gs[-1][1]))  # bottom block
        return rs

    @staticmethod
    def shaded_rect(surf, r):
        """Vertical colour bands give the pipe a rounded, shiny look."""
        if r.h <= 0:
            return
        bands = [(0.0, PIPE_DARK), (0.08, PIPE_MID), (0.25, PIPE_LIGHT), (0.38, (190, 245, 160)),
                 (0.48, PIPE_LIGHT), (0.7, PIPE_MID), (0.9, PIPE_DARK)]
        for i, (k, c) in enumerate(bands):
            x0 = r.x + int(r.w * k)
            x1 = r.x + int(r.w * (bands[i + 1][0] if i + 1 < len(bands) else 1))
            pygame.draw.rect(surf, c, (x0, r.y, x1 - x0, r.h))
        pygame.draw.rect(surf, (25, 70, 25), r, 3)

    def draw(self, surf):
        rs = self.rects()
        for r in rs:
            self.shaded_rect(surf, r)
        # caps on every edge that faces a gap
        cap_h = 22 if self.has_gates else 28
        edges = []
        for i, r in enumerate(rs):
            if i > 0:
                edges.append(r.y)                      # top edge faces the gap above
            if i < len(rs) - 1:
                edges.append(r.bottom - cap_h)         # bottom edge faces the gap below
        for y in edges:
            self.shaded_rect(surf, pygame.Rect(self.x - 7, y, PIPE_W + 14, cap_h))

    def draw_gates(self, surf, t):
        """A gate icon floating in each gap."""
        if not self.has_gates:
            return
        if Pipe._font is None:
            Pipe._font = (pygame.font.SysFont("arial", 24, bold=True),
                          pygame.font.SysFont("arial", 13, bold=True))
        f_big, f_small = Pipe._font
        for i, g in enumerate(self.gates):
            cx, cy = self.x + PIPE_W / 2, self.gap_center(i) + math.sin(t * 0.1 + i) * 3
            col = GATE_COLS[g]
            if self.chosen is not None and self.chosen != i:
                col = tuple(c // 2 + 60 for c in col)          # fade the gate you skipped
            box = pygame.Rect(0, 0, 52, 46)
            box.center = (cx, cy)
            pygame.draw.rect(surf, (20, 15, 50), box.move(2, 3), border_radius=10)
            pygame.draw.rect(surf, col, box, border_radius=10)
            pygame.draw.rect(surf, WHITE, box, 2, border_radius=10)
            label = f_big.render(g, True, WHITE)
            surf.blit(label, label.get_rect(center=(cx, cy)))


# ---------------- Main ----------------
def main(max_frames=None, screenshot=None, autoplay=False, start_playing=False):
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption(" The Qubird - Quantum Flight")
    clock = pygame.time.Clock()
    small = pygame.font.SysFont("arial", 18, bold=True)
    font = pygame.font.SysFont("arial", 22, bold=True)
    mid = pygame.font.SysFont("arial", 32, bold=True)
    big = pygame.font.SysFont("arial", 52, bold=True)
    huge = pygame.font.SysFont("arial", 96, bold=True)

    sky_normal = gradient(SKY_TOP, SKY_BOT)
    sky_flip = gradient(FLIP_TOP, FLIP_BOT)
    stars = [(random.randint(0, W), random.randint(0, H - 200), random.random()) for _ in range(60)]
    clouds = [[random.randint(0, W), random.randint(20, 220), random.uniform(0.6, 1.3)] for _ in range(6)]

    theta_speed = np.pi / 2  # speed change 50%

    state = "play" if start_playing else "intro"   # intro -> title -> play -> over -> title
    intro_timer = 0
    best = 0

    def new_game():
        return Bird(), [Pipe(FIRST_PIPE_X + i * PIPE_SPACING, allow_orb=i >= 1, allow_gate=i >= 1) for i in range(4)], 0

    bird, pipes, score = new_game()
    last_bits, effect_msg, badges = "---", "", []
    speed_mult = 1.0
    ghost_timer, double_pipes = 0, 0
    held = None            # stored power-up: (bits, name, colour), used with X
    flip_warn = 0          # frames left to show the gravity warning
    msg_timer = 0
    particles = []
    shake = 0
    flash = 0
    t = 0
    scroll = 0.0

    use_power = False
    bloch_anim = None      # [start angle, after-gate angle, measured angle, frame]
    popups = []            # small floating quantum labels next to the bird: [text, y, timer, colour]
    while True:
        t += 1
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                pygame.quit()
                return
            if e.type == pygame.KEYDOWN and state == "intro":
                state = "title"          # any key skips the intro
                continue
            if e.type == pygame.KEYDOWN:
                if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and state == "title":
                    state = "howto"                       # explain the quantum rules first
                elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and state == "howto":
                    bird, pipes, score = new_game()
                    last_bits, effect_msg, badges = "---", "", []
                    speed_mult = 1.0
                    ghost_timer, double_pipes = 0, 0
                    held = None
                    msg_timer, flash, shake = 0, 0, 0    # clear leftovers from the last game
                    flip_warn = 0
                    popups = []
                    bloch_anim = None
                    particles = []
                    state = "play"
                    bird.flap()
                elif e.key == pygame.K_SPACE and state == "play":
                    bird.flap()
                    for _ in range(5):
                        particles.append(Particle(bird.x - 15, bird.y, (230, 220, 255), 2, 20, 3))
                elif e.key == pygame.K_r and state == "over":
                    state = "title"
            if e.type == pygame.MOUSEBUTTONDOWN and state == "play":
                bird.flap()

        # ---- use the stored power-up (X key) ----
        if state == "play" and (use_power or (autoplay and held)) and held:
            pbits, pname, pcol = held
            held = None
            if pname == "GHOST":
                ghost_timer = FPS * 4
            else:
                double_pipes = 5
            effect_msg, msg_timer, flash = f"{pname} ON!", 70, 8
            popups.append([f"superposition  ->  measured |{pbits}>  =  {pname}", bird.y, 100, pcol])
            for _ in range(35):
                particles.append(Particle(bird.x, bird.y, random.choice([pcol, WHITE]), 7, 50, 5))
        use_power = False

        base_speed = min(MAX_SPEED, START_SPEED + score * SPEED_STEP)   # gets faster over time
        if state == "play":
            speed = base_speed * speed_mult * (FLIP_SLOW if bird.flipped else 1.0)
        else:
            speed = START_SPEED * 0.6
        if state != "over":
            scroll += speed

        if state == "intro":
            intro_timer += 1
            if intro_timer > INTRO_FRAMES:
                state = "title"

        if state in ("intro", "title", "howto"):
            # bird bobs gently on the title screen
            bird.y = H * 0.48 + math.sin(t * 0.06) * 18
            bird.flipped = False
            bird.trail = []

        if state == "play":
            # autoplay (for testing)
            if autoplay:
                nxt = next(p for p in pipes if p.x + PIPE_W > bird.x - bird.r)
                gi = min(range(len(nxt.gaps())), key=lambda i: abs(nxt.gap_center(i) - bird.y)) if nxt.chosen is None else nxt.chosen
                target = nxt.gap_center(gi) + (-25 if bird.flipped else 25)
                if (not bird.flipped and bird.y > target and bird.vy > 0) or \
                   (bird.flipped and bird.y < target and bird.vy < 0):
                    bird.flap()

            bird.update()
            for p in pipes:
                p.x -= speed
                # remember which gap (= which gate) the bird flew through
                if p.chosen is None and p.x + PIPE_W / 2 <= bird.x:
                    gs = p.gaps()
                    p.chosen = 0 if len(gs) == 1 or bird.y < (gs[0][1] + gs[1][0]) / 2 else 1
                # measure only after the bird's whole body has cleared the pipe (cap included)
                if not p.passed and p.x + PIPE_W + 7 < bird.x - bird.r:
                    p.passed = True
                    score += 2 if double_pipes > 0 else 1
                    double_pipes = max(0, double_pipes - 1)
                    # passed a pipe -> quantum measurement
                    gate = p.gates[p.chosen if p.chosen is not None else 0] if p.has_gates else None
                    was_flipped = bird.flipped
                    qc = build_circuit(was_flipped, gate, theta_speed)
                    last_bits, q = measure_once(qc)
                    if gate is None:
                        gate_msg = ""                       # normal pipe: gravity unchanged
                    elif gate == "X":
                        gate_msg = "X: FLIPPED!"
                    elif q[0] != was_flipped:
                        gate_msg = "RY: FLIPPED"
                    else:
                        gate_msg = "RY: STAYED"
                    if gate:
                        before, after = int(was_flipped), int(q[0])
                        # Bloch arrow: rotate by the gate (superposition), then snap to the measured pole
                        start_a = math.pi * before
                        bloch_anim = [start_a, start_a + (math.pi if gate == "X" else RY_THETA),
                                      math.pi * after, 0]
                        popups.append([f"|{before}>  ->  {gate} gate  ->  measure  ->  |{after}>",
                                       bird.y, 110, GATE_COLS[gate]])
                    if bird.set_flipped(q[0]):
                        flip_warn = FLIP_WARN
                        if bird.flipped:
                            # give the next pipe wider gaps while the player adapts
                            nxt_pipe = next((pp for pp in pipes if not pp.passed and pp.chosen is None), None)
                            if nxt_pipe:
                                nxt_pipe.widen(FLIP_GAP_BONUS)
                    speed_mult = (1.6 if q[2] else 0.55) if q[1] else 1.0
                    badges = []
                    if q[0]:
                        badges.append(("UPSIDE DOWN", (110, 50, 180)))
                    if q[1]:
                        if q[2]:
                            badges.append(("FAST", (230, 80, 70)))
                        elif q[0]:
                            badges.append(("SLOW (entangled)", (60, 140, 230)))   # forced by the CH gate
                        else:
                            badges.append(("SLOW", (60, 140, 230)))
                    speed_part = [b[0] for b in badges if b[0].startswith(("FAST", "SLOW"))]
                    effect_msg = " + ".join([m for m in [gate_msg] + speed_part if m])
                    msg_timer = 0      # the floating label, badges and Bloch sphere explain it - keep the centre clear
                    flash = 10 if gate else 0
                    # quantum sparkle burst (bigger when a gate was applied)
                    for _ in range(30 if gate else 8):
                        particles.append(Particle(bird.x, bird.y, random.choice(
                            [(200, 160, 255), GOLD, (120, 220, 255)]), 6, 45, 5))
            if pipes[0].x < -PIPE_W - 20:
                pipes.pop(0)
                pipes.append(Pipe(pipes[-1].x + PIPE_SPACING))

            # grab a power-up orb -> quantum measurement decides which one
            for p in pipes:
                if p.orb:
                    ox, oy = p.orb_pos()
                    if (ox - bird.x) ** 2 + (oy - bird.y) ** 2 < (bird.r + 18) ** 2:
                        p.orb = False
                        pbits, (pname, pcol) = measure_powerup()
                        held = (pbits, pname, pcol)
                        use_power = True                   # applied automatically on the next frame
                        msg_timer = 90
                        flash = 8
                        for _ in range(35):
                            particles.append(Particle(ox, oy, random.choice([pcol, WHITE]), 7, 50, 5))

            if ghost_timer > 0:
                ghost_timer -= 1

            br = bird.rect()
            hit_edge = bird.y - bird.r < 0 or bird.y + bird.r > H - GROUND_H
            hit_pipe = ghost_timer == 0 and any(br.colliderect(r) for p in pipes for r in p.rects())
            hit = hit_edge or hit_pipe
            if hit:
                state = "over"
                best = max(best, score)
                shake = 18
                for _ in range(40):
                    particles.append(Particle(bird.x, bird.y, random.choice([BIRD, WHITE, GOLD]), 7, 50, 6))

        for pt in particles:
            pt.update()
        particles = [pt for pt in particles if pt.life > 0]

        # ---------------- Drawing ----------------
        frame = pygame.Surface((W, H))
        frame.blit(sky_flip if bird.flipped else sky_normal, (0, 0))

        # twinkling stars while upside down
        if bird.flipped:
            for sx, sy, ph in stars:
                a = int(150 + 100 * math.sin(t * 0.08 + ph * 10))
                s = pygame.Surface((6, 6), pygame.SRCALPHA)
                pygame.draw.circle(s, (255, 255, 255, a), (3, 3), 2)
                frame.blit(s, (sx, sy))

        # parallax clouds
        for c in clouds:
            if state != "over":
                c[0] -= speed * 0.25 * c[2]
            if c[0] < -160:
                c[0], c[1] = W + random.randint(0, 200), random.randint(20, 220)
            draw_cloud(frame, c[0], c[1], c[2], 200 if not bird.flipped else 110)

        # parallax hills (far + near)
        for col, base, amp, wl, k in [((140, 205, 150), H - GROUND_H - 110, 40, 260, 0.2),
                                       ((95, 185, 95), H - GROUND_H - 50, 30, 180, 0.45)]:
            pts = [(0, H - GROUND_H)]
            for x in range(0, W + 21, 20):
                pts.append((x, base + math.sin((x + scroll * k) / wl * math.tau) * amp))
            pts.append((W, H - GROUND_H))
            pygame.draw.polygon(frame, col, pts)

        if state in ("play", "over"):
            for p in pipes:
                p.draw(frame)
            for p in pipes:
                p.draw_gates(frame, t)
            for p in pipes:
                p.draw_orb(frame, t)

        # speed lines while FAST
        if speed_mult > 1 and state == "play":
            for i in range(10):
                y = (i * 53 + t * 7) % (H - GROUND_H)
                x = W - (t * 30 + i * 131) % (W + 200)
                pygame.draw.line(frame, WHITE, (x, y), (x + 70, y), 2)

        if state != "howto":
            bird.draw(frame, t, ghost=ghost_timer > 0)

        for pt in particles:
            pt.draw(frame)

        # ground with scrolling stripes
        gy = H - GROUND_H
        pygame.draw.rect(frame, (222, 210, 150), (0, gy, W, GROUND_H))
        pygame.draw.rect(frame, (100, 185, 60), (0, gy, W, 18))
        off = int(scroll) % 40
        for x in range(-40, W + 40, 40):
            pygame.draw.polygon(frame, (75, 155, 45),
                                [(x - off, gy + 18), (x - off + 20, gy), (x - off + 40, gy), (x - off + 20, gy + 18)])
        pygame.draw.line(frame, (60, 120, 40), (0, gy), (W, gy), 3)

        # -------- screens --------
        if state == "intro":
            # fade in, hold, fade out
            k = intro_timer / INTRO_FRAMES
            alpha = min(1.0, k * 4, (1 - k) * 4)
            veil = pygame.Surface((W, H))
            veil.fill(INK)
            veil.set_alpha(int(255 * (0.55 + 0.45 * (1 - k))))
            frame.blit(veil, (0, 0))
            layer = pygame.Surface((W, H), pygame.SRCALPHA)
            outlined(layer, huge, "TEAM JORDAN", (W // 2, H // 2 - 20), GOLD, INK, 5)
            text(layer, mid, "Team members: Daniel, Percy", (W // 2, H // 2 + 55), WHITE)
            text(layer, font, "presents", (W // 2, H // 2 + 100), (230, 220, 255))
            layer.set_alpha(int(255 * max(0.0, alpha)))
            frame.blit(layer, (0, 0))

        if state == "howto":
            veil = pygame.Surface((W, H), pygame.SRCALPHA)
            veil.fill((15, 8, 40, 200))
            frame.blit(veil, (0, 0))
            outlined(frame, big, "HOW THE QUANTUM WORKS", (W // 2, 58), GOLD, INK, 3)
            rows = [
                ("QUBIT", "The bird's gravity.   |0> = normal,   |1> = upside down"),
                ("GATE", "Pick an entrance.   X = always flip,   RY = tilt the arrow (maybe flip)"),
                ("SUPERPOSITION", "A tilted Bloch arrow = not decided yet (like a spinning coin)"),
                ("MEASUREMENT", "The pipe snaps the arrow to |0> or |1> - gravity follows"),
                ("ENTANGLEMENT", "Gravity and speed are linked: upside down is never FAST"),
            ]
            for i, (word, desc) in enumerate(rows):
                y = 130 + i * 58
                box = pygame.Rect(70, y - 20, 190, 40)
                pygame.draw.rect(frame, (90, 50, 170), box, border_radius=12)
                pygame.draw.rect(frame, (200, 170, 255), box, 2, border_radius=12)
                wl = small.render(word, True, GOLD)
                frame.blit(wl, wl.get_rect(center=box.center))
                frame.blit(small.render(desc, True, WHITE), (280, y - 10))
            text(frame, small, "Orbs:  1 qubit + H gate  ->  |0> GHOST  or  |1> DOUBLE  (50 / 50)",
                 (W // 2, 425), (210, 230, 255))
            if (t // 30) % 2 == 0:
                outlined(frame, font, "PRESS ENTER TO FLY", (W // 2, 470), WHITE, INK, 2)

        if state == "title":
            veil = pygame.Surface((W, H), pygame.SRCALPHA)
            veil.fill((20, 10, 50, 90))
            frame.blit(veil, (0, 0))
            bob = math.sin(t * 0.05) * 6
            outlined(frame, huge, "QUBIRD", (W // 2, 120 + bob), GOLD, INK, 5)
            text(frame, font, "a quantum flight", (W // 2, 190 + bob), (230, 220, 255))
            if (t // 30) % 2 == 0:
                outlined(frame, big, "PRESS ENTER", (W // 2, 360), WHITE, INK, 3)
            text(frame, small, "SPACE = flap      the bird's gravity is a QUBIT - gates change it, pipes MEASURE it",
                 (W // 2, 420), WHITE)
            text(frame, small, f"Best: {best}", (W // 2, 450), GOLD)
            credit = "made by TEAM JORDAN  \u00b7  Daniel & Percy"
            text(frame, small, credit, (W - 14 - small.size(credit)[0], H - 32), (240, 235, 255), center=False)

        if state in ("play", "over"):
            outlined(frame, big, str(score), (W // 2, 45), WHITE, INK, 3)

            # active power-ups + speed level (top-left)
            active = []
            if held:
                active.append((f"[X] {held[1]}", held[2]))
            if ghost_timer > 0:
                active.append((f"GHOST {ghost_timer / FPS:.1f}s", POWERUPS["0"][1]))
            if double_pipes > 0:
                active.append((f"x2 for {double_pipes}", POWERUPS["1"][1]))
            for i, (label, col) in enumerate(active):
                w = small.size(label)[0] + 20
                border = 2 + (1 if label.startswith("[X]") and (t // 15) % 2 else 0)   # stored one blinks
                pygame.draw.rect(frame, (20, 15, 50), (14, 14 + i * 34, w, 28), border_radius=14)
                pygame.draw.rect(frame, col, (14, 14 + i * 34, w, 28), border, border_radius=14)
                frame.blit(small.render(label, True, col), (24, 18 + i * 34))

            # active effects stay on screen until the next pipe
            bx = W // 2 - sum(font.size(b[0])[0] + 34 for b in badges) // 2
            for label, color in badges:
                w = font.size(label)[0] + 24
                pygame.draw.rect(frame, (20, 15, 50), (bx + 2, 84, w, 34), border_radius=17)
                pygame.draw.rect(frame, color, (bx, 80, w, 34), border_radius=17)
                pygame.draw.rect(frame, WHITE, (bx, 80, w, 34), 2, border_radius=17)
                frame.blit(font.render(label, True, WHITE), (bx + 12, 85))
                bx += w + 10

            # ---- Bloch sphere of the bird's gravity qubit (bottom-right, where the bird never flies) ----
            pw, ph = 170, 186
            px, py = W - pw - 12, H - GROUND_H - ph - 10
            panel = pygame.Surface((pw, ph), pygame.SRCALPHA)
            pygame.draw.rect(panel, (25, 15, 60, 185), panel.get_rect(), border_radius=14)
            pygame.draw.rect(panel, (180, 150, 255, 200), panel.get_rect(), 2, border_radius=14)
            frame.blit(panel, (px, py))
            bcx, bcy, br_ = px + pw // 2, py + 92, 40
            # arrow angle: 0 = |0> (top), pi = |1> (bottom)
            caption = "measured" if bloch_anim is None else ""
            ang = math.pi if bird.flipped else 0.0
            if bloch_anim is not None:
                a0, a1, a2, f = bloch_anim
                if f < 25:                                   # gate rotates the arrow
                    k = f / 25
                    ang = a0 + (a1 - a0) * (1 - (1 - k) ** 2)
                    caption = "gate rotating..."
                elif f < 55:                                 # hold in superposition
                    ang = a1
                    caption = "superposition" if abs(math.sin(a1)) > 0.05 else "gate applied"
                elif f < 67:                                 # collapse to the measured pole
                    k = (f - 55) / 12
                    ang = a1 + (a2 + (2 * math.pi if a1 - a2 > math.pi else 0) - a1) * k
                    caption = "MEASURE!"
                else:
                    bloch_anim = None
                    ang = a2
                    caption = "measured"
                if bloch_anim is not None and state == "play":
                    bloch_anim[3] += 1
            # sphere
            sph = pygame.Surface((br_ * 2 + 4, br_ * 2 + 4), pygame.SRCALPHA)
            pygame.draw.circle(sph, (120, 90, 220, 70), (br_ + 2, br_ + 2), br_)
            pygame.draw.circle(sph, (200, 180, 255, 220), (br_ + 2, br_ + 2), br_, 2)
            pygame.draw.ellipse(sph, (200, 180, 255, 140), (2, br_ + 2 - br_ * 0.3, br_ * 2, br_ * 0.6), 1)
            pygame.draw.line(sph, (200, 180, 255, 110), (br_ + 2, 2), (br_ + 2, br_ * 2 + 2), 1)
            frame.blit(sph, (bcx - br_ - 2, bcy - br_ - 2))
            l0 = small.render("|0>", True, (220, 230, 255))
            l1 = small.render("|1>", True, (220, 230, 255))
            frame.blit(l0, l0.get_rect(midbottom=(bcx, bcy - br_ - 2)))
            frame.blit(l1, l1.get_rect(midtop=(bcx, bcy + br_ + 2)))
            # arrow (rotation in the x-z plane, like an RY gate)
            ex, ey = bcx + br_ * math.sin(ang), bcy - br_ * math.cos(ang)
            pygame.draw.line(frame, GOLD, (bcx, bcy), (ex, ey), 4)
            pygame.draw.circle(frame, GOLD, (int(ex), int(ey)), 6)
            pygame.draw.circle(frame, WHITE, (int(ex), int(ey)), 6, 2)
            pygame.draw.circle(frame, WHITE, (bcx, bcy), 3)
            title_s = small.render("Gravity qubit", True, WHITE)
            frame.blit(title_s, title_s.get_rect(midtop=(bcx, py + 6)))
            cap = small.render(caption, True, GOLD)
            frame.blit(cap, cap.get_rect(midtop=(bcx, py + 158)))

        if msg_timer > 0 and state == "play" and effect_msg:
            msg_timer -= 1
            scale = 1 + max(0, msg_timer - 75) * 0.04      # pops in, then settles
            m = big.render(effect_msg, True, GOLD)
            fit = min(1.0, (W - 80) / m.get_width())           # long combos shrink to fit
            m = pygame.transform.rotozoom(m, 0, scale * fit)
            m.set_alpha(min(255, msg_timer * 6))
            frame.blit(m, m.get_rect(center=(W // 2, H // 2 - 70)))

        # big gravity warning right after a flip (drawn on top of everything)
        if flip_warn > 0 and state == "play":
            flip_warn -= 1
            label = "\u2191 GRAVITY UP \u2191" if bird.flipped else "\u2193 GRAVITY DOWN \u2193"
            col = (255, 240, 120) if bird.flipped else (200, 240, 255)
            wy = bird.y + (55 if bird.flipped else -55)          # opposite side to where it falls
            if (flip_warn // 6) % 2 == 0 or flip_warn > FLIP_WARN - 20:
                outlined(frame, font, label, (bird.x + 20, wy), col, INK, 3)

        # floating quantum labels next to the bird
        if state == "play":
            for i, pop in enumerate(popups):
                label, py0, timer, col = pop
                rise = (110 - timer) * 0.6
                surf_t = small.render(label, True, WHITE)
                bx_ = pygame.Rect(0, 0, surf_t.get_width() + 20, 28)
                if py0 < 170:      # bird near the top -> show the label below it instead
                    bx_.midleft = (bird.x + 34, py0 + 45 + rise + i * 32)
                else:
                    bx_.midleft = (bird.x + 34, py0 - 40 - rise - i * 32)
                bx_.x = min(bx_.x, W - bx_.w - 10)
                bx_.y = max(10, min(bx_.y, H - GROUND_H - 40))
                tag = pygame.Surface(bx_.size, pygame.SRCALPHA)
                a = min(255, timer * 6)
                pygame.draw.rect(tag, (20, 12, 50, int(a * 0.85)), tag.get_rect(), border_radius=14)
                pygame.draw.rect(tag, (*col, a), tag.get_rect(), 2, border_radius=14)
                surf_t.set_alpha(a)
                tag.blit(surf_t, (10, 4))
                frame.blit(tag, bx_)
                pop[2] -= 1
            popups = [pp for pp in popups if pp[2] > 0]

        if state == "over":
            veil = pygame.Surface((W, H), pygame.SRCALPHA)
            veil.fill((20, 10, 50, 120))
            frame.blit(veil, (0, 0))
            outlined(frame, huge, "GAME OVER", (W // 2, H // 2 - 30), (255, 110, 120), INK, 5)
            text(frame, font, f"Score {score}   Best {best}", (W // 2, H // 2 + 40), GOLD)
            if (t // 30) % 2 == 0:
                text(frame, font, "Press R", (W // 2, H // 2 + 80), WHITE)

        # white flash when the circuit is measured
        if flash > 0:
            fl = pygame.Surface((W, H), pygame.SRCALPHA)
            fl.fill((255, 255, 255, flash * 12))
            frame.blit(fl, (0, 0))
            flash -= 1

        # screen shake on crash
        ox = oy = 0
        if shake > 0:
            ox, oy = random.randint(-shake, shake), random.randint(-shake, shake)
            shake -= 1
        screen.fill(INK)
        screen.blit(frame, (ox, oy))

        pygame.display.flip()
        clock.tick(FPS if not max_frames else 0)

        if max_frames and t >= max_frames:
            if screenshot:
                pygame.image.save(screen, screenshot)
            pygame.quit()
            return score


if __name__ == "__main__":
    main()