# Legacy OpenClaw extension removed

ODS deprecated its legacy OpenClaw extension on 2026-05-12 and has now removed
it: the `ods-openclaw` container (image `ghcr.io/openclaw/openclaw:2026.3.8`,
port 7860), its configuration and its installer options. Its pinned image had
unresolved critical upstream security advisories.

The supported agents are [Portal (Pixel)](PIXEL.md) on qualified hosts and
[Hermes Agent](HERMES.md). Pixel runs its own OpenClaw runtime as the host
service `openclaw-gateway.service`. That runtime is separate from this
extension and is not affected.

## What an upgrade does

- Rerunning the installer on Linux, macOS or Windows deletes
  `extensions/services/openclaw` from the install directory and removes the
  `ods-openclaw` container when it starts the stack. In a git checkout updated
  with `ods-update.sh update`, `git pull` deletes the files and the restart
  removes the container.
- The installers no longer turn OpenClaw back on when they find its container
  or data.
- `--openclaw` and `--no-openclaw` (Linux and macOS) and `-OpenClaw` (Windows)
  are still accepted. They print a notice and change nothing.
- Installers no longer write `OPENCLAW_TOKEN`, `OPENCLAW_PORT` or `HOST_LAN_IP`
  to `.env`. Linux and Windows reruns rewrite `.env` without them; macOS keeps
  existing values. Retired keys that remain are ignored and still pass `.env`
  validation.
- On AMD Linux installs, a rerun stops and deletes the
  `openclaw-session-cleanup` user timer.

Nothing migrates to Hermes or Portal. OpenClaw sessions, memories and cron jobs
do not transfer. n8n workflows that call port 7860 stop working; the bundled
`config/n8n/hermes-agent-trigger.json` workflow targets Hermes instead.

## What stays on disk

The upgrade deletes no data. These remain until you remove them:

- `data/openclaw/`: agent state. On macOS and Windows,
  `data/openclaw/home/openclaw.json` contains the gateway token, and on macOS
  also a provider key.
- `config/openclaw/`: configuration and `workspace/`. On Strix Halo tiers,
  `openclaw.json` can contain a copy of your LiteLLM key.
- Retired `.env` keys, pre-update backups in `data/backups/` that include a
  `config-openclaw` copy, and the downloaded `ghcr.io/openclaw/openclaw` image.
- On AMD Linux installs, the `memory-shepherd-memory` and
  `memory-shepherd-workspace` user timers, which reset files in
  `config/openclaw/workspace`.

## Removing the leftovers

On Linux or macOS, from the install directory (`~/ods` by default):

```bash
# AMD Linux: stop the timers that maintain the old workspace first.
# They fail on every run once config/openclaw is gone.
for timer in openclaw-session-cleanup memory-shepherd-memory memory-shepherd-workspace; do
    systemctl --user disable --now "$timer.timer" 2>/dev/null
    rm -f ~/.config/systemd/user/"$timer".timer ~/.config/systemd/user/"$timer".service
done
systemctl --user daemon-reload

# Optional: keep a private archive. It contains the secrets listed above.
tar czf ~/openclaw-archive.tgz data/openclaw config/openclaw

rm -rf data/openclaw config/openclaw
docker image rm ghcr.io/openclaw/openclaw:2026.3.8
```

On Linux these folders can belong to UID 1000, the container's user; use
`sudo rm -rf` if `rm` reports permission errors. If `docker ps -a` still lists
`ods-openclaw`, remove it with `docker rm -f ods-openclaw`.

On Windows, from `%USERPROFILE%\ods`:

```powershell
Remove-Item -Recurse -Force data\openclaw, config\openclaw
docker image rm ghcr.io/openclaw/openclaw:2026.3.8
```

You can also delete the retired `OPENCLAW_*`, `HOST_LAN_IP` and
`BOOTSTRAP_MODEL` lines from `.env`; ODS ignores them either way.

### Git checkouts with a changed `openclaw.json`

If ODS runs from a git checkout with OpenClaw enabled, the installer wrote your
model name, and on Strix Halo tiers your LiteLLM key, into the tracked
`config/openclaw/openclaw.json`. `git pull` then refuses to delete it, and
`ods-update.sh update` stops with "Git pull failed." Move the file out of the
checkout, or delete it, and update again:

```bash
mv config/openclaw/openclaw.json ~/openclaw.json.bak
```
