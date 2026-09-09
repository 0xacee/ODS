# Portal public beta — 9 September 2026

Portal (currently labelled Pixel in parts of ODS) is a core ODS feature under active qualification. This branch is the common baseline for supervised fleet and external user tests. It is not a declaration of general release readiness.

## Included changes

The integration at `d2e3040e16f4264b4d575120e989f0b0e27ed7de` combines:

- PR #3385 through `f6058891ad76edbe36ca06ee2fa3ddaeffcbe3ad`: background-process completion accounting and recovery into permitted work after a denied network request.
- PR #3818 through `91050302d87bebf94696335e37a38d3388206ac7`: provider routing, runtime settings, and Apply/Deactivate/Recover controls.
- The existing public-beta workspace and dashboard UI from `7dde42bf020fa50709beee785ef06f06f0d6b458`, including PR #4027.

These PRs remain open and unmerged. Publishing their composition here is beta testing, not user acceptance.

## Qualification evidence

The combined code passed 560 focused plugin checks and 638 frontend tests across 69 files, followed by a production frontend build on physical Tower3 with Node 22.23.2. An earlier guest run omitted a sibling module from its source snapshot and encountered extensive timing failures. Those results are retained as test-environment evidence, not counted as established product regressions.

Installed fleet state is tracked separately. A source commit, successful build, or isolated SDK fixture does not prove that a machine has been upgraded or that a native user journey succeeds.

## Known limitations to exercise

- The original 8GB laptop has reproduced a long model response ending at 8,192 output tokens with no visible content or created files. Installed request/response settings are under investigation; increasing context is not a verified fix.
- Public PDF ingestion can fail at extraction or reach an approval workflow that chat does not explain correctly.
- Diagnosing a registered local extension can choose a blocked network route and fail to finish its report. Discovery alone is not proof that the extension responds correctly.
- Research and generated applications still require checking the cited facts and actual rendered output. Some completion claims exceed the evidence.
- The upstream isolated browser runtime has passed a disposable navigation/authentication/private-address check. Factory browser provisioning, full access transitions, and clean-install/upgrade/rollback journeys still require native qualification.

When reporting a test, include the installed beta commit, machine/OS/GPU, model and context settings, the task, the observed result, and any artifact or screenshot. Keep credentials and private documents out of public reports. Preserve hardware-specific settings when comparing machines; shared source does not require identical model configurations.
