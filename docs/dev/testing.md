# Testing

`python -m pytest` runs the suite on the real Gemma source with a fixed approval index
(`tests/fixtures/approvals.json`), so results don't depend on the live review state of dita-corpus. The model is
`aegis.model.Scripted`, which replays fixed answers.

- `tests/test_checks.py`: profiles; each check, including the real Annex XI and XII gaps, the version-date rule, the
  key-only rule, self-approval, bot approval, non-owner approval and direct pushes; the licence conflict; the leak test
  in all three packs; that no decision can release a leak.
- `tests/test_model_and_api.py`: `propose_mapping` against its schema (invented ids, low confidence, `none`, no topic
  bodies in the prompt); the sandbox end to end through the API; pack hashes; the daily cap; Ask's checks.
- The MVP tests in `tests/test_model_and_api.py`: both packs and the seven metrics come back; the manifest hash on the page
  equals the download's; an unknown system or reader is refused.
- `tests/test_dita_ot.py`: when `build/packs` exists, the topics DITA-OT kept for each profile equal the topics the
  Python profile keeps.

Three tests skip when `build/packs` doesn't exist. Run `scripts/build_packs.sh` first to run them: 34 pass, 0 skipped.
