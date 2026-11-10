#!/usr/bin/env python3
"""Build 07: Visual Graphics in Pure Intent — Mandelbrot Fractal & 3D Sphere Raycaster.

Compiles `graphics_engine.intent` to a native LLVM binary and renders:
  1. A 48x24 Mandelbrot Set Fractal (20 fixed-point iterations in native LLVM IR)
     -> saved to `mandelbrot_ascii.txt` and `mandelbrot.ppm` (Netpbm P3 color image).
  2. A 40x20 3D Lambertian-Shaded Sphere Raycast
     -> saved to `sphere_ascii.txt` and `sphere.ppm` (Netpbm P3 color image).
"""
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from intentc.cli import load
from intentc.interp import Machine

HERE = os.path.dirname(os.path.abspath(__file__))
INTENT_FILE = os.path.join(HERE, 'graphics_engine.intent')
BINARY = os.path.join(HERE, 'graphics_engine')


def run_graphics():
    print('=== [Build 07] Compiling graphics_engine.intent to native LLVM binary ===')
    r = subprocess.run([os.path.join(ROOT, 'intent'), 'build', INTENT_FILE, '-o', BINARY],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    cmds = []
    # 1. Seed 48x21 Mandelbrot pixel grid: cx in [-2100, 700], cy in [-1100, 1100]
    W, H = 48, 21
    pid = 1
    for row in range(H):
        cy = -1100 + int(row * 2200 / (H - 1))
        for col in range(W):
            cx = -2100 + int(col * 2800 / (W - 1))
            cmds.append(f'add-pixel {pid},{row},{col},{cx},{cy},0,0,0,0,0,0,0,0,0,0,.')
            pid += 1

    for _ in range(20):
        cmds.append('step-mandelbrot')
        cmds.append('mark-escaped')

    cmds.extend([
        'shade-mandelbrot-interior',
        'shade-mandelbrot-low',
        'shade-mandelbrot-mid',
        'shade-mandelbrot-high',
        'shade-mandelbrot-edge',
        'dump-mandelbrot-glyphs',
        'dump-mandelbrot-rgb',
    ])

    # 2. Seed 41x21 3D Sphere Voxel Grid: sx in [-1200, 1200], sy in [-1200, 1200]
    SW, SH = 41, 21
    vid = 1
    for row in range(SH):
        sy = -1200 + int(row * 2400 / (SH - 1))
        for col in range(SW):
            sx = -1200 + int(col * 2400 / (SW - 1))
            cmds.append(f'add-voxel {vid},{sx},{sy},0,0,0,0,0,0,.')
            vid += 1

    cmds.extend([
        'raycast-sphere',
        'shade-sphere-hit',
        'shade-sphere-bright',
        'shade-sphere-core',
        'shade-sphere-shadow',
        'dump-sphere-glyphs',
        'dump-sphere-rgb',
    ])

    # Verify against reference interpreter
    prog, diags, _, _ = load(INTENT_FILE)
    assert all(d.level == 'note' for d in diags)
    m = Machine(prog)
    ref_out = []
    for c in cmds:
        ref_out.extend(m.run(c))

    proc = subprocess.run([BINARY], input='\n'.join(cmds) + '\n', capture_output=True, text=True, check=True)
    nat_out = proc.stdout.splitlines()
    assert nat_out == ref_out, 'Native vs Reference mismatch in graphics renderer!'

    n_mandel = W * H
    n_sphere = SW * SH
    m_glyphs = nat_out[0:n_mandel]
    m_rgb = nat_out[n_mandel:2 * n_mandel]
    s_glyphs = nat_out[2 * n_mandel:2 * n_mandel + n_sphere]
    s_rgb = nat_out[2 * n_mandel + n_sphere:2 * n_mandel + 2 * n_sphere]

    m_ascii = '\n'.join(''.join(m_glyphs[r * W:(r + 1) * W]) for r in range(H))
    s_ascii = '\n'.join(''.join(s_glyphs[r * SW:(r + 1) * SW]) for r in range(SH))

    with open(os.path.join(HERE, 'mandelbrot_ascii.txt'), 'w') as fh:
        fh.write(m_ascii + '\n')
    with open(os.path.join(HERE, 'sphere_ascii.txt'), 'w') as fh:
        fh.write(s_ascii + '\n')

    # Save valid Netpbm P3 .ppm color images
    with open(os.path.join(HERE, 'mandelbrot.ppm'), 'w') as fh:
        fh.write(f'P3\n{W} {H}\n255\n')
        for line in m_rgb:
            r_c, g_c, b_c = [max(0, min(255, int(x))) for x in line.split(',')]
            fh.write(f'{r_c} {g_c} {b_c}\n')

    with open(os.path.join(HERE, 'sphere.ppm'), 'w') as fh:
        fh.write(f'P3\n{SW} {SH}\n255\n')
        for line in s_rgb:
            r_c, g_c, b_c = [max(0, min(255, int(x))) for x in line.split(',')]
            fh.write(f'{r_c} {g_c} {b_c}\n')

    print('  [OK] Rendered 48x21 Mandelbrot Fractal & 41x21 3D Sphere in native LLVM IR!')
    print('  [OK] Saved `mandelbrot.ppm`, `sphere.ppm`, `mandelbrot_ascii.txt`, and `sphere_ascii.txt`.')
    print('\n--- Native Intent 2D Mandelbrot Set Preview ---')
    print(m_ascii)
    print('\n--- Native Intent 3D Lambertian Sphere Preview ---')
    print(s_ascii)


if __name__ == '__main__':
    run_graphics()
