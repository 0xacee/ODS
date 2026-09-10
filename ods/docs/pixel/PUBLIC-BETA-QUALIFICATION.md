# Portal public beta — 10 September 2026

Portal (currently labelled Pixel in parts of ODS) is a core ODS feature under active qualification. This branch is the common baseline for supervised fleet and external user tests. It is not a declaration of general release readiness.

## Current checkpoint — 10 September

Code qualified at `7b74eda7ca1d` combines PR #3385 through `5a8b84d136bd10a363fa0e3d1393fde45a97bf56`, PR #3818 through `5d68d42fc9458012fae5bbd3985096576cdaeebc`, and the existing public-beta workspace/dashboard work. Both PRs remain open and unmerged into the default branch.

The composition includes durable chat-result recovery, Stop ordering, native-search provisioning, provider/runtime/access controls, sharing diagnostics and advertised-port handling, and a customizable assistant display name with Portal as the default. Internal routes remain stable. The beta workspace layout and preview isolation are preserved.

The exact composition passed 116 focused API tests, all 703 frontend tests across 73 files, frontend lint, and the production build on physical Tower2. The API scope covers chat recovery and identity. PR #3385 at `5a8b84d1` separately passed 32 hosted checks, with three skipped. The wider beta retained Python lint debt outside the recovery files; this composition is not declared globally lint-clean.

Current native evidence and gaps:

- Tower3 recovered a real answer and preview after closing the browser tab; the completed result survived an API replacement. Explicit Stop and stale Stop were independently checked. This does not qualify OS-shutdown recovery or every long-running job.
- Tower1 runs a separate native-search canary with the official pinned `parallel-free` plugin and a required read-only service mount. Actual ODS chat receipts show relevant restaurant pages. The full research-to-file task still failed after context-overflow checks, compaction/retry, and research-budget exhaustion. No report was saved; standalone research is not accepted.
- Laptop sharing exposed incorrect installed Compose permissions, then an older router image missing required model metadata. The file mode was repaired without changing bytes. No inference capability probe ran. Test grants are revoked and sharing is stopped; existing model configuration and llama/router containers were preserved.
- Real app tests still expose functional failures: a voxel repair failed at shell portability/output completion, and a laptop time-zone planner initially displayed identical times in different cities. Publication alone is not functional acceptance.
- Strixy's UI displayed its 35B model while the agent's status projection reported old 9B configuration. The agent could not establish the actual underlying model. Runtime/projection parity remains an upgrade requirement.

Installed state at this checkpoint: Tower1, Strixy, and the laptop retain the earlier `8c` dashboard beta; Tower3 runs recovery canary `a86bca33`; Tower2 remains a coordinated mixed-source exception protecting its runtime. This new composition is not yet installed consistently. Qualification must include router image bytes, gateway/plugin configuration and file permissions as well as source and dashboard/API images.

Next acceptance work: reliable research-to-file and bounded ingestion across compaction; model switching and truthful runtime status; interruption/resume; files, PDFs, codebases, GitHub and images; browser/network and Full Access; cloud providers and two-host sharing; fresh-install, upgrade, reboot and rollback. Record actual installed versions and artifacts, and distinguish partial results from accepted behavior.

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
