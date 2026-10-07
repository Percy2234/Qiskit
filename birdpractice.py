"""
Qubird - a bird game where a quantum circuit decides the effects
Every time the bird passes a pipe, a 3-qubit circuit is measured once.
Each effect has its own qubit, so several effects can stack at once.
  q0 = 1  -> upside down (gravity flips, bird falls UP)
  q1 = 1  -> horizontal speed changes
  q2      -> 0 = slower, 1 = faster (H gate controlled on q0 = 0,
             so when upside down it is ALWAYS slower - never FAST)

Upside down also slows the world down (x0.7) to keep it fair.
The game starts slow and speeds up a little with every pipe.

Power-ups (glowing orbs in some pipe gaps)
  Grabbing an orb measures a 2-qubit circuit H(0) H(1) -> 4 equally likely outcomes.
  The power-up is stored (one slot) and only used when you press X:
  |00> SHIELD    survive one pipe hit (quantum error correction!)
  |01> GHOST     pass through pipes for 4 seconds (tunnelling)
  |10> COLLAPSE  next pipe gives no effects (state collapses to |000>)
  |11> DOUBLE    next 5 pipes are worth 2 points

Controls
  ENTER         : start game
  SPACE / click : flap
  X             : use the stored power-up
  R             : back to title after game over
"""
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
START_SPEED = 2.2      # game starts slow...
MAX_SPEED = 4.8        # ...and speeds up to this
SPEED_STEP = 0.08      # extra speed per pipe passed
FLIP_SLOW = 0.7        # world moves slower while upside down
FLIP_GRAVITY = 0.7     # gravity is weaker while upside down (easier to control)
ORB_CHANCE = 0.35      # chance a pipe has a power-up orb
FIRST_PIPE_X = 680     # where the first pipe starts (smaller = reach it sooner)
PIPE_GAP = 170
PIPE_W = 80
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
def build_circuit(theta_flip, theta_speed):
    """Circuit that decides the effects. Angles set the probabilities (P(1) = sin^2(theta/2))."""
    qc = QuantumCircuit(3)
    qc.ry(theta_flip, 0)
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
    "00": ("SHIELD", (80, 200, 255)),
    "01": ("GHOST", (220, 220, 255)),
    "10": ("COLLAPSE", (255, 150, 60)),
    "11": ("DOUBLE", (255, 215, 70)),
}


def measure_powerup():
    """Two qubits in equal superposition -> each power-up has a 25% chance."""
    qc = QuantumCircuit(2)
    qc.h([0, 1])
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
        self.trail = []

    def gravity_factor(self):
        """Weaker gravity while upside down."""
        return FLIP_GRAVITY if self.flipped else 1.0

    def flap(self):
        # scale flap with gravity so jump height stays similar
        f = FLAP * math.sqrt(self.gravity_factor())
        self.vy = -f if self.flipped else f

    def update(self):
        g = GRAVITY * self.gravity_factor() * (-1 if self.flipped else 1)
        self.vy += g
        self.vy = max(-11, min(11, self.vy))
        self.y += self.vy
        self.trail.append((self.x, self.y))
        self.trail = self.trail[-14:]

    def rect(self):
        return pygame.Rect(self.x - self.r + 4, self.y - self.r + 4, 2 * self.r - 8, 2 * self.r - 8)

    def draw(self, surf, t, ghost=False, shield=False):
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
        if shield:
            bubble = pygame.Surface((80, 80), pygame.SRCALPHA)
            pulse = int(4 * math.sin(t * 0.15))
            pygame.draw.circle(bubble, (80, 200, 255, 60), (40, 40), 34 + pulse)
            pygame.draw.circle(bubble, (150, 230, 255, 220), (40, 40), 34 + pulse, 3)
            surf.blit(bubble, (self.x - 40, self.y - 40))


class Pipe:
    def __init__(self, x, allow_orb=True):
        self.x = x
        self.gap_y = random.randint(130, H - GROUND_H - 130)
        self.passed = False
        self.orb = allow_orb and random.random() < ORB_CHANCE

    def orb_pos(self):
        return self.x + PIPE_W / 2, self.gap_y

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
        q = pygame.font.SysFont("arial", 20, bold=True).render("?", True, WHITE)
        surf.blit(q, q.get_rect(center=(ox, oy)))

    def rects(self):
        top = pygame.Rect(self.x, 0, PIPE_W, self.gap_y - PIPE_GAP // 2)
        bot_y = self.gap_y + PIPE_GAP // 2
        bot = pygame.Rect(self.x, bot_y, PIPE_W, H - GROUND_H - bot_y)
        return top, bot

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
        top, bot = self.rects()
        for r, is_top in ((top, True), (bot, False)):
            self.shaded_rect(surf, r)
            cap = pygame.Rect(r.x - 7, r.bottom - 28 if is_top else r.y, PIPE_W + 14, 28)
            self.shaded_rect(surf, cap)


# ---------------- Main ----------------
def main(max_frames=None, screenshot=None, autoplay=False, start_playing=False):
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Qubird - Quantum Flight")
    clock = pygame.time.Clock()
    small = pygame.font.SysFont("arial", 18, bold=True)
    font = pygame.font.SysFont("arial", 22, bold=True)
    big = pygame.font.SysFont("arial", 52, bold=True)
    huge = pygame.font.SysFont("arial", 96, bold=True)

    sky_normal = gradient(SKY_TOP, SKY_BOT)
    sky_flip = gradient(FLIP_TOP, FLIP_BOT)
    stars = [(random.randint(0, W), random.randint(0, H - 200), random.random()) for _ in range(60)]
    clouds = [[random.randint(0, W), random.randint(20, 220), random.uniform(0.6, 1.3)] for _ in range(6)]

    theta_flip = np.pi / 2   # upside down 50%
    theta_speed = np.pi / 2  # speed change 50%

    state = "play" if start_playing else "title"   # title -> play -> over -> title
    best = 0

    def new_game():
        return Bird(), [Pipe(FIRST_PIPE_X + i * PIPE_SPACING, allow_orb=i >= 2) for i in range(4)], 0

    bird, pipes, score = new_game()
    last_bits, effect_msg, badges = "---", "", []
    speed_mult = 1.0
    shield, ghost_timer, collapse, double_pipes = False, 0, False, 0
    held = None            # stored power-up: (bits, name, colour), used with X
    msg_timer = 0
    particles = []
    shake = 0
    flash = 0
    t = 0
    scroll = 0.0

    use_power = False
    while True:
        t += 1
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                pygame.quit()
                return
            if e.type == pygame.KEYDOWN:
                if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and state == "title":
                    bird, pipes, score = new_game()
                    last_bits, effect_msg, badges = "---", "", []
                    speed_mult = 1.0
                    shield, ghost_timer, collapse, double_pipes = False, 0, False, 0
                    held = None
                    msg_timer, flash, shake = 0, 0, 0    # clear leftovers from the last game
                    particles = []
                    state = "play"
                    bird.flap()
                elif e.key == pygame.K_SPACE and state == "play":
                    bird.flap()
                    for _ in range(5):
                        particles.append(Particle(bird.x - 15, bird.y, (230, 220, 255), 2, 20, 3))
                elif e.key == pygame.K_r and state == "over":
                    state = "title"
                elif e.key == pygame.K_x and state == "play" and held:
                    use_power = True
            if e.type == pygame.MOUSEBUTTONDOWN and state == "play":
                bird.flap()

        # ---- use the stored power-up (X key) ----
        if state == "play" and (use_power or (autoplay and held)) and held:
            pbits, pname, pcol = held
            held = None
            if pname == "SHIELD":
                shield = True
            elif pname == "GHOST":
                ghost_timer = FPS * 4
            elif pname == "COLLAPSE":
                collapse = True
            else:
                double_pipes = 5
            effect_msg, msg_timer, flash = f"{pname} ON!", 70, 8
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

        if state == "title":
            # bird bobs gently on the title screen
            bird.y = H * 0.48 + math.sin(t * 0.06) * 18
            bird.flipped = False
            bird.trail = []

        if state == "play":
            # autoplay (for testing)
            if autoplay:
                nxt = next(p for p in pipes if p.x + PIPE_W > bird.x - bird.r)
                target = nxt.gap_y + (-30 if bird.flipped else 30)
                if (not bird.flipped and bird.y > target and bird.vy > 0) or \
                   (bird.flipped and bird.y < target and bird.vy < 0):
                    bird.flap()

            bird.update()
            for p in pipes:
                p.x -= speed
                # measure only after the bird's whole body has cleared the pipe (cap included)
                if not p.passed and p.x + PIPE_W + 7 < bird.x - bird.r:
                    p.passed = True
                    score += 2 if double_pipes > 0 else 1
                    double_pipes = max(0, double_pipes - 1)
                    # passed a pipe -> quantum measurement
                    if collapse:
                        # COLLAPSE power-up: the state is forced to |000> -> no effects
                        collapse = False
                        last_bits, q = "000", [False] * 3
                    else:
                        qc = build_circuit(theta_flip, theta_speed)
                        last_bits, q = measure_once(qc)
                    bird.flipped = q[0]
                    speed_mult = (1.6 if q[2] else 0.55) if q[1] else 1.0
                    badges = []
                    if q[0]:
                        badges.append(("UPSIDE DOWN", (110, 50, 180)))
                    if q[1]:
                        badges.append(("FAST", (230, 80, 70)) if q[2] else ("SLOW", (60, 140, 230)))
                    effect_msg = " + ".join(b[0] for b in badges) if badges else "NORMAL"
                    msg_timer = 90
                    flash = 10
                    # quantum sparkle burst
                    for _ in range(30):
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
                        held = (pbits, pname, pcol)        # stored - press X to use (replaces old one)
                        effect_msg = f"GOT {pname}!  press X"
                        msg_timer = 90
                        flash = 8
                        for _ in range(35):
                            particles.append(Particle(ox, oy, random.choice([pcol, WHITE]), 7, 50, 5))

            if ghost_timer > 0:
                ghost_timer -= 1

            br = bird.rect()
            hit_edge = bird.y - bird.r < 0 or bird.y + bird.r > H - GROUND_H
            hit_pipe = ghost_timer == 0 and any(br.colliderect(r) for p in pipes for r in p.rects())
            if hit_pipe and shield:
                # shield absorbs the hit, then a short ghost window so you can escape
                shield = False
                hit_pipe = False
                ghost_timer = FPS
                shake = 8
                effect_msg, msg_timer = "SHIELD SAVED YOU!", 70
                for _ in range(30):
                    particles.append(Particle(bird.x, bird.y, (80, 200, 255), 6, 40, 5))
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

        if state != "title":
            for p in pipes:
                p.draw(frame)
            for p in pipes:
                p.draw_orb(frame, t)

        # speed lines while FAST
        if speed_mult > 1 and state == "play":
            for i in range(10):
                y = (i * 53 + t * 7) % (H - GROUND_H)
                x = W - (t * 30 + i * 131) % (W + 200)
                pygame.draw.line(frame, WHITE, (x, y), (x + 70, y), 2)

        bird.draw(frame, t, ghost=ghost_timer > 0, shield=shield)
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
        if state == "title":
            veil = pygame.Surface((W, H), pygame.SRCALPHA)
            veil.fill((20, 10, 50, 90))
            frame.blit(veil, (0, 0))
            bob = math.sin(t * 0.05) * 6
            outlined(frame, huge, "QUBIRD", (W // 2, 120 + bob), GOLD, INK, 5)
            text(frame, font, "a quantum flight", (W // 2, 190 + bob), (230, 220, 255))
            if (t // 30) % 2 == 0:
                outlined(frame, big, "PRESS ENTER", (W // 2, 360), WHITE, INK, 3)
            text(frame, small, "SPACE = flap    X = use power-up    Every pipe is a quantum measurement",
                 (W // 2, 420), WHITE)
            text(frame, small, f"Best: {best}", (W // 2, 450), GOLD)

        if state in ("play", "over"):
            outlined(frame, big, str(score), (W // 2, 45), WHITE, INK, 3)

            # active power-ups + speed level (top-left)
            active = []
            if held:
                active.append((f"[X] {held[1]}", held[2]))
            if shield:
                active.append(("SHIELD", POWERUPS["00"][1]))
            if ghost_timer > 0:
                active.append((f"GHOST {ghost_timer / FPS:.1f}s", POWERUPS["01"][1]))
            if collapse:
                active.append(("COLLAPSE next", POWERUPS["10"][1]))
            if double_pipes > 0:
                active.append((f"x2 for {double_pipes}", POWERUPS["11"][1]))
            for i, (label, col) in enumerate(active):
                w = small.size(label)[0] + 20
                border = 2 + (1 if label.startswith("[X]") and (t // 15) % 2 else 0)   # stored one blinks
                pygame.draw.rect(frame, (20, 15, 50), (14, 14 + i * 34, w, 28), border_radius=14)
                pygame.draw.rect(frame, col, (14, 14 + i * 34, w, 28), border, border_radius=14)
                frame.blit(small.render(label, True, col), (24, 18 + i * 34))
            lvl = (base_speed - START_SPEED) / (MAX_SPEED - START_SPEED)
            text(frame, small, f"SPEED {base_speed:.1f}", (W - 14 - small.size("SPEED 0.0")[0], 14), WHITE, center=False)
            pygame.draw.rect(frame, (40, 30, 80), (W - 134, 40, 120, 10), border_radius=5)
            pygame.draw.rect(frame, (255, 120, 90), (W - 134, 40, max(6, int(120 * lvl)), 10), border_radius=5)

            # active effects stay on screen until the next pipe
            bx = W // 2 - sum(font.size(b[0])[0] + 34 for b in badges) // 2
            for label, color in badges:
                w = font.size(label)[0] + 24
                pygame.draw.rect(frame, (20, 15, 50), (bx + 2, 84, w, 34), border_radius=17)
                pygame.draw.rect(frame, color, (bx, 80, w, 34), border_radius=17)
                pygame.draw.rect(frame, WHITE, (bx, 80, w, 34), 2, border_radius=17)
                frame.blit(font.render(label, True, WHITE), (bx + 12, 85))
                bx += w + 10

            # quantum info panel (bottom-right, where the bird never flies)
            px, py = W - 172, H - GROUND_H - 84
            panel = pygame.Surface((160, 72), pygame.SRCALPHA)
            pygame.draw.rect(panel, (25, 15, 60, 170), panel.get_rect(), border_radius=14)
            pygame.draw.rect(panel, (180, 150, 255, 200), panel.get_rect(), 2, border_radius=14)
            frame.blit(panel, (px, py))
            rows = [("Flip", prob_one(theta_flip)),
                    ("Speed", prob_one(theta_speed))]
            for i, (name, pval) in enumerate(rows):
                y = py + 12 + i * 28
                frame.blit(small.render(name, True, WHITE), (px + 14, y))
                pct = small.render(f"{pval:.0%}", True, GOLD)
                frame.blit(pct, (px + 146 - pct.get_width(), y))

        if msg_timer > 0 and state == "play" and effect_msg:
            msg_timer -= 1
            scale = 1 + max(0, msg_timer - 75) * 0.04      # pops in, then settles
            m = big.render(effect_msg, True, GOLD)
            fit = min(1.0, (W - 80) / m.get_width())           # long combos shrink to fit
            m = pygame.transform.rotozoom(m, 0, scale * fit)
            m.set_alpha(min(255, msg_timer * 6))
            frame.blit(m, m.get_rect(center=(W // 2, H // 2 - 70)))

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