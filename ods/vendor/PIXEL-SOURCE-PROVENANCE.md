# Pixel source provenance in ODS

The source under `vendor/pixel/` was exported from the private
`Osmantic/Pixel` repository at commit
`b33730436baf5d98bf58f7d57c090318fe19f433`, then adapted for ODS's
public ODS-only license, bundled-source installation, documentation, and
22-tool integration. The export deliberately omits the private Git history,
the private repository's `.github` workflows, the historical `LIVE-AUDIT*`
documents, and `DREAM-FORGE-SOURCE-AUDIT.md`. It is not a live Git submodule.

The visible source is duplicated into `vendor/pixel.bundle` solely so existing
Pixel installation code can use exact-commit Git verification without network
or private credentials. The bundle contains one new synthetic root commit with
public Osmantic release identity and no ancestors. Its commit is
`c3b573f9741fd402878176ac1d534201a904732a`, and its SHA-256 is
`21afe069cb98e81b92d5490c6b5fe23d926671d9fc2bbeff88473f9d3273cc27`.
Run `python3 scripts/verify-pixel-bundle.py` to check the bundle against the
visible source, tracked executable modes, and those pins. The `pixel` launcher
and the install/bootstrap scripts must retain executable Git modes.

The repository owner authorized this source publication and the ODS-only
Pixel grant. Third-party packages are not included in the Git bundle and
retain their own notices and licenses.

The ODS lint maintenance adaptation retains import effects and exported names,
renames only unread local bindings without dropping their right-hand sides,
expands semicolon statements with AST-equivalence verification, removes one
identical shadowed test helper, and supplies two missing Python imports. The
bundle was regenerated twice from tracked source bytes and executable modes;
both artifacts matched. The public synthetic author, message, and original
synthetic timestamp are retained; no upstream/private history is included.
