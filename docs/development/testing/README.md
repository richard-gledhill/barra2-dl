# Testing

The test strategy and known gaps.

- **Level:** unit tests per module in `tests/test_<module>.py`, plus doctests collected by `--doctest-modules`.
- **Offline by default:** `requests.get` is faked, files go to `tmp_path`. Tests that hit the real THREDDS server run
  only with `BARRA2_LIVE=1`.
- **Coverage:** 100% line and branch on `src`, reported by `make test`, not enforced (see
  [`../constraints.md`](../constraints.md)).
- **Known bugs** are pinned as strict `xfail` tests; see [`../backlog.md`](../backlog.md).
- **Manual checks** (Windographer import of the csv header, running the example scripts and notebooks) are in
  [`manual-checks.md`](manual-checks.md), with a table for recording results.
- **Gaps:** `scripts/example_barra2_dl_*.py` are not tested (it downloads data); the unwired `mapping` helpers are tested
  but not integrated.
