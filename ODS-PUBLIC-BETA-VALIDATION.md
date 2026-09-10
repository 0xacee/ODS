# Public beta contribution validation — 2026-09-10

Ten independent branches target Osmantic/ODS public-beta at 31063fcbb602859698317698b0a22d53406290ec. Each branch starts directly from that beta commit.

## Candidate commits

| Change | Candidate | Focused evidence |
| --- | --- | --- |
| fix(beta): open the workspace when browser storage access is denied | [d37efe73](https://github.com/0xacee/ODS/commit/d37efe73e00c0a254fcd804dfdb3c1bf108958de) | 12 App tests |
| fix(beta): isolate malformed retained conversations without discarding data | [8253ac9e](https://github.com/0xacee/ODS/commit/8253ac9e16629b0b1f178d090357c018a0f8ee91) | 4 navigation + 9 library tests |
| fix(beta): retain the search session on repeated shortcuts | [417502a4](https://github.com/0xacee/ODS/commit/417502a47c5132d5aa591e5b9d377bb190ee0f4a) | 4 command-search tests |
| fix(beta): recover unavailable approval-command clipboard access | [3335e70c](https://github.com/0xacee/ODS/commit/3335e70c6040c38d30e1945f6c27eb50539d4bc6) | 3 approval-copy tests |
| fix(beta): make prompt command choices reachable from the keyboard | [addea460](https://github.com/0xacee/ODS/commit/addea460ed56694f323e6c706af193bc65bff8f9) | 5 composer tests |
| fix(beta): clear hidden navigation filters on sidebar collapse | [36944bb7](https://github.com/0xacee/ODS/commit/36944bb7fd7664eaf5809005d8aaddb92570817b) | 7 navigation tests |
| fix(beta): preserve verified source text through syntax highlighting | [76cc5efc](https://github.com/0xacee/ODS/commit/76cc5efc9f578d12839107545d41f39823753dab) | 7 source + 9 diff tests |
| fix(beta): append only newly finalized dictation results | [d1c3f0a1](https://github.com/0xacee/ODS/commit/d1c3f0a18db4dd72c77bafdea1851eba4a3a4bac) | 5 dictation tests |
| fix(beta): update sharing controls when device keys expire | [060a640a](https://github.com/0xacee/ODS/commit/060a640aba36623079dd8359b34f14bd4ef473dc) | 19 sharing tests |
| feat(beta): export complete Pixel conversations as local JSON | [cf3bff32](https://github.com/0xacee/ODS/commit/cf3bff32c9c63a2e43aa67a4111fabda2e1baf2e) | 2 export + 2 navigation tests |

## Integration and compatibility

The ten-PR code snapshot is 15d215c5a0ac23556e892397fbee3d5f9570497f.
The branches merge without conflicts. Each candidate also passes its own production build.

A separate compatibility snapshot, 7dc69aa5, adds existing PRs #4081 (open-search history refresh), #4078 (cleared draft retention), #4080 (advertised sharing port), and #4105 (IME candidate handling).
Its five affected suites pass **43 tests**, and its production build passes.
Two append-only conflicts in PixelCommandSearch.test.jsx were resolved by retaining both sets of tests and their imports. Production changes merge automatically.

The final repeated-shortcut PR intentionally excludes IME handling, which belongs to #4105.
The final dictation PR excludes Stop/finalization, which belongs to #4106; it fixes cumulative result replay instead. Existing contributions are not counted as new PRs.

## Browser evidence

Chromium exercised the integrated dashboard through its real rendered UI with fixture API responses:

- Downloaded and parsed a complete 80-message conversation JSON file beside an unrelated malformed library record.
- Preserved an open search query through repeated Ctrl+K and restored the original composer focus after native-dialog Escape.
- Selected a prompt with the keyboard and appended it to an existing draft.
- Restored hidden destinations when collapsing a filtered sidebar.

No uncaught page errors occurred. The export test had to hover the conversation row, as the download control is revealed on hover/focus. The harness also uses reduced motion to bypass the normal opening animation.

The portable harness is [review/public-beta-browser.cjs](review/public-beta-browser.cjs).
Run the dashboard on loopback port 18245, install Playwright 1.63.0 and Chromium in a separate tooling directory, then run the harness with NODE_PATH pointing to that directory's node_modules.
ODS_REVIEW_URL can select a different loopback dashboard test server. The harness replaces /api/ responses with fixtures; it does not test a live Pixel deployment.

## Limits and review

No Docker/GPU installation, native Windows/macOS package build, live sharing service, actual microphone recognition, or real model task was exercised.
Dictation validation uses controlled SpeechRecognition events; approval-command checks copy a verified fixture command and never execute it.
Export archives browser-retained records only; workspace files and server data need separate backups.

These changes are ready for human code review. Local checks do not imply that hosted CI or end-to-end public-beta qualification has passed. No upstream merge or deployment was performed.
