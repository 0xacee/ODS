# ODS PR batch validation — 2026-09-10

Twenty new pull requests were opened against Osmantic/ODS. All twenty are now Ready for review following a fresh audit of their unchanged candidate heads. The final GitHub audit found no conflicts with main and no attached check results. The results below are local validation, not hosted CI or live-installation evidence.

| PR | Change | Candidate head | Focused validation |
| --- | --- | --- | --- |
| [#3995](https://github.com/Osmantic/ODS/pull/3995) | fix(installer): keep progress polling alive across effect cleanup | 40576458 | 5 Vitest |
| [#3996](https://github.com/Osmantic/ODS/pull/3996) | fix(installer): recover failed and superseded GPU checks | 31141545 | 3 Vitest |
| [#3997](https://github.com/Osmantic/ODS/pull/3997) | fix(installer): recover prerequisite setup failures | db01785e | 5 Vitest |
| [#3998](https://github.com/Osmantic/ODS/pull/3998) | fix(installer): expose feature selection states accessibly | 4213dbd4 | 2 Vitest |
| [#3999](https://github.com/Osmantic/ODS/pull/3999) | fix(installer): report failed browser launches | 534d687e | 2 Vitest |
| [#4000](https://github.com/Osmantic/ODS/pull/4000) | fix(installer): keep wizard pages reachable in small windows | 9aefb0a0 | 2 Chromium |
| [#4001](https://github.com/Osmantic/ODS/pull/4001) | fix(installer): retain user choices when retrying installation | 8b364f64 | 2 Vitest |
| [#4002](https://github.com/Osmantic/ODS/pull/4002) | fix(usage): isolate same-host runtime counter observations | 1ed6b1ed | 22 API |
| [#4003](https://github.com/Osmantic/ODS/pull/4003) | fix(remote-provider): diagnose invalid persisted text | 17277d75 | 32 API |
| [#4007](https://github.com/Osmantic/ODS/pull/4007) | fix(dashboard): restore the offline agent monitor | f5892fa0 | 3 Chromium; lint/build |
| [#4013](https://github.com/Osmantic/ODS/pull/4013) | fix(agents): expire stale telemetry after collection failures | 64dc5806 | 22 API |
| [#4063](https://github.com/Osmantic/ODS/pull/4063) | feat(agents): expose authenticated Prometheus snapshots | ded258bd | 22 API |
| [#4064](https://github.com/Osmantic/ODS/pull/4064) | perf(usage): bound and overlap runtime metric scrapes | 6024062b | 22 API |
| [#4065](https://github.com/Osmantic/ODS/pull/4065) | fix(installer): recover diagnostic clipboard failures | bb8d074c | 3 Vitest |
| [#4067](https://github.com/Osmantic/ODS/pull/4067) | feat(installer): recheck system requirements after host repairs | d0b01e3e | 3 Vitest |
| [#4068](https://github.com/Osmantic/ODS/pull/4068) | fix(installer): preserve keyboard orientation across wizard steps | a54a53b9 | 2 Chromium |
| [#4069](https://github.com/Osmantic/ODS/pull/4069) | perf(voice): overlap independent service health probes | d8eaf54b | 9 API |
| [#4070](https://github.com/Osmantic/ODS/pull/4070) | feat(agents): expose a bounded throughput history window | 46435254 | 83 API |
| [#4071](https://github.com/Osmantic/ODS/pull/4071) | fix(installer): drain child logs after invalid UTF-8 | a8e0d434 | 7 Rust on Windows/Linux; isolated child executed |
| [#4072](https://github.com/Osmantic/ODS/pull/4072) | ci(installer): run native module contracts across platforms | abe9791a | 6 Rust on Windows/Linux; actionlint; lock parity |

**Combined snapshots**

- The [20-PR integration code snapshot](https://github.com/0xacee/ODS/commit/e2058ad5a9c868701a04affa276ede7dda620bf5) contains all candidate heads, including the final GPU-layout and test-fixture followups.
- The [compatibility snapshot](https://github.com/0xacee/ODS/commit/14d5a68a280dd303259a4b02c8b181b6aa4ef25f) additionally includes existing #3703 (desktop request contract), #3704 (progress phases), #3731 (Compose prerequisites), #3733 (diagnostic tails), and #3669 (hermetic NVIDIA test fixture). These five are not counted as new PRs.

| Surface | Result | Evidence scope |
| --- | --- | --- |
| Installer | 25 Vitest tests; 4 Chromium tests; production build passed | Final compatibility snapshot; the 20-PR-only snapshot also passes 25 tests and build |
| Dashboard | 258 Vitest tests; 3 Chromium tests; lint/build passed | Tested at 2e292fd9; dashboard files are unchanged in the final snapshots |
| Dashboard API | 2,166 passed, 1 skipped, 2 warnings | Compatibility API tree tested at 22d17298; only two installer test fixtures changed afterward |
| Native modules | 17 passed on Windows x86_64 and Linux x86_64 (WSL) | Compatibility Rust tree at 22d17298, unchanged afterward; one ignored-discovery helper is explicitly executed by its parent test |
| Configuration | actionlint, Python CI-select Ruff, dependency parity, diff whitespace checks passed | New workflow, changed Python files, and the shipped native dependency versions |

Without existing #3669, the API run encounters NVIDIA planning fixture failures. A clean main worktree reproduces all 15 failures in test_model_activate.py (223 other tests pass, 1 skips in that module). The batch does not claim those baseline failures are fixed by any of the twenty new PRs. The compatibility run includes #3669 explicitly and completes the full API suite.

**Merge order and resolutions**

The table order is the order used for the 20-PR snapshot. Keep both installer test scripts (test and test:e2e), plus both Vitest and Playwright dependencies. Keep the merged lockfile; clean npm ci passed. Browser files use the .browser.ts suffix so Vitest cannot discover Playwright tests.

- For #3996 + #4001, retain active-check disposal/retry handling and initialize the selected tier with initialTier ?? detected.recommended_tier; the effect depends on attempt and initialTier.
- For #4000 + #4068, retain key={step} on the named, focused main element. Keep #4001 saved tier/features props.
- For #4013 + #4070, retain read-time pruning and the history_limit parameter. For #4063 + #4070, keep both routes and all required datetime/Annotated/Query/Response imports.
- With existing #3731, the prerequisite Continue gate is busy || !prereqs.all_met. Followups db01785e (#3997) and 8b364f64 (#4001) keep fixtures compatible with both payload shapes.
- With existing #3703/#3704/#3733, retain request argument mapping, structured progress phases, bounded diagnostic tails, and the byte-decoding output_lines reader on both streams. The compatibility snapshot retains every corresponding Rust regression.

Followup 31141545 (#3996) makes long GPU error messages scrollable. Followup 9aefb0a0 (#4000) separates browser test discovery. These changes were pushed to their original PR branches; no replacement PRs were created.

**Remaining validation**

No full Tauri/WebView package build, macOS execution, real GPU/Docker installation, or production deployment was performed. Native module tests exercise actual process boundaries with isolated fixture checkouts and state paths. Hosted GitHub checks have not reported results. Ready for review does not establish merge readiness. Native changes #4071 and #4072 are explicitly not merge-ready until their declared platform gates and independent human review are complete.

The integration and compatibility branches are review artifacts on the fork. Nothing was merged into upstream main.
