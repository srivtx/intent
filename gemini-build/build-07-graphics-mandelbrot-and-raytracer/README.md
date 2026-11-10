# Build 07: Can Intent Build Visual Graphics Programs? (Mandelbrot Set & 3D Sphere Raycaster)

## Direct Answer: Can Intent Build Graphics Programs Right Now?
- **NO for Windowed / Interactive GPU Graphics (`OpenGL`, `Metal`, `SDL`, `Canvas`)**: [`intentc/llvm.py`](file:///Users/zen/Desktop/project-10nov/intentc/llvm.py#L16-L40) only links 24 standard `libc` text/memory functions (`getline`, `printf`, `malloc`, `qsort`, etc.) and has no foreign-function interface (FFI), no windowing syscalls, no floating-point types, and no pixel framebuffer output.
- **YES for Offline Software Rendering (Raycasting, Fractals, Netpbm `.ppm` Images & ASCII Framebuffers)**: Because Intent compiles arithmetic loops directly to native LLVM IR and preserves insertion order when told `Keep pixels in the order they were added`, a pure `.intent` program **can** act as a software fragment shader over a collection of pixels!

---

## 1. What We Tried to Do
We tried to write two classic computer graphics pipelines in **100% pure `.intent`** ([`graphics_engine.intent`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-07-graphics-mandelbrot-and-raytracer/graphics_engine.intent)):
1. **A 2D Mandelbrot Set Fractal Renderer** ($z_{n+1} = z_n^2 + c$, 20 iterations per pixel across a $48 \times 21$ grid).
2. **A 3D Orthographic Sphere Raycaster** with ray-sphere intersection ($x^2 + y^2 + z^2 \le R^2$), surface normal reconstruction, and directional Lambertian diffuse + specular shading across a $41 \times 21$ voxel grid.

---

## 2. What Worked (and Why We Think It Worked)
- **Fixed-Point Integer Shader Math (`1.0 = 1000`)**: By scaling coordinates by `1000`, complex squaring $z^2 + c$ works cleanly in 64-bit integers:
  ```text
  step-mandelbrot: for every pixel whose escaped is 0, set zx2 to (zx * zx) / 1000, then set zy2 to (zy * zy) / 1000, then set mag2 to zx2 + zy2, then set zy to (2 * zx * zy) / 1000 + cy, then set zx to zx2 - zy2 + cx, then increase iter by 1.
  ```
  **Why this worked**: In [`llvm.py:542-548`](file:///Users/zen/Desktop/project-10nov/intentc/llvm.py#L542-L548), chained assignments in one sentence execute sequentially in-place on each pixel struct. Updating `zy` *before* `zx` lets `2 * zx * zy` use the old `zx`, while `zx2` and `zy2` hold the squared components!
- **2nd-Order Taylor Polynomial for `sqrt` in 3D Sphere Normals**: Since Intent has no `sqrt()`, on a sphere of radius $R = 1000$ ($R^2 = 1{,}000{,}000$), we approximated $z = \sqrt{R^2 - r^2} \approx 1000 - \frac{r^2}{2000} - \frac{(r^2 / 2000)^2}{2000}$ directly in English arithmetic, producing smooth 3D Lambertian shading in [`sphere.ppm`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-07-graphics-mandelbrot-and-raytracer/sphere.ppm) and [`sphere_ascii.txt`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-07-graphics-mandelbrot-and-raytracer/sphere_ascii.txt).

---

## 3. What Did Not Work & Bugs We Faced (and Why We Faced Them)
In [`attempt_failed.intent`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-07-graphics-mandelbrot-and-raytracer/attempt_failed.intent) (diagnostics in [`attempt_failed_output.txt`](file:///Users/zen/Desktop/project-10nov/gemini-build/build-07-graphics-mandelbrot-and-raytracer/attempt_failed_output.txt)):
1. **Floating-Point Literals (`-2.0`, `0.5`) Failed**:
   - **Why we faced it**: [`parser.py:400-402`](file:///Users/zen/Desktop/project-10nov/intentc/parser.py#L400-L402) explicitly rejects any number token containing `.` (`decimal numbers are not supported yet`).
2. **Arithmetic Expressions on the Left-Hand Side of `WHERE` (`whose zx2 + zy2 is over 4000`) Failed**:
   - **Bug / Parser Asymmetry We Faced**: Writing `whose zx2 + zy2 is over 4000` fails with `question: which property is this comparing?`.
   - **Why we faced it**: In [`parse_term()`](file:///Users/zen/Desktop/project-10nov/intentc/parser.py#L707-L731), the left-hand side of a condition must be a single `FIELD` token (`p[0].kind == 'FIELD'`), whereas the right-hand side is parsed with `self.whole_expr(rest)`.
   - **How we worked around it**: Either materialize `mag2 = zx2 + zy2` in the update step and check `whose mag2 is over 4000`, OR move `+ zy2` to the right-hand side (`whose zx2 is over 4000 - zy2`)!
3. **No Loop-Until-Convergence Inside `.intent`**:
   - **Why we faced it**: Each `step-mandelbrot` command performs 1 iteration over the collection; the external runner had to send `step-mandelbrot` 20 times.

---

## 4. Where Our Analysis Might Be Wrong & Thoughts for a Reviewing Model (Aligned with Flexibility, Not Rigidity)
- **Where we might be wrong**:
  - One could argue Intent *should never* have GPU/windowing primitives baked into [`lexicon.py`](file:///Users/zen/Desktop/project-10nov/intentc/lexicon.py), because Intent's core identity is describing **information and capabilities**, not low-level I/O protocols.
  - A stronger reviewing model may also notice that our LHS vs. RHS condition asymmetry (`zx2 + zy2 is over 4000` failing while `zx2 is over 4000 - zy2` succeeds) is a pure parser limitation in [`parse_term()`](file:///Users/zen/Desktop/project-10nov/intentc/parser.py#L707), not a fundamental IR or LLVM limitation—because [`ir.py`](file:///Users/zen/Desktop/project-10nov/intentc/ir.py#L6) (`('cmp', op, a, b)`) and [`llvm.py:182-184`](file:///Users/zen/Desktop/project-10nov/intentc/llvm.py#L182-L184) **already support arbitrary expressions on both sides of `cmp`!**
- **Flexible (Non-Rigid) Hypotheses for a Reviewing Model to Consider**:
  - Rather than forcing programmers to memorize rigid rules like *"put math on the right of `is over`, never on the left"*, could [`parse_term()`](file:///Users/zen/Desktop/project-10nov/intentc/parser.py#L698-L735) split a comparison clause at the comparison phrase (`IS`/`NOT`/`CMP`/`EQSYM`) and call `whole_expr()` on **both** the left and right sides whenever a full expression is present? That would make `whose zx2 + zy2 is over 4000` or `whose price * qty is at least 1000` work naturally in plain English with zero change to the IR or LLVM backend.
