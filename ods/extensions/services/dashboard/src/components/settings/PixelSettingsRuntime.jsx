import usePixelSettingsRuntime from './usePixelSettingsRuntime'

export default function PixelSettingsRuntime({ savedRevision, saving, blocked, onBusyChange }) {
  const { runtime, running, stale, error, notice, stage, inspect, change } = usePixelSettingsRuntime({ savedRevision, saving, blocked, onBusyChange })
  const canApply = !running && !saving && !blocked && !stale &&
    ['not-applied', 'saved-changes', 'restored'].includes(runtime?.status) && runtime.settingsRevision === savedRevision
  const canRecover = !running && !saving && !stale && runtime?.status === 'pending'
  const caps = !stale && runtime?.capabilities
  const mismatch = runtime && runtime.status !== 'unavailable' && runtime.status !== 'pending' &&
    savedRevision !== null && runtime.settingsRevision !== savedRevision
  const descriptions = {
    'not-applied': 'No current applied-settings verification is available.',
    restored: 'Previous runtime configuration is restored and verified. Saved preferences are not applied.',
    applied: `Saved revision ${runtime?.settingsRevision} is applied and verified.`,
    'saved-changes': `Runtime revision ${runtime?.appliedRevision} is verified; saved revision ${runtime?.settingsRevision} is not applied.`,
    pending: 'A settings change is incomplete. Inspect and recover it before applying another change.',
    unavailable: 'Runtime control is unavailable on this installation. Saving preferences is still available.',
  }
  const confirmChange = operation => {
    const message = operation === 'apply'
      ? `Apply saved revision ${savedRevision}? Pixel will restart only when idle. Existing access mode will be preserved.`
      : 'Recover this interrupted change? The controller will finish a verified change or restore the previous configuration; Pixel may restart.'
    if (window.confirm(message)) void change(operation)
  }
  return (
    <section aria-labelledby="pixel-settings-runtime-status-title" className="space-y-3 min-w-0 rounded-lg border border-theme-border p-4">
      <h3 id="pixel-settings-runtime-status-title" className="font-medium">Apply saved preferences</h3>
      <p className="text-sm text-theme-text-muted">Applying restarts an idle Pixel with the saved revision. It does not change sandbox or Full Access mode.</p>
      <div aria-live="polite" className="text-sm space-y-2 break-words">
        {stage && <p role="status">{stage}</p>}
        {!running && stale && <p>Runtime status is unknown or stale. Refresh before changing it.</p>}
        {!stale && runtime && <p>{descriptions[runtime.status]}</p>}
        {!stale && runtime?.reason && <p className="text-theme-text-muted">Status code: {runtime.reason}</p>}
        {!stale && runtime?.lastVerifiedAt && <p>Last runtime verification: {runtime.lastVerifiedAt}</p>}
        {mismatch && <p>Saved preferences and runtime inspection differ. Reload preferences and refresh runtime status.</p>}
        {blocked && <p>Save or cancel edits and reload stale preferences before applying. Recovery does not discard your edits.</p>}
        {error && <p role="alert" className="text-red-600">{error}</p>}
        {notice && <p role="status">{notice}</p>}
      </div>
      {caps && (
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm break-words">
          <div><dt className="text-theme-text-muted">Declared context / output limits</dt><dd>{caps.providerContextTokens.toLocaleString()} / {caps.providerMaxOutputTokens.toLocaleString()} tokens ({caps.capacitySource})</dd></div>
          <div><dt className="text-theme-text-muted">Configured Pixel context / output caps</dt><dd>{caps.activeContextTokens.toLocaleString()} / {caps.activeMaxOutputTokens.toLocaleString()} tokens</dd></div>
          <div><dt className="text-theme-text-muted">Measured backend capacity</dt><dd>{caps.backendContextTokens === null ? 'Not verified' : `${caps.backendContextTokens.toLocaleString()} tokens`}</dd></div>
          <div><dt className="text-theme-text-muted">Qualified reasoning levels</dt><dd>{caps.supportedThinkingLevels.length ? caps.supportedThinkingLevels.join(', ') : 'Not qualified'}</dd></div>
          <div><dt className="text-theme-text-muted">Sampling controls</dt><dd>{caps.samplingSupported ? 'Supported' : 'Not qualified for Apply'}</dd></div>
        </dl>
      )}
      <div className="flex flex-wrap gap-2">
        <button className="rounded border border-theme-border px-3 py-2 text-sm disabled:opacity-40" disabled={Boolean(running) || saving} onClick={inspect}>Refresh runtime status</button>
        <button className="rounded border border-theme-border px-3 py-2 text-sm disabled:opacity-40" disabled={!canApply} onClick={() => confirmChange('apply')}>Apply saved Pixel preferences</button>
        <button className="rounded border border-theme-border px-3 py-2 text-sm disabled:opacity-40" disabled={!canRecover} onClick={() => confirmChange('recover')}>Recover interrupted settings change</button>
      </div>
    </section>
  )
}
