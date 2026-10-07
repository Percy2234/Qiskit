"""
Qubird - a bird game where a quantum circuit decides the effects
Every time the bird passes a pipe, a 3-qubit circuit is measured once
  q0 = 1  -> upside down (gravity flips)
  q1 = 1  -> horizontal speed changes
  q2      -> 0 = slower, 1 = faster (50:50 via H gate)

Controls
  SPACE / click : flap
  E             : toggle entanglement mode (CX links q0 and q1)
  1 / 2         : lower / raise upside-down probability
  3 / 4         : lower / raise speed-change probability
  R             : restart after game over
"""
import math
import random
import sys

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
BASE_SPEED = 3.2
PIPE_GAP = 170
PIPE_W = 80
PIPE_SPACING = 300

SKY = (110, 200, 245)
HILL = (120, 200, 110)
GROUND = (215, 205, 150)
GRASS = (110, 190, 60)
PIPE = (90, 170, 80)
PIPE_DARK = (55, 120, 50)
BIRD = (150, 110, 230)  # original purple qubit bird
TEXT = (30, 30, 50)


# ---------------- Quantum part ----------------
def build_circuit(theta_flip, theta_slow, entangled):
    """Circuit that decides the effects. Angles set the probabilities (P(1) = sin^2(theta/2))."""
    qc = QuantumCircuit(3)
    qc.ry(theta_flip, 0)
    if entangled:
        qc.cx(0, 1)  # q1 follows q0 -> flip and speed change always happen together
    else:
        qc.ry(theta_slow, 1)
    qc.h(2)          # slower / faster 50:50
    return qc


def measure_once(qc):
    """Measure the circuit once. Qiskit bit order: rightmost character is q0."""
    counts = Statevector(qc).sample_counts(shots=1)
    bits = next(iter(counts))  # e.g. '101' (q2 q1 q0)
    q0 = bits[-1] == "1"
    q1 = bits[-2] == "1"
    q2 = bits[-3] == "1"
    return bits, q0, q1, q2


def prob_one(theta):
    return math.sin(theta / 2) ** 2


# ---------------- Game objects ----------------
class Bird:
    def __init__(self):
        self.x = W * 0.28
        self.y = H * 0.45
        self.vy = 0.0
        self.r = 18
        self.flipped = False

    def flap(self):
        self.vy = -FLAP if self.flipped else FLAP

    def update(self):
        g = -GRAVITY if self.flipped else GRAVITY
        self.vy += g
        self.vy = max(-11, min(11, self.vy))
        self.y += self.vy

    def rect(self):
        return pygame.Rect(self.x - self.r + 3, self.y - self.r + 3, 2 * self.r - 6, 2 * self.r - 6)

    def draw(self, surf, t):
        body = pygame.Surface((80, 80), pygame.SRCALPHA)
        cx, cy = 40, 40
        pygame.draw.circle(body, BIRD, (cx, cy), self.r)
        pygame.draw.circle(body, (120, 85, 200), (cx, cy), self.r, 3)
        # wing (flapping)
        flap = math.sin(t * 0.35) * 6
        pygame.draw.ellipse(body, (200, 180, 255), (cx - 16, cy - 2 + flap, 18, 11))
        # eye
        pygame.draw.circle(body, (255, 255, 255), (cx + 8, cy - 6), 7)
        pygame.draw.circle(body, (20, 20, 40), (cx + 10, cy - 6), 3)
        # beak
        pygame.draw.polygon(body, (255, 170, 40), [(cx + 15, cy), (cx + 28, cy + 3), (cx + 15, cy + 7)])
        # |psi> antenna on its head
        pygame.draw.line(body, (120, 85, 200), (cx, cy - self.r), (cx + 4, cy - self.r - 9), 3)
        pygame.draw.circle(body, (255, 220, 80), (cx + 4, cy - self.r - 10), 4)

        angle = max(-30, min(60, self.vy * 4 * (-1 if self.flipped else 1)))
        body = pygame.transform.rotate(body, -angle)
        if self.flipped:
            body = pygame.transform.flip(body, False, True)
        surf.blit(body, body.get_rect(center=(self.x, self.y)))


class Pipe:
    def __init__(self, x):
        self.x = x
        self.gap_y = random.randint(130, H - GROUND_H - 130)
        self.passed = False

    def rects(self):
        top = pygame.Rect(self.x, 0, PIPE_W, self.gap_y - PIPE_GAP // 2)
        bot_y = self.gap_y + PIPE_GAP // 2
        bot = pygame.Rect(self.x, bot_y, PIPE_W, H - GROUND_H - bot_y)
        return top, bot

    def draw(self, surf):
        for r in self.rects():
            pygame.draw.rect(surf, PIPE, r)
            pygame.draw.rect(surf, PIPE_DARK, r, 3)
            cap = pygame.Rect(r.x - 6, r.bottom - 26 if r.y == 0 else r.y, PIPE_W + 12, 26)
            pygame.draw.rect(surf, PIPE, cap)
            pygame.draw.rect(surf, PIPE_DARK, cap, 3)


# ---------------- Main ----------------
def main(max_frames=None, screenshot=None, autoplay=False):
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Qubird - Quantum Flight")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("arial", 22, bold=True)
    big = pygame.font.SysFont("arial", 52, bold=True)

    theta_flip = np.pi / 3   # upside down 25%
    theta_slow = np.pi / 2   # speed change 50%
    entangled = False

    def reset():
        return Bird(), [Pipe(W + 200 + i * PIPE_SPACING) for i in range(4)], 0, False, "---", ""

    bird, pipes, score, dead, last_bits, effect_msg = reset()
    speed_mult = 1.0
    msg_timer = 0
    t = 0
    ground_x = 0

    while True:
        t += 1
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                pygame.quit()
                return
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_SPACE and not dead:
                    bird.flap()
                elif e.key == pygame.K_r and dead:
                    bird, pipes, score, dead, last_bits, effect_msg = reset()
                    speed_mult = 1.0
                elif e.key == pygame.K_e:
                    entangled = not entangled
                elif e.key == pygame.K_1:
                    theta_flip = max(0, theta_flip - np.pi / 12)
                elif e.key == pygame.K_2:
                    theta_flip = min(np.pi, theta_flip + np.pi / 12)
                elif e.key == pygame.K_3:
                    theta_slow = max(0, theta_slow - np.pi / 12)
                elif e.key == pygame.K_4:
                    theta_slow = min(np.pi, theta_slow + np.pi / 12)
            if e.type == pygame.MOUSEBUTTONDOWN and not dead:
                bird.flap()

        speed = BASE_SPEED * speed_mult

        if not dead:
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
                if not p.passed and p.x + PIPE_W < bird.x:
                    p.passed = True
                    score += 1
                    # passed a pipe -> quantum measurement
                    qc = build_circuit(theta_flip, theta_slow, entangled)
                    last_bits, q0, q1, q2 = measure_once(qc)
                    bird.flipped = q0
                    speed_mult = (1.6 if q2 else 0.55) if q1 else 1.0
                    parts = []
                    if q0:
                        parts.append("UPSIDE DOWN!")
                    if q1:
                        parts.append("FAST!" if q2 else "SLOW!")
                    effect_msg = " + ".join(parts) if parts else "NORMAL"
                    msg_timer = 90
            if pipes[0].x < -PIPE_W - 20:
                pipes.pop(0)
                pipes.append(Pipe(pipes[-1].x + PIPE_SPACING))

            br = bird.rect()
            if bird.y - bird.r < 0 or bird.y + bird.r > H - GROUND_H:
                dead = True
            for p in pipes:
                if any(br.colliderect(r) for r in p.rects()):
                    dead = True
            ground_x = (ground_x - speed) % 40

        # ---- Drawing ----
        screen.fill(SKY)
        for i, (cx, cy) in enumerate([(150, 120), (520, 80), (820, 150)]):
            for dx, dy, r in [(0, 0, 30), (30, -10, 36), (65, 0, 28)]:
                pygame.draw.circle(screen, (255, 255, 255), (cx + dx, cy + dy), r)
        pygame.draw.ellipse(screen, HILL, (-100, H - GROUND_H - 120, 600, 260))
        pygame.draw.ellipse(screen, (100, 185, 95), (400, H - GROUND_H - 90, 700, 220))

        for p in pipes:
            p.draw(screen)
        bird.draw(screen, t)

        pygame.draw.rect(screen, GROUND, (0, H - GROUND_H, W, GROUND_H))
        pygame.draw.rect(screen, GRASS, (0, H - GROUND_H, W, 16))
        for x in range(-40, W + 40, 40):
            pygame.draw.rect(screen, (90, 165, 45), (x + ground_x, H - GROUND_H, 20, 16))

        # HUD
        s = big.render(str(score), True, (255, 255, 255))
        screen.blit(s, s.get_rect(center=(W // 2, 45)))

        panel = pygame.Surface((330, 130), pygame.SRCALPHA)
        panel.fill((255, 255, 255, 190))
        screen.blit(panel, (10, 10))
        lines = [
            f"Measured: |{last_bits}>  speed x{speed_mult}",
            f"Flip   P={prob_one(theta_flip):.0%}  [1/2]",
            f"Speed  P={prob_one(theta_flip if entangled else theta_slow):.0%}  [3/4]",
            f"Entangle(CX): {'ON' if entangled else 'OFF'}  [E]",
        ]
        for i, line in enumerate(lines):
            screen.blit(font.render(line, True, TEXT), (20, 18 + i * 28))

        if msg_timer > 0:
            msg_timer -= 1
            m = big.render(effect_msg, True, (255, 230, 80))
            screen.blit(m, m.get_rect(center=(W // 2, H // 2 - 120)))

        if dead:
            o = big.render("GAME OVER  -  R", True, (255, 255, 255))
            screen.blit(o, o.get_rect(center=(W // 2, H // 2)))

        pygame.display.flip()
        clock.tick(FPS if not max_frames else 0)

        if max_frames and t >= max_frames:
            if screenshot:
                pygame.image.save(screen, screenshot)
            pygame.quit()
            return score


if __name__ == "__main__":
    main()
