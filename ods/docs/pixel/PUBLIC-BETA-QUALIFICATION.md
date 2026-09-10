# Portal public beta — 10 September 2026

Portal (currently labelled Pixel in parts of ODS) is a core ODS feature under active qualification. This branch is the common baseline for supervised fleet and external user tests. It is not a declaration of general release readiness.

## Current checkpoint — independent research allowances, 10 September

Runtime composition `476dc8a26ca598f833a60c9d1dae85ab51ab21a9` adds PR #3385 source `5cb98461f9bd2f9612d56dd6a632d7d2b1a13539` and PR #3818 source `974922caf37adc55697dea29739b86be59c7555a` to the previous beta. Both PRs remain open and unmerged. The new code changes the research guard and the sister PR's explicit-null runtime-status fallback; dashboard and API image code is unchanged.

Search and page-reading allowances are now independent. Exhausting search no longer prevents fetching already identified public pages, and exhausting page reads does not consume the remaining search allowance. Total limits, repeated-denial protection, private-network policy and ordinary file-tool checks remain. No numeric context, output or research limits were raised. Denial state survives compaction and permitted work does not reset it.

On physical Tower1, all four new direct/wrapped-tool regression cases failed against the preceding code and passed against the candidate. The candidate plugin suite passed 775 tests with one skip. The composed candidate, including the newer #3818 change, passed 1,017 tests with one skip. These source checks do not establish research completion or full provider acceptance.

Installed scope: Tower1 activated only the new plugin, verified its canonical digest, preserved owner configuration/model settings/containers, passed the native sandbox probe and released admission. Its fresh research-to-file repeat is running. This is not a full installation of composition 476. Tower3, Strixy and the laptop retain full runtime 7d from the preceding checkpoint; Tower2's mixed tree remains unresolved.

New native evidence: Tower3 continued the existing voxel project, published keyboard controls, then repaired a seeded-generator bug through another native turn. Root checked the actual preview: Play/Pause and keyboard regeneration work, and buildings now visibly vary. Strixy processed a preserved 12,000-row ZIP/CSV and independently reproduced 11,986 valid rows, 14 rejected rows and the exact USD total 44,834.04. Its follow-up fixed the short-row crash and archive-relative input, but independent checks found unbounded rejection samples, whole-member ZIP buffering and acceptance of extra fields. A further native repair is running. This was a workspace archive test, not an upload-interface pass.

Browser provisioning/navigation, citation retention through compaction, truthful runtime/model switching, sharing/cloud/Full Access, upload/vision ingestion and lifecycle qualification remain open. Fresh live test results, source checks and installed revisions are reported separately.

## Previous checkpoint — four installed beta machines, 10 September

Runtime code `7dcb7d8ffb69743a5a0326d6d798dad468cc1b7c` combines PR #3385 through `ae60d3122d9cb3e95ed4002f38bcf00e5869927e`, PR #3818 through `5d68d42fc9458012fae5bbd3985096576cdaeebc`, and the public-beta workspace/UI. This checkpoint changes documentation only. Both PRs remain open and unmerged into the default branch.

Tower1, Tower3, Strixy and the 8GB laptop completed the full code update. Each activation verified 1,712 non-generated source files, preserved owner configuration and access mode, restarted the affected services, updated plugin verification, and executed a native sandbox tool probe. The same pinned dashboard/API images are healthy on all four. Strixy/laptop also have the rebuilt model-router image; the Tower1/Tower3 ODS guests preserve their external model routes. Admission is released. Tower2 still has a mixed tree, with 205 baseline mismatches under investigation; its physical fleet inference host and separate ODS guest must be distinguished.

The identity/settings composition passed 116 focused API tests, 703 frontend tests, lint and production build on physical Tower2. The subsequent native web-result projection passed 771 plugin tests with one skip. PR #3385 currently has 32 passing hosted checks and three skips. These are separate from installed acceptance. Earlier beta-wide Python lint debt is not declared fixed.

Current native evidence:

- **Research:** Tower1's actual OpenClaw native search returned relevant restaurant/menu/delivery pages without Perplexica. The new web-result projection operated. The full task nevertheless overflowed once, compacted at a recorded 36,829 tokens, repeated research and exhausted the search bucket. The compaction summary retained progress but omitted citation URLs. An exhausted search bucket also prevented fetch calls despite remaining fetch allowance. The turn aborted and no report was saved.
- **Files and refresh:** Strixy's initial expense-analysis answer recovered after refreshing the browser during execution. Root verified the preserved original and total 83.00. The revised Decimal script passed independent malformed-data and alternate-directory checks. Its follow-up still aborted at an unauthorized recursive cleanup of temporary fixtures: correct saved artifacts do not establish a clean final experience.
- **Applications:** a fresh Tower3 chat recovered the voxel project; root verified Play/Pause/Play in its actual preview. This recovery occurred on the previous canary before the full update. The laptop planner remains broken: its newest published preview has blank results and a `dstBadge` null-access JavaScript error.
- **Browser:** a fresh laptop diagnostic after the full update found no interactive browser tool. An owned-preview URL triggered an overbroad private-URL denial, and delivery then incorrectly treated the diagnostic as a website-build request. Factory browser capability and intent routing remain open.
- **Model status:** Strixy's UI/router reports 35B while saved alias metadata names 9B. The configured route points to the current model router; a stale name is not proof of 9B inference. Actual request identity and model-switch recovery still need qualification.
- **Sharing:** the laptop's earlier template-permission and missing-router-metadata blockers are repaired. Test grants remain revoked and sharing stopped. No two-host inference/tool-capability pass is claimed.

PR #3818 has subsequently published `974922caf37adc55697dea29739b86be59c7555a`, a separate explicit-null runtime-status correction, composed with parent ae60. That newer feature source is not in runtime beta 7d. New beta UX PRs are under review; they are not installed merely because they exist.

The next priorities are research completion across compaction, working browser-based app verification, truthful routing/status and clean Stop/resume behavior. Broader acceptance still includes uploads, PDFs, codebases/GitHub/images, network and Full Access, real cloud/provider roles and sharing, fresh installs, upgrade, reboot and rollback. The fleet has useful live results and real failures; continuous live-test occupancy and the 90% direct-testing-time target have not been achieved.

## Historical checkpoint — 9 September

The following evidence describes the earlier composition and installations, not the current fleet state above.

## Included changes

The integration at `3861c14cfc4b1a4e0dd5a261f2344a36bb49cfa8` combines:

- PR #3385 through `7dbddb225de63793fc29178165372c4eabae32ca`: background-process completion accounting, recovery into permitted work after a denied network request, and SVG file delivery without an unrequested website-publication requirement. Explicitly requested previews still require publication evidence.
- PR #3818 through `91050302d87bebf94696335e37a38d3388206ac7`: provider routing, runtime settings, and Apply/Deactivate/Recover controls.
- The existing public-beta workspace and dashboard UI from `7dde42bf020fa50709beee785ef06f06f0d6b458`, including PR #4027.

These PRs remain open and unmerged. Publishing their composition here is beta testing, not user acceptance.

## Qualification evidence

The earlier composition passed 560 focused plugin checks and 638 frontend tests across 69 files, followed by a production frontend build on physical Tower3 with Node 22.23.2. The SVG successor passed 586 focused integration checks on the Tower3 guest. Its PR #3385 source also passed 736 plugin checks with one skip on physical Tower3 and all 32 applicable hosted checks. The frontend is unchanged by the SVG successor. An earlier guest run omitted a sibling module from its source snapshot and encountered extensive timing failures. Those results are retained as test-environment evidence, not counted as established product regressions.

The 8GB laptop was updated to PR #3385 source `7dbddb22`, preserving owner configuration, SDK and container identities. Its native tiny-SVG task now delivers the saved path correctly; root inspection confirmed the actual 164-byte SVG is valid. The agent's SVG read still omitted the image, so full readback/vision qualification remains open. Tower3 generated and published a maze whose movement and restart controls responded in the browser; completion of the win path is not yet qualified.

Tower2's protected runtime and dashboard/API/edge canary at beta `d2542b75` activated successfully after an exercised file/image rollback. The deployment helper needed a bounded transition journal and container recreation after the ingress socket directory changed. Native provider controls and inference are being qualified separately. This does not establish whole-installation or factory-core parity, and the other machines are not yet on a common installed beta revision.

Installed fleet state is tracked separately. A source commit, successful build, or isolated SDK fixture does not prove that a machine has been upgraded or that a native user journey succeeds.

## Known limitations to exercise

- The original 8GB laptop has reproduced a long model response ending at 8,192 output tokens with no visible content or created files. Installed request/response settings are under investigation; increasing context is not a verified fix.
- Public PDF ingestion can fail at extraction or reach an approval workflow that chat does not explain correctly.
- Diagnosing a registered local extension can choose a blocked network route and fail to finish its report. Discovery alone is not proof that the extension responds correctly.
- Research and generated applications still require checking the cited facts and actual rendered output. Some completion claims exceed the evidence.
- A Strixy research correction repeated six malformed edit calls, then claimed saved corrections despite an unchanged readback. A further user-directed retry successfully changed the file. Automatic tool-error recovery and honest completion remain qualification gaps; successful research retrieval alone does not establish factual accuracy or persistence.
- The upstream isolated browser runtime has passed a disposable navigation/authentication/private-address check. Factory browser provisioning, full access transitions, and clean-install/upgrade/rollback journeys still require native qualification.

When reporting a test, include the installed beta commit, machine/OS/GPU, model and context settings, the task, the observed result, and any artifact or screenshot. Keep credentials and private documents out of public reports. Preserve hardware-specific settings when comparing machines; shared source does not require identical model configurations.
