# Plan: parameter presets, variable inventory and fixed fields

Builds [SPEC.md](SPEC.md). One branch, `feat/parameter-presets-inventory`, one PR.

1. **Inventory.** Write `scripts/build_barra2_inventory.py` and generate `barra2_variables.csv` from the live server.
2. **globals.py.** Load the inventory; add presets, the default preset, the automatic fixed fields and the `fx`
   template. Tests: every `(domain, freq)` has an inventory entry, presets against the inventory, defaults.
3. **download.py.** `preset_variables`, inventory validation, `fx` routing and automatic `orog`. Update the expected
   URL lists in the existing tests for the extra `orog` request. Add validation, preset and `fx` tests, plus live
   inventory-drift and `orog` tests.
4. **merge.py and convert.py.** Skip `fx` files in `merge_csvs_to_df`, `read_fixed_fields`, `convert_units`, each
   with tests.
5. **Docs and examples.** README, `CONTEXT.md` (Preset, Inventory, Fixed field), the example script and notebook.
6. **Verify.** `make check`, `make test`, live tests, then the PR.
