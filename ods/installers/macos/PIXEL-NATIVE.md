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

## Native model bundle qualification

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
