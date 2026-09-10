const DATABASE = 'ods-wallpapers-v1'
const STORE = 'images'
export const CUSTOM_WALLPAPER_EVENT = 'ods:wallpapers-changed'
export const isCustomWallpaper = id => typeof id === 'string' && /^custom-[a-f0-9-]{36}$/.test(id)

async function transact(mode, action) {
  if (!globalThis.indexedDB) throw new Error('Wallpaper storage is unavailable in this browser.')
  const db = await new Promise((resolve, reject) => {
    const request = globalThis.indexedDB.open(DATABASE, 1)
    let blocked = false
    request.onblocked = () => { blocked = true; reject(new Error('Close other ODS tabs and try adding the wallpaper again.')) }
    request.onupgradeneeded = () => request.result.createObjectStore(STORE, {keyPath:'id'})
    request.onsuccess = () => { if (blocked) request.result.close(); else resolve(request.result) }
    request.onerror = () => reject(new Error('Wallpaper storage is unavailable in this browser.'))
  })
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, mode)
      const request = action(tx.objectStore(STORE))
      tx.oncomplete = () => resolve(request.result)
      tx.onerror = tx.onabort = () => reject(new Error('Could not save wallpapers. Check available browser storage.'))
    })
  } finally { db.close() }
}

export async function readCustomWallpapers() {
  const rows = await transact('readonly', store => store.getAll())
  return rows.filter(row => isCustomWallpaper(row.id) && typeof row.name === 'string' &&
    row.image?.length <= 6 * 1024 * 1024 && /^data:image\/(jpeg|png|webp);base64,[A-Za-z0-9+/]+=*$/.test(row.image))
}

export async function prepareWallpaper(file) {
  if (!file || !['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) throw new Error('Choose a JPG, PNG or WebP image.')
  if (file.size > 20 * 1024 * 1024) throw new Error('Choose an image smaller than 20 MB.')
  let bitmap
  try { bitmap = await createImageBitmap(file, {imageOrientation:'from-image'}) }
  catch { throw new Error('This image could not be opened. Try another wallpaper.') }
  try {
    if (!bitmap.width || !bitmap.height || bitmap.width * bitmap.height > 80000000) throw new Error('This image is too large. Choose a smaller wallpaper.')
    const scale = Math.min(1, 2560 / Math.max(bitmap.width, bitmap.height))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(bitmap.width * scale))
    canvas.height = Math.max(1, Math.round(bitmap.height * scale))
    const context = canvas.getContext('2d')
    if (!context) throw new Error('Image processing is unavailable in this browser.')
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    const image = canvas.toDataURL('image/webp', .86)
    if (image.length > 6 * 1024 * 1024 || !/^data:image\/(webp|png);base64,/.test(image)) throw new Error('The wallpaper could not be resized. Try another image.')
    return {id:`custom-${crypto.randomUUID()}`, name:file.name.replace(/\.[^.]+$/, '').slice(0, 80) || 'My wallpaper', image}
  } finally { bitmap.close() }
}

export async function addCustomWallpaper(file) {
  const row = await prepareWallpaper(file)
  await transact('readwrite', store => store.put(row))
  window.dispatchEvent(new Event(CUSTOM_WALLPAPER_EVENT))
  return row
}

export async function deleteCustomWallpaper(id) {
  if (!isCustomWallpaper(id)) throw new Error('Invalid wallpaper')
  await transact('readwrite', store => store.delete(id))
  window.dispatchEvent(new Event(CUSTOM_WALLPAPER_EVENT))
}
