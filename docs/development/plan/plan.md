# Plan: wind variable table and wind frequencies

Builds [SPEC.md](SPEC.md). One branch, `fix/wind-variables-and-frequencies`, one PR.

1. **globals.py.** Replace the wind table; add aliases, domains, frequencies and `BARRA2_URL`; derive the old
   constants. Update `tests/test_globals.py`: table consistency with `int` heights, no `ua300m` xfail, template tests
   over every `(domain, freq)`, old constants equal the derived URLs.
2. **download.py.** Add `domain`/`freq`, the deprecation path, alias resolution, step-aware `time_end` and the new
   filenames. Move offline tests to `BARRA2_URL` with `domain=`/`freq=`; add the 20-minute, unsupported-combination,
   alias, filename and deprecation tests; parametrize the live tests over `BARRA2_FREQS`, and add a live
   every-variable check.
3. **convert.py.** Exact matching, height-based names, 10 m rename. Remove the `uas`/`vas` xfail; add exact-matching,
   1500 m and alias-output tests.
4. **Docs and examples.** README example and features, `scripts/example_barra2_dl.py` (and its notebook twin via
   the same cells), `CONTEXT.md` terms, backlog rows removed.
5. **Verify.** `make check`, `make test`, then a live run of the new live tests with `BARRA2_LIVE=1`.
