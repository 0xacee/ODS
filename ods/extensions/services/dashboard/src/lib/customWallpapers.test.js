import {prepareWallpaper, isCustomWallpaper} from './customWallpapers'
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals()})
it('accepts only opaque custom IDs, not URLs or CSS',()=>{
  expect(isCustomWallpaper('custom-11111111-2222-4333-8444-555555555555')).toBe(true)
  for(const value of ['custom-evil','https://remote/image','url(test)',null]) expect(isCustomWallpaper(value)).toBe(false)
})
it('rejects unsupported formats and oversized images before decoding',async()=>{
  const decode=vi.fn();vi.stubGlobal('createImageBitmap',decode)
  await expect(prepareWallpaper({type:'image/svg+xml',size:20})).rejects.toThrow('JPG')
  await expect(prepareWallpaper({type:'image/png',size:21*1024*1024})).rejects.toThrow('20 MB')
  expect(decode).not.toHaveBeenCalled()
})
it('resizes without cropping, strips source metadata, and releases decoded resources',async()=>{
  const bitmap={width:4000,height:2000,close:vi.fn()},drawImage=vi.fn()
  vi.stubGlobal('createImageBitmap',vi.fn(async()=>bitmap))
  vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage})
  vi.spyOn(HTMLCanvasElement.prototype,'toDataURL').mockReturnValue('data:image/webp;base64,YQ==')
  const row=await prepareWallpaper({name:'Forest.jpg',type:'image/jpeg',size:2048})
  expect(row.name).toBe('Forest');expect(isCustomWallpaper(row.id)).toBe(true)
  expect(drawImage).toHaveBeenCalledWith(bitmap,0,0,2560,1280)
  expect(bitmap.close).toHaveBeenCalledOnce()
})
