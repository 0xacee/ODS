# Native Pixel transport integration

`pixel-native.compose.yaml.disabled` is a staged installer component, not an
installer entry point or a declaration that macOS host-access parity is ready.
It does not start a gateway, accept a license, or grant host access.

Compose ordering is the ODS base stack, the shared
`extensions/services/pixel-edge/compose.yaml.disabled`, then this native
fragment. Resolve paths relative to the ODS installation directory. Compose
must support `!override`; validate the merged configuration before changing
running services. The shared Edge fragment retains Portal routing, preview
authentication, transition persistence, and Open WebUI defaults.

The installer must supply:

- `PIXEL_NATIVE_UID` and `PIXEL_INGRESS_GID`: the verified native runtime owner's
  numeric identity, not a fixed 501/20 pair.
- `PIXEL_NATIVE_CONFIG_PATH`: an existing private gateway configuration file
  readable by that identity. Missing bind sources must not create directories.
- `PIXEL_NATIVE_INGRESS_IMAGE`: the qualified image containing the Node runtime.
  Its gateway entry point and inherited health check are explicitly replaced.
- `PIXEL_NATIVE_GATEWAY_PORT`: the native loopback listener, default 18789.
- `PIXEL_NATIVE_WORKSPACE`: the existing canonical private workspace, mounted
  read-only by the preview broker. `PIXEL_PREVIEW_PORT` defaults to 9437 and must
  be free on host loopback. The broker uses the same port inside Docker so its
  verified receipt identifies the actual published browser origin.
- Shared Edge keys and preview runtime prerequisites. Compose interpolates the
  shared Linux fragment before applying overrides, so its
  `PIXEL_INGRESS_RUNTIME_DIR` variable must also be set even though that mount
  is replaced by a Docker volume. The same applies to
  `PIXEL_PREVIEW_RUNTIME_DIR`. Neither variable is the native socket path.

Native preview uses the shared snapshot engine in a dedicated non-root image.
The broker receives no Docker socket and can only read the configured workspace
and write its snapshot/runtime volumes. Its HTTP port is published on host
loopback only. Edge receives the preview runtime volume read-only.
The native plugin selects `workspacePreviewTransport: "docker-desktop"` in
installer-owned plugin configuration. This invokes only the fixed
`ods-pixel-workspace-preview` container's bounded `request` command; model input
is JSON on stdin, never a container name, command, or host path. Linux defaults
to the existing Unix-socket transport. Killing the Docker client stops waiting,
not necessarily a publication already accepted by the broker; no receipt is
returned after cancellation. The gateway's Docker authority still requires the
independent qualification described below.

The tool must pass both OpenClaw policy gates. In addition to the global
`tools.allow`, add only `pixel_ods_workspace_preview` to the Pixel agent's
`tools.sandbox.tools.alsoAllow`. Preserve existing deny rules. The default
sandbox allowlist does not include plugin tools; enabling the transport alone
can pass direct plugin tests while leaving the tool unavailable in a real chat.
Do not use `group:plugins`, disable sandboxing, or enable elevated execution to
make preview available. Validate the effective agent policy and a real Portal
tool call after updating configuration.

The initializer owns only the runtime volume's top-level directory. It has no
network or host bind mounts and does not recursively change existing history.
Ingress runs unprivileged and writes history/status and its Unix socket there;
Edge mounts it read-only. Neither service receives the Docker daemon socket.
The native gateway's separate Docker authority remains a security qualification
requirement, not something this transport fragment resolves.

Do not enable this fragment until native deployment custody, gateway lifecycle,
preview/control-plane services and licensing are qualified. Existing local
qualification containers and volumes have different names: migration must
preserve their history and transition state before replacing them. Do not run
`down --volumes` during installation, upgrade or rollback.

Run the configuration contract tests without starting any service:

```sh
python3 -m unittest discover -s ods/tests -p test_pixel_native_compose.py -v
```

These tests validate Compose merging, identity/path/port substitution, retained
Edge contracts and required parameters. They do not prove runtime connectivity,
preview availability, restart recovery or full macOS security equivalence.

## Native process identity

`LaunchdGatewayService.process_identity()` requires an approved deployment
specification (`uid`, `gid`, absolute `executable`). It reads the kernel's
process creation timestamp, effective/real/saved credentials and executable
path through `libproc`, checks for changes during the read, and rechecks the
service PID. Native admission discovery compares this entire identity before
and after HTTP discovery, so reuse of a numeric PID cannot authorize a request.
Missing specification, short API replies, process exit or identity changes
fail closed. Linux retains its existing systemd PID contract.

This does not prove the executable's file custody or signature, absence of
descendants, sandbox policy, script identity or host-access equivalence. It
does not enable the Darwin access bridge. A future protected deployment must
ship `pixel_macos_process.py` alongside the service and custody adapters and
provide the approved specification, not derive approval from an arbitrary
currently running process.

Model/settings/provider transaction identity and restart now dispatch through
the selected service adapter. The receipt shape remains `{pid, started, boot}`.
Linux retains `ExecMainStartTimestampMonotonic` and `/proc`'s boot ID. Darwin
uses the verified process birth time in epoch microseconds plus
`kern.bootsessionuuid`, with identity checked around the boot query. Receipts
are platform-local; their timestamps must not be compared across platforms.
Existing restart rules still require a different PID, the same boot UUID and
a later birth time. A backwards clock adjustment therefore fails closed on
macOS rather than manufacturing a successful restart. This does not port the
remaining provider environment/drop-in logic, isolation boundary, stopped
descendant proof or privileged bridge discovery.

For an opt-in real lifecycle check using an already acquired qualified
OpenClaw runtime (no package download and no production service restart):

```sh
python3 ods/tests/test-macos-pixel-lifecycle.py --node /absolute/path/to/node --openclaw-entrypoint /absolute/path/to/openclaw/openclaw.mjs
```

Run from the source repository as the regular login user. The test creates a
random-label LaunchAgent with private disposable state, no plugins/tools, and
an ephemeral loopback port. It pins Node through OpenClaw's supported
`OPENCLAW_WRAPPER` interface, checks the actual kernel executable identity,
restarts, and removes its own job. OpenClaw's default installer may select a
system Node instead of the runtime used to invoke the CLI. The check requires
version 2026.6.33 unless an explicitly qualified version is supplied with
`--expected-version`. It does not prove reboot recovery or production custody.

## Native model bundle qualification

For a separately qualified runtime with hybrid-model checkpoint support, the
native installer and `ods` restart accept these optional `.env` settings:

```dotenv
LLAMA_ARG_CHECKPOINT_EVERY_NT=1024
LLAMA_ARG_CTX_CHECKPOINTS=8
LLAMA_ARG_CACHE_RAM=512
```

These are an example qualification profile, not universal defaults. Unset
values preserve existing behavior. The selected executable must advertise
each requested option in `--help`; invalid/unsupported settings fail before
the normal native-model replacement step. Existing registered model profiles
retain their own qualified argument lists instead of mixing in these settings.
This does not automatically upgrade the pinned runtime, backport a cache fix,
or make an unqualified runtime safe to distribute. Smaller RAM budgets and
checkpoint limits must still be tested with the selected model and workloads.

Native idle unloading is separately opt-in with
`LLAMA_ARG_SLEEP_IDLE_SECONDS=120` (1..86400 seconds, or `-1` to disable).
The same pre-stop capability validation applies. This uses llama.cpp's own
idle timer, not a process-killing watchdog: active inference stays running,
and a new inference request reloads a sleeping model. Sleep releases the
model and KV/prefix cache, so the first request after sleep is cold and can
be slower. `/health`, `/props`, and `/models` do not wake the model; metrics
scrapes and other tasks can prevent sleep or wake it. Qualify monitoring
traffic as well as chat before enabling this in an installation. This is
workstation memory relief, not a claim of faster inference or a default for
all Macs.

Before distributing a locally compiled flat ARM64 llama.cpp bundle, check its
loader metadata on macOS:

```sh
python3 installers/macos/lib/native-runtime-audit.py --bundle /path/to/bundle --minimum-macos 14.0
```

This rejects external Homebrew/build-directory dependencies, escaping symlinks,
missing companion libraries and deployment targets newer than requested. It
does not execute the binaries or qualify their CPU instructions, code signing,
Metal correctness, TLS features or behavior on older hardware. It is a release
qualification helper, not yet an automatic installer gate. Builds still need
explicit baseline CPU settings and real supported-hardware testing.
