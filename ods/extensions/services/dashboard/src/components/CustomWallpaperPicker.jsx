import {useRef, useState} from 'react'
import {useTheme} from '../contexts/ThemeContext'
import {isCustomWallpaper} from '../lib/customWallpapers'

export default function CustomWallpaperPicker() {
  const {theme, addWallpaper, removeWallpaper, wallpaperError} = useTheme()
  const input = useRef(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function run(action) {
    setBusy(true); setError('')
    try { await action() } catch (failure) { setError(failure.message || 'Could not update wallpaper.') }
    finally { setBusy(false) }
  }
  return <div className="custom-wallpaper-actions">
    <input ref={input} type="file" accept="image/jpeg,image/png,image/webp" hidden aria-label="Choose local wallpaper" disabled={busy}
      onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void run(() => addWallpaper(file)) }}/>
    <button type="button" className="btn-secondary" disabled={busy} onClick={() => input.current?.click()}>{busy ? 'Saving wallpaper…' : 'Add wallpaper'}</button>
    {isCustomWallpaper(theme) && <button type="button" className="btn-secondary" disabled={busy} onClick={() => void run(() => removeWallpaper(theme))}>Remove selected wallpaper</button>}
    <p className="wallpaper-note">JPG, PNG or WebP · up to 20 MB. Your images stay in this browser and are never uploaded.</p>
    {(error || wallpaperError) && <p role="alert">{error || wallpaperError}</p>}
  </div>
}
