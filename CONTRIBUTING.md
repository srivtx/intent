# Contributing to Intent

Intent is a research prototype, and the most useful contribution is a **sentence**.

## Found a sentence it reads wrongly?

That is the bug that matters most. Open an issue with the
[misread sentence template](https://github.com/srivtx/intent/issues/new?template=misread.yml) and paste:

1. the smallest program that shows it,
2. what `./intent check yourfile.intent` printed in the right-hand column,
3. what you meant.

A sentence that is refused with a question is working as designed; a sentence that compiles to
something you did not mean is a bug.

## Changing the compiler

- No dependencies: Python 3.10+ and `clang` only.
- The reference interpreter (`intentc/interp.py`) defines the meaning. Native code
  (`intentc/llvm.py`) must agree with it on random commands: add the program to the
  differential tests in `tests/test_intent.py`.
- Keep the rules: never drop an unknown word, ask instead of guessing, the same text always
  means the same thing, and no AI in the compiler.
- Run the tests before opening a pull request:

```bash
python3 -m pytest tests -q
```

## Ideas and questions

Use [Discussions](https://github.com/srivtx/intent/discussions) for ideas, phrasing proposals and
"how would I say ...?" questions.
