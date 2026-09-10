# Community PR integration — 10 September 2026

This beta-only composition starts at public-beta `d7d76cdc` and preserves the
existing OpenClaw/Portal work. It does not merge public-beta into main or qualify
a general release.

## Included PRs

[#4055](https://github.com/Osmantic/ODS/pull/4055), [#4061](https://github.com/Osmantic/ODS/pull/4061), [#4066](https://github.com/Osmantic/ODS/pull/4066), [#4074](https://github.com/Osmantic/ODS/pull/4074), [#4075](https://github.com/Osmantic/ODS/pull/4075), [#4076](https://github.com/Osmantic/ODS/pull/4076), [#4077](https://github.com/Osmantic/ODS/pull/4077), [#4078](https://github.com/Osmantic/ODS/pull/4078), [#4079](https://github.com/Osmantic/ODS/pull/4079), [#4080](https://github.com/Osmantic/ODS/pull/4080), [#4081](https://github.com/Osmantic/ODS/pull/4081), [#4082](https://github.com/Osmantic/ODS/pull/4082), [#4083](https://github.com/Osmantic/ODS/pull/4083), [#4084](https://github.com/Osmantic/ODS/pull/4084), [#4085](https://github.com/Osmantic/ODS/pull/4085), [#4092](https://github.com/Osmantic/ODS/pull/4092), [#4093](https://github.com/Osmantic/ODS/pull/4093), [#4102](https://github.com/Osmantic/ODS/pull/4102), [#4103](https://github.com/Osmantic/ODS/pull/4103), [#4105](https://github.com/Osmantic/ODS/pull/4105), [#4106](https://github.com/Osmantic/ODS/pull/4106), [#4107](https://github.com/Osmantic/ODS/pull/4107), [#4108](https://github.com/Osmantic/ODS/pull/4108), [#4109](https://github.com/Osmantic/ODS/pull/4109), [#4110](https://github.com/Osmantic/ODS/pull/4110), [#4112](https://github.com/Osmantic/ODS/pull/4112), [#4113](https://github.com/Osmantic/ODS/pull/4113), [#4114](https://github.com/Osmantic/ODS/pull/4114), [#4115](https://github.com/Osmantic/ODS/pull/4115), [#4116](https://github.com/Osmantic/ODS/pull/4116), [#4117](https://github.com/Osmantic/ODS/pull/4117), [#4118](https://github.com/Osmantic/ODS/pull/4118), [#4119](https://github.com/Osmantic/ODS/pull/4119), [#4120](https://github.com/Osmantic/ODS/pull/4120), [#4121](https://github.com/Osmantic/ODS/pull/4121), [#4139](https://github.com/Osmantic/ODS/pull/4139), [#4140](https://github.com/Osmantic/ODS/pull/4140), [#4141](https://github.com/Osmantic/ODS/pull/4141), [#4142](https://github.com/Osmantic/ODS/pull/4142), [#4143](https://github.com/Osmantic/ODS/pull/4143), [#4144](https://github.com/Osmantic/ODS/pull/4144), [#4145](https://github.com/Osmantic/ODS/pull/4145), [#4146](https://github.com/Osmantic/ODS/pull/4146), [#4147](https://github.com/Osmantic/ODS/pull/4147), [#4148](https://github.com/Osmantic/ODS/pull/4148), [#4149](https://github.com/Osmantic/ODS/pull/4149), [#4150](https://github.com/Osmantic/ODS/pull/4150), [#4151](https://github.com/Osmantic/ODS/pull/4151), [#4152](https://github.com/Osmantic/ODS/pull/4152), [#4153](https://github.com/Osmantic/ODS/pull/4153), [#4154](https://github.com/Osmantic/ODS/pull/4154).

The changes cover retained chat recovery, search, dictation, sharing/settings
race handling, verified files and diffs, conversation organization/export/import,
draft tools, and publication history/responsive preview controls. Import is
text-only and never replays exported jobs or restores permission receipts.

Composition fixes retain current Portal identity, combine overlapping tests and
controls, correct RGB theme variables, and assign distinct React keys to the
file input and draft preview. Real browser inspection caught duplicate file
buttons caused by those sibling keys; a new integration regression covers it.

## Verification

- Frontend: 833 tests passed across 95 files; production build passed.
- Frontend lint: zero errors, 539 warnings (including the existing JSX-unused
  warnings); this is not a claim that lint debt is resolved.
- Focused Windows Python runs: 54 filter/access/cache tests and 50
  Lemonade/talk/router-fixture tests passed.
- Linux container: 49 preview/charset/access tests and 15 subtests passed.
- WSL native ingress: 57 tests passed.

These are source/composition checks, not Windows/Linux/macOS fresh-install,
sharing, cloud-provider, or complete agent acceptance. The existing
[community handoff](COMMUNITY-HANDOFF.md) limitations still apply.

## Not included in this batch

Overlapping history PR #4111 is superseded here by #4121. Draft #4104 and Python
3.10 backport #4124 require additional contract/platform work. #4165 and #4166
need real provider-health/workspace contract validation. Standalone utility PRs
#4129, #4131, #4132, #4134, #4135, #4136 and #4138 are not integrated features.
The remaining installer, privacy, session and platform-skip candidates remain
open for focused review; blanket skips or partial BSD substitutions are not
platform qualification.
