"""
Qubit Mines - a 2D block world where quantum circuits decide what's hidden underground
Made by Team Jordan (Daniel, Percy) for Qiskit Fall Fest 2026.

Quantum ideas in the game
  World seed      : 16 qubits each put through an H gate, measured once.
                    Every world is a genuinely random quantum world.
  Quantum blocks  : purple |?> blocks sit in SUPERPOSITION. Mining one is a
                    MEASUREMENT of a 2-qubit circuit, which collapses it into an ore:
                      q0 = RY(theta)  P(1) = 0.40
                      q1 = RY(theta)  P(1) = 0.30
                      |q1 q0> = 00 -> COAL, 01 -> IRON, 10 -> GOLD, 11 -> DIAMOND
  Entangled pairs : some quantum blocks are linked by a glowing line. Their circuit
                    uses CX gates to copy q0, q1 onto q2, q3, so they are ENTANGLED.
                    Mine one and its partner collapses into the SAME ore instantly.

Controls
  ENTER           : start game (title screen)
  H               : how the quantum works (title screen)
  A / D           : move left / right
  W / SPACE       : jump
  Left mouse      : hold to mine
  Right mouse     : place selected block
  1-9 / wheel     : choose hotbar slot
  C               : craft 1 wood -> 4 planks
  ESC             : back to title
"""
import math
import random

import pygame
from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector

# ---------------- Settings ----------------
W, H = 960, 540
FPS = 60
T = 32                     # tile size in pixels
WORLD_W, WORLD_H = 220, 64 # world size in tiles
GRAVITY = 0.55
JUMP = -10.5
MOVE = 4.2
MAX_FALL = 14
REACH = 5.5                # mining / placing reach in tiles

P_Q0 = 0.40                # P(q0 = 1)
P_Q1 = 0.30                # P(q1 = 1)

# colours
SKY_TOP, SKY_BOT = (80, 165, 245), (200, 235, 255)
WHITE = (255, 255, 255)
INK = (30, 25, 60)
GOLD_TXT = (255, 215, 70)
QPURPLE = (160, 100, 255)
QGLOW = (220, 180, 255)

# ---------------- Blocks ----------------
(AIR, GRASS, DIRT, STONE, WOOD, LEAF, COAL, IRON, GOLD,
 DIAMOND, QBLOCK, BEDROCK, PLANK) = range(13)

# id: (name, base colour, frames to mine)  hardness None = unbreakable
BLOCKS = {
    GRASS:   ("Grass",   (110, 80, 50),   14),
    DIRT:    ("Dirt",    (125, 88, 55),   14),
    STONE:   ("Stone",   (125, 125, 130), 36),
    WOOD:    ("Wood",    (120, 85, 45),   28),
    LEAF:    ("Leaves",  (60, 150, 60),   6),
    COAL:    ("Coal",    (125, 125, 130), 40),
    IRON:    ("Iron",    (125, 125, 130), 48),
    GOLD:    ("Gold",    (125, 125, 130), 48),
    DIAMOND: ("Diamond", (125, 125, 130), 60),
    QBLOCK:  ("Quantum", (90, 50, 170),   30),
    BEDROCK: ("Bedrock", (45, 45, 50),    None),
    PLANK:   ("Planks",  (190, 145, 85),  22),
}
ORE_DOTS = {COAL: (30, 30, 30), IRON: (220, 175, 140), GOLD: (250, 210, 60),
            DIAMOND: (90, 235, 230)}
POINTS = {COAL: 5, IRON: 10, GOLD: 20, DIAMOND: 50}
HOTBAR = [DIRT, STONE, WOOD, PLANK, LEAF, COAL, IRON, GOLD, DIAMOND]


# ---------------- Quantum part ----------------
def theta_for(p):
    """RY angle that gives P(1) = p, since P(1) = sin^2(theta/2)."""
    return 2 * math.asin(math.sqrt(p))


def measure_once(qc):
    """Measure the circuit once. Qiskit bit order: rightmost character is q0."""
    bits = next(iter(Statevector(qc).sample_counts(shots=1)))
    q = [bits[-1 - i] == "1" for i in range(len(bits))]  # q[0] = q0, q[1] = q1, ...
    return bits, q


def quantum_seed(n=16):
    """n qubits in superposition (H gates), measured once -> a truly random world seed."""
    qc = QuantumCircuit(n)
    qc.h(range(n))
    bits, _ = measure_once(qc)
    return int(bits, 2), bits


def ore_circuit():
    """One quantum block in superposition over 4 ores."""
    qc = QuantumCircuit(2)
    qc.ry(theta_for(P_Q0), 0)
    qc.ry(theta_for(P_Q1), 1)
    return qc


def pair_circuit():
    """Two entangled quantum blocks: CX copies q0 -> q2 and q1 -> q3."""
    qc = QuantumCircuit(4)
    qc.ry(theta_for(P_Q0), 0)
    qc.ry(theta_for(P_Q1), 1)
    qc.cx(0, 2)
    qc.cx(1, 3)
    return qc


def ore_from(q0, q1):
    return {(0, 0): COAL, (1, 0): IRON, (0, 1): GOLD, (1, 1): DIAMOND}[(int(q0), int(q1))]


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
    img = font.render(msg, True, color)
    r = img.get_rect(center=pos) if center else img.get_rect(topleft=pos)
    if shadow:
        sh = font.render(msg, True, (0, 0, 0))
        sh.set_alpha(120)
        surf.blit(sh, r.move(2, 2))
    surf.blit(img, r)
    return r


def shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)


def make_block_images():
    """Pixel-style textures drawn once at startup (all original art)."""
    imgs = {}
    for bid, (_, base, _) in BLOCKS.items():
        s = pygame.Surface((T, T))
        s.fill(base)
        rng = random.Random(bid * 97)
        px = 4
        for gx in range(0, T, px):
            for gy in range(0, T, px):
                k = rng.uniform(0.85, 1.12)
                pygame.draw.rect(s, shade(base, k), (gx, gy, px, px))
        if bid == GRASS:
            pygame.draw.rect(s, (90, 185, 70), (0, 0, T, 9))
            for gx in range(0, T, px):
                if rng.random() < 0.6:
                    pygame.draw.rect(s, (70, 160, 55), (gx, 8, px, px))
        elif bid == WOOD:
            for gx in (6, 15, 24):
                pygame.draw.line(s, shade(base, 0.7), (gx, 0), (gx, T), 2)
        elif bid == PLANK:
            for gy in (0, 16):
                pygame.draw.line(s, shade(base, 0.65), (0, gy), (T, gy), 2)
            pygame.draw.line(s, shade(base, 0.65), (12, 0), (12, 16), 2)
            pygame.draw.line(s, shade(base, 0.65), (24, 16), (24, T), 2)
        elif bid == LEAF:
            for _ in range(10):
                pygame.draw.rect(s, (40, 115, 45), (rng.randrange(0, T, px), rng.randrange(0, T, px), px, px))
        elif bid in ORE_DOTS:
            for _ in range(6):
                x, y = rng.randrange(4, T - 8, px), rng.randrange(4, T - 8, px)
                pygame.draw.rect(s, ORE_DOTS[bid], (x, y, 6, 6))
                pygame.draw.rect(s, shade(ORE_DOTS[bid], 0.7), (x + 4, y + 4, 2, 2))
        elif bid == QBLOCK:
            pygame.draw.rect(s, QPURPLE, (3, 3, T - 6, T - 6), 2)
        pygame.draw.rect(s, shade(base, 0.6), (0, 0, T, T), 1)
        imgs[bid] = s
    return imgs


# ---------------- World ----------------
class World:
    def __init__(self, seed):
        rng = random.Random(seed)
        self.g = [[AIR] * WORLD_H for _ in range(WORLD_W)]   # g[x][y]
        self.partner = {}                                     # (x, y) -> (x2, y2)
        self.surface = [0] * WORLD_W
        p1, p2, p3 = (rng.uniform(0, 6.28) for _ in range(3))

        for x in range(WORLD_W):
            h = int(20 + 4 * math.sin(x * 0.045 + p1) + 2.5 * math.sin(x * 0.12 + p2)
                    + 1.2 * math.sin(x * 0.29 + p3))
            self.surface[x] = h
            for y in range(h, WORLD_H):
                d = y - h
                if y >= WORLD_H - 1 or (y >= WORLD_H - 3 and rng.random() < 0.5):
                    b = BEDROCK
                elif d == 0:
                    b = GRASS
                elif d <= 3:
                    b = DIRT
                else:
                    b = STONE
                    r = rng.random()
                    if d > 5 and r < 0.025:
                        b = COAL
                    elif d > 12 and r < 0.04:
                        b = IRON
                    elif d > 22 and r < 0.048:
                        b = GOLD
                    elif d > 32 and r < 0.053:
                        b = DIAMOND
                self.g[x][y] = b

        # caves: a few random-walk tunnels
        for _ in range(14):
            cx, cy = rng.randrange(WORLD_W), rng.randrange(30, WORLD_H - 6)
            for _ in range(rng.randint(40, 110)):
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        x, y = cx + dx, cy + dy
                        if 0 <= x < WORLD_W and y > self.surface[x] + 6 and self.g[x][y] != BEDROCK:
                            self.g[x][y] = AIR
                cx = max(1, min(WORLD_W - 2, cx + rng.choice((-1, 1, 1, 0))))
                cy = max(28, min(WORLD_H - 5, cy + rng.choice((-1, 0, 1))))

        # trees
        x = 4
        while x < WORLD_W - 4:
            if rng.random() < 0.18 and abs(x - WORLD_W // 2) > 2:
                top = self.surface[x]
                trunk = rng.randint(4, 6)
                for i in range(1, trunk + 1):
                    self.g[x][top - i] = WOOD
                for lx in range(-2, 3):
                    for ly in range(-2, 2):
                        if abs(lx) + abs(ly) < 4:
                            tx, ty = x + lx, top - trunk + ly
                            if self.g[tx][ty] == AIR:
                                self.g[tx][ty] = LEAF
                x += rng.randint(5, 9)
            x += 1

        # quantum blocks (some come as entangled pairs)
        for x in range(WORLD_W):
            for y in range(self.surface[x] + 5, WORLD_H - 3):
                if self.g[x][y] == STONE and rng.random() < 0.012:
                    self.g[x][y] = QBLOCK
                    if rng.random() < 0.4:
                        x2, y2 = x + rng.randint(3, 7), y + rng.randint(-2, 2)
                        if 0 <= x2 < WORLD_W and self.g[x2][y2] == STONE and y2 > self.surface[x2] + 4:
                            self.g[x2][y2] = QBLOCK
                            self.partner[(x, y)] = (x2, y2)
                            self.partner[(x2, y2)] = (x, y)

    def get(self, x, y):
        if y < 0:
            return AIR
        if x < 0 or x >= WORLD_W or y >= WORLD_H:
            return BEDROCK
        return self.g[x][y]

    def set(self, x, y, b):
        if 0 <= x < WORLD_W and 0 <= y < WORLD_H:
            self.g[x][y] = b

    def solid(self, x, y):
        return self.get(x, y) != AIR


# ---------------- Player ----------------
class Player:
    def __init__(self, x, y):
        self.rect = pygame.Rect(x, y, 22, 58)
        self.vx = 0.0
        self.vy = 0.0
        self.on_ground = False
        self.facing = 1

    def collide(self, world, axis):
        r = self.rect
        for tx in range(r.left // T, (r.right - 1) // T + 1):
            for ty in range(r.top // T, (r.bottom - 1) // T + 1):
                if not world.solid(tx, ty):
                    continue
                tile = pygame.Rect(tx * T, ty * T, T, T)
                if not r.colliderect(tile):
                    continue
                if axis == "x":
                    if self.vx > 0:
                        r.right = tile.left
                    elif self.vx < 0:
                        r.left = tile.right
                    self.vx = 0
                else:
                    if self.vy > 0:
                        r.bottom = tile.top
                        self.on_ground = True
                    elif self.vy < 0:
                        r.top = tile.bottom
                    self.vy = 0

    def update(self, world, keys):
        self.vx = 0
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            self.vx = -MOVE
            self.facing = -1
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            self.vx = MOVE
            self.facing = 1
        if (keys[pygame.K_w] or keys[pygame.K_SPACE] or keys[pygame.K_UP]) and self.on_ground:
            self.vy = JUMP
        self.vy = min(self.vy + GRAVITY, MAX_FALL)

        self.rect.x += round(self.vx)
        self.collide(world, "x")
        self.on_ground = False
        self.rect.y += round(self.vy)
        self.collide(world, "y")

    def draw(self, surf, cam):
        r = self.rect.move(-cam[0], -cam[1])
        # original "qubit miner": purple suit, gold helmet lamp
        pygame.draw.rect(surf, (90, 60, 170), (r.x, r.y + 22, r.w, 22), border_radius=4)   # body
        pygame.draw.rect(surf, (60, 45, 110), (r.x + 2, r.y + 44, 8, 14))                  # legs
        pygame.draw.rect(surf, (60, 45, 110), (r.x + 12, r.y + 44, 8, 14))
        pygame.draw.rect(surf, (240, 200, 160), (r.x + 1, r.y + 4, r.w - 2, 18), border_radius=4)  # face
        pygame.draw.rect(surf, (250, 200, 50), (r.x - 1, r.y, r.w + 2, 8), border_radius=3)        # helmet
        ex = r.centerx + 4 * self.facing
        pygame.draw.rect(surf, INK, (ex - 1, r.y + 11, 3, 4))
        pygame.draw.circle(surf, (255, 250, 200), (r.centerx + 8 * self.facing, r.y + 4), 3)       # lamp


# ---------------- Game ----------------
class Game:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Qubit Mines - Team Jordan")
        self.screen = pygame.display.set_mode((W, H))
        self.clock = pygame.time.Clock()
        self.f_big = pygame.font.Font(None, 96)
        self.f_mid = pygame.font.Font(None, 44)
        self.f_sm = pygame.font.Font(None, 28)
        self.f_xs = pygame.font.Font(None, 22)
        self.sky = gradient(SKY_TOP, SKY_BOT)
        self.imgs = make_block_images()
        self.state = "intro"
        self.t = 0
        self.new_game()

    # ----- setup -----
    def new_game(self):
        self.seed, self.seed_bits = quantum_seed()
        self.world = World(self.seed)
        sx = WORLD_W // 2
        self.player = Player(sx * T + 5, (self.world.surface[sx] - 2) * T)
        self.inv = {b: 0 for b in HOTBAR}
        self.slot = 0
        self.score = 0
        self.measured = 0
        self.last_measure = None       # (bits, ore, entangled)
        self.mine_target = None
        self.mine_progress = 0
        self.particles = []
        self.messages = []             # cleared every new game (avoids stale timers)
        self.cam = [0.0, 0.0]
        self.say(f"Quantum world seed |{self.seed_bits}>", QGLOW)

    def say(self, msg, color=WHITE, frames=180):
        self.messages.append([msg, color, frames])
        self.messages = self.messages[-4:]

    def burst(self, tx, ty, color, n=14):
        cx, cy = tx * T + T / 2, ty * T + T / 2
        for _ in range(n):
            a = random.uniform(0, 6.28)
            s = random.uniform(1, 4)
            self.particles.append([cx, cy, math.cos(a) * s, math.sin(a) * s - 2, 40, color])

    # ----- actions -----
    def mouse_tile(self):
        mx, my = pygame.mouse.get_pos()
        return int((mx + self.cam[0]) // T), int((my + self.cam[1]) // T)

    def in_reach(self, tx, ty):
        pc = self.player.rect.center
        return math.hypot(tx * T + T / 2 - pc[0], ty * T + T / 2 - pc[1]) <= REACH * T

    def collect(self, b):
        if b in (GRASS,):
            b = DIRT
        if b in self.inv:
            self.inv[b] += 1
        if b in POINTS:
            self.score += POINTS[b]

    def break_block(self, tx, ty):
        w = self.world
        b = w.get(tx, ty)
        if b == QBLOCK:
            self.measured += 1
            partner = w.partner.pop((tx, ty), None)
            if partner:
                w.partner.pop(partner, None)
                bits, q = measure_once(pair_circuit())
                ore = ore_from(q[0], q[1])
                ore2 = ore_from(q[2], q[3])          # always equal - they are entangled
                w.set(*partner, ore2)
                self.burst(*partner, QGLOW, 20)
                self.last_measure = (bits, ore, True)
                self.say(f"ENTANGLED!  |{bits}>  both blocks -> {BLOCKS[ore][0].upper()}", QGLOW, 240)
            else:
                bits, q = measure_once(ore_circuit())
                ore = ore_from(q[0], q[1])
                self.last_measure = (bits, ore, False)
                self.say(f"Measured |{bits}>  ->  {BLOCKS[ore][0].upper()}", ORE_DOTS[ore])
            self.collect(ore)
            self.burst(tx, ty, QPURPLE, 22)
        else:
            self.collect(b)
            self.burst(tx, ty, BLOCKS[b][1], 10)
        w.set(tx, ty, AIR)

    def handle_mouse(self):
        buttons = pygame.mouse.get_pressed()
        tx, ty = self.mouse_tile()
        if buttons[0]:
            b = self.world.get(tx, ty)
            hard = BLOCKS.get(b, (None, None, None))[2]
            if b != AIR and hard and self.in_reach(tx, ty):
                if self.mine_target != (tx, ty):
                    self.mine_target, self.mine_progress = (tx, ty), 0
                self.mine_progress += 1
                if self.mine_progress >= hard:
                    self.break_block(tx, ty)
                    self.mine_target, self.mine_progress = None, 0
            else:
                self.mine_target, self.mine_progress = None, 0
        else:
            self.mine_target, self.mine_progress = None, 0

    def place_block(self):
        tx, ty = self.mouse_tile()
        item = HOTBAR[self.slot]
        if self.inv[item] <= 0 or not self.in_reach(tx, ty):
            return
        if self.world.get(tx, ty) != AIR or not (0 <= tx < WORLD_W and 0 <= ty < WORLD_H):
            return
        if pygame.Rect(tx * T, ty * T, T, T).colliderect(self.player.rect):
            return
        neighbours = [(tx + 1, ty), (tx - 1, ty), (tx, ty + 1), (tx, ty - 1)]
        if not any(self.world.solid(*n) for n in neighbours):
            return
        self.world.set(tx, ty, item)
        self.inv[item] -= 1

    def craft(self):
        if self.inv[WOOD] > 0:
            self.inv[WOOD] -= 1
            self.inv[PLANK] += 4
            self.say("Crafted 4 planks", (240, 200, 140), 90)
        else:
            self.say("Need wood to craft planks", (255, 160, 160), 90)

    # ----- update -----
    def update_play(self):
        keys = pygame.key.get_pressed()
        self.player.update(self.world, keys)
        self.handle_mouse()

        # camera follows the player smoothly, clamped to the world
        tx = self.player.rect.centerx - W / 2
        ty = self.player.rect.centery - H / 2
        self.cam[0] += (tx - self.cam[0]) * 0.15
        self.cam[1] += (ty - self.cam[1]) * 0.15
        self.cam[0] = max(0, min(WORLD_W * T - W, self.cam[0]))
        self.cam[1] = max(-4 * T, min(WORLD_H * T - H, self.cam[1]))

        for p in self.particles:
            p[0] += p[2]
            p[1] += p[3]
            p[3] += 0.25
            p[4] -= 1
        self.particles = [p for p in self.particles if p[4] > 0]
        for m in self.messages:
            m[2] -= 1
        self.messages = [m for m in self.messages if m[2] > 0]

    # ----- drawing -----
    def draw_world(self):
        s = self.screen
        cam = (int(self.cam[0]), int(self.cam[1]))
        s.blit(self.sky, (0, 0))
        # darken the sky the deeper you go
        depth = max(0, min(1, (self.cam[1] / T - 10) / 25))
        if depth > 0:
            dark = pygame.Surface((W, H))
            dark.fill((10, 8, 25))
            dark.set_alpha(int(200 * depth))
            s.blit(dark, (0, 0))
        # clouds
        for i in range(6):
            cx = (i * 260 - cam[0] * 0.3) % (W + 300) - 150
            cy = 60 + (i * 37) % 90 - cam[1] * 0.2
            for dx, r in ((0, 26), (28, 32), (60, 24)):
                pygame.draw.circle(s, (250, 252, 255), (int(cx + dx), int(cy)), r)

        x0, y0 = cam[0] // T, cam[1] // T
        pulse = (math.sin(self.t * 0.08) + 1) / 2
        for tx in range(x0, x0 + W // T + 2):
            for ty in range(y0, y0 + H // T + 2):
                b = self.world.get(tx, ty)
                if b == AIR or (tx < 0 or tx >= WORLD_W):
                    continue
                pos = (tx * T - cam[0], ty * T - cam[1])
                s.blit(self.imgs[b], pos)
                if b == QBLOCK:
                    glow = pygame.Surface((T, T), pygame.SRCALPHA)
                    glow.fill((200, 150, 255, int(60 + 90 * pulse)))
                    s.blit(glow, pos)
                    text(s, self.f_xs, "|?>", (pos[0] + T // 2, pos[1] + T // 2), WHITE, shadow=False)

        # entanglement links
        drawn = set()
        for a, bpos in self.world.partner.items():
            if (bpos, a) in drawn:
                continue
            drawn.add((a, bpos))
            p1 = (a[0] * T + T // 2 - cam[0], a[1] * T + T // 2 - cam[1])
            p2 = (bpos[0] * T + T // 2 - cam[0], bpos[1] * T + T // 2 - cam[1])
            if -T < p1[0] < W + T or -T < p2[0] < W + T:
                c = shade(QGLOW, 0.7 + 0.3 * pulse)
                n = 12
                for i in range(0, n, 2):
                    q1 = (p1[0] + (p2[0] - p1[0]) * i / n, p1[1] + (p2[1] - p1[1]) * i / n)
                    q2 = (p1[0] + (p2[0] - p1[0]) * (i + 1) / n, p1[1] + (p2[1] - p1[1]) * (i + 1) / n)
                    pygame.draw.line(s, c, q1, q2, 3)

        # mining crack + target outline
        tx, ty = self.mouse_tile()
        if self.in_reach(tx, ty):
            pygame.draw.rect(s, WHITE, (tx * T - cam[0], ty * T - cam[1], T, T), 2)
        if self.mine_target:
            mx, my = self.mine_target
            hard = BLOCKS[self.world.get(mx, my)][2] or 1
            k = self.mine_progress / hard
            ox, oy = mx * T - cam[0], my * T - cam[1]
            crack = pygame.Surface((T, T), pygame.SRCALPHA)
            crack.fill((0, 0, 0, int(150 * k)))
            s.blit(crack, (ox, oy))
            pygame.draw.rect(s, GOLD_TXT, (ox + 2, oy + T - 6, int((T - 4) * k), 4))

        self.player.draw(s, cam)
        for p in self.particles:
            pygame.draw.rect(s, p[5], (p[0] - cam[0], p[1] - cam[1], 5, 5))

    def draw_hud(self):
        s = self.screen
        # hotbar
        bw = 52
        x0 = W // 2 - len(HOTBAR) * bw // 2
        y0 = H - bw - 10
        for i, b in enumerate(HOTBAR):
            r = pygame.Rect(x0 + i * bw, y0, bw - 4, bw - 4)
            panel = pygame.Surface(r.size, pygame.SRCALPHA)
            panel.fill((20, 15, 40, 170))
            s.blit(panel, r)
            s.blit(pygame.transform.scale(self.imgs[b], (30, 30)), (r.x + 9, r.y + 6))
            text(s, self.f_xs, str(self.inv[b]), (r.right - 6, r.bottom - 8), WHITE)
            text(s, self.f_xs, str(i + 1), (r.x + 7, r.y + 7), (200, 200, 220), shadow=False)
            pygame.draw.rect(s, GOLD_TXT if i == self.slot else (90, 80, 120), r, 3 if i == self.slot else 1,
                             border_radius=4)
        text(s, self.f_sm, BLOCKS[HOTBAR[self.slot]][0], (W // 2, y0 - 14))

        # score + quantum panel
        panel = pygame.Surface((300, 92), pygame.SRCALPHA)
        panel.fill((20, 15, 40, 170))
        s.blit(panel, (W - 310, 10))
        text(s, self.f_sm, f"Score: {self.score}", (W - 298, 18), GOLD_TXT, center=False)
        text(s, self.f_xs, f"Quantum blocks measured: {self.measured}", (W - 298, 46), QGLOW, center=False)
        if self.last_measure:
            bits, ore, ent = self.last_measure
            tag = "  (entangled)" if ent else ""
            text(s, self.f_xs, f"Last: |{bits}> -> {BLOCKS[ore][0]}{tag}", (W - 298, 70),
                 ORE_DOTS[ore], center=False)
        else:
            text(s, self.f_xs, "Mine a |?> block to measure it!", (W - 298, 70), WHITE, center=False)

        # messages
        for i, (msg, color, _) in enumerate(self.messages):
            text(s, self.f_sm, msg, (16, 16 + i * 28), color, center=False)
        text(s, self.f_xs, "ESC: title   C: craft planks", (16, H - 24), (220, 220, 235), center=False)

    def draw_intro(self):
        s = self.screen
        s.fill((12, 8, 30))
        a = min(255, self.t * 5)
        for i in range(40):
            x = (i * 137) % W
            y = (i * 71 + self.t) % H
            pygame.draw.circle(s, (80, 60, 150), (x, y), 2)
        img = self.f_mid.render("TEAM JORDAN", True, GOLD_TXT)
        img.set_alpha(a)
        s.blit(img, img.get_rect(center=(W // 2, H // 2 - 30)))
        img = self.f_sm.render("presents", True, WHITE)
        img.set_alpha(a)
        s.blit(img, img.get_rect(center=(W // 2, H // 2 + 10)))
        img = self.f_xs.render("Daniel  ·  Percy", True, QGLOW)
        img.set_alpha(a)
        s.blit(img, img.get_rect(center=(W // 2, H // 2 + 50)))

    def draw_title(self):
        s = self.screen
        s.blit(self.sky, (0, 0))
        # decorative ground strip
        for i in range(W // T + 1):
            h = 4 + int(1.5 * math.sin(i * 0.5))
            for j in range(h):
                b = GRASS if j == h - 1 else (DIRT if j > h - 4 else STONE)
                if b == STONE and (i * 7 + j * 3) % 11 == 0:
                    b = QBLOCK
                s.blit(self.imgs[b], (i * T, H - (j + 1) * T))
        bob = math.sin(self.t * 0.05) * 6
        text(s, self.f_big, "QUBIT MINES", (W // 2, 120 + bob), WHITE)
        text(s, self.f_sm, "dig into a world built from quantum randomness", (W // 2, 178), INK, shadow=False)
        lines = ["ENTER - start      H - how the quantum works",
                 "A/D move   W/SPACE jump   hold LEFT CLICK mine   RIGHT CLICK place",
                 "1-9 / wheel pick block   C craft planks"]
        for i, ln in enumerate(lines):
            text(s, self.f_sm if i == 0 else self.f_xs, ln, (W // 2, 240 + i * 34),
                 GOLD_TXT if i == 0 else WHITE)

    def draw_howto(self):
        s = self.screen
        s.fill((18, 12, 40))
        text(s, self.f_mid, "How the Quantum Works", (W // 2, 50), GOLD_TXT)
        sections = [
            ("1. Quantum world seed", QGLOW,
             ["16 qubits each go through a Hadamard (H) gate -> equal superposition of 0 and 1.",
              "Measuring them gives a 16-bit number that builds the terrain. Every world is unique."]),
            ("2. Superposition blocks  |?>", QPURPLE,
             ["Each purple block is a 2-qubit circuit:  q0 = RY (40% chance of 1),  q1 = RY (30%).",
              "Until you mine it, it is ALL ores at once: coal, iron, gold and diamond."]),
            ("3. Mining = Measurement", ORE_DOTS[GOLD],
             ["Breaking the block measures the circuit. The superposition collapses to one result:",
              "|00> coal    |01> iron    |10> gold    |11> diamond  (rarest: 0.4 x 0.3 = 12%)"]),
            ("4. Entangled pairs", ORE_DOTS[DIAMOND],
             ["Linked blocks share one 4-qubit circuit. CX gates copy q0 -> q2 and q1 -> q3.",
              "Mine one and its partner instantly collapses into the SAME ore - that's entanglement!"]),
        ]
        y = 100
        for title, col, body in sections:
            text(s, self.f_sm, title, (70, y), col, center=False)
            for j, ln in enumerate(body):
                text(s, self.f_xs, ln, (90, y + 30 + j * 22), WHITE, center=False, shadow=False)
            y += 100
        text(s, self.f_xs, "ENTER / ESC - back", (W // 2, H - 22), (200, 200, 220))

    # ----- main loop -----
    def run(self):
        running = True
        while running:
            self.t += 1
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    running = False
                elif e.type == pygame.KEYDOWN:
                    if self.state == "intro":
                        self.state = "title"
                    elif self.state == "title":
                        if e.key == pygame.K_RETURN:
                            self.new_game()
                            self.state = "play"
                        elif e.key == pygame.K_h:
                            self.state = "howto"
                        elif e.key == pygame.K_ESCAPE:
                            running = False
                    elif self.state == "howto":
                        if e.key in (pygame.K_RETURN, pygame.K_ESCAPE, pygame.K_h):
                            self.state = "title"
                    elif self.state == "play":
                        if e.key == pygame.K_ESCAPE:
                            self.state = "title"
                        elif e.key == pygame.K_c:
                            self.craft()
                        elif pygame.K_1 <= e.key <= pygame.K_9:
                            self.slot = e.key - pygame.K_1
                elif e.type == pygame.MOUSEBUTTONDOWN and self.state == "play":
                    if e.button == 3:
                        self.place_block()
                elif e.type == pygame.MOUSEWHEEL and self.state == "play":
                    self.slot = (self.slot - e.y) % len(HOTBAR)

            if self.state == "intro":
                self.draw_intro()
                if self.t > 170:
                    self.state = "title"
            elif self.state == "title":
                self.draw_title()
            elif self.state == "howto":
                self.draw_howto()
            else:
                self.update_play()
                self.draw_world()
                self.draw_hud()

            pygame.display.flip()
            self.clock.tick(FPS)
        pygame.quit()


if __name__ == "__main__":
    Game().run()