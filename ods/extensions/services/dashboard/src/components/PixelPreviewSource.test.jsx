import { webcrypto, createHash } from 'node:crypto'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import PixelPreviewSource from './PixelPreviewSource'
const source = '<!doctype html><button onclick="alert(1)">Click</button>\n```\n<script>bad()</script>'
const preview = { siteId:'site-'+'a'.repeat(24), entrySha256:createHash('sha256').update(source).digest('hex') }
beforeEach(() => { vi.stubGlobal('crypto', webcrypto) })
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })
it('verifies exact snapshot bytes and renders HTML as inert highlighted code', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,arrayBuffer:async () => new TextEncoder().encode(source).buffer})))
  const {container} = render(<PixelPreviewSource preview={preview}/>)
  await waitFor(() => expect(screen.getByRole('button',{name:'Copy code'})).toBeEnabled())
  expect(container.querySelector('pre code').textContent).toContain(source)
  expect(container.querySelector('.pixel-code-block .code-language-badge')).toHaveTextContent('HTML')
  expect(container.querySelectorAll('.code-line')).toHaveLength(source.split('\n').length)
  expect(container.querySelectorAll('.code-line')[1]).toHaveAttribute('data-line','2')
  expect(container.querySelector('script')).toBeNull()
  expect(screen.queryByRole('button',{name:'Click'})).toBeNull()
  expect(fetch).toHaveBeenCalledWith(`/pixel-preview/${preview.siteId}/`,expect.objectContaining({cache:'no-store'}))
})
it('does not show mismatching or failed snapshot content', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,arrayBuffer:async () => new TextEncoder().encode('wrong content').buffer})))
  const {container} = render(<PixelPreviewSource preview={preview}/>)
  expect(await screen.findByRole('alert')).toHaveTextContent('could not be verified')
  expect(container.querySelector('pre')).toBeNull()
  expect(screen.getByRole('button',{name:'Copy code'})).toBeDisabled()
})
it('rejects arbitrary source destinations before fetching', async () => {
  vi.stubGlobal('fetch',vi.fn())
  render(<PixelPreviewSource preview={{...preview,siteId:'../../settings'}}/>)
  expect(await screen.findByRole('alert')).toBeVisible()
  expect(fetch).not.toHaveBeenCalled()
})

it('clears a clipboard refusal after a successful retry without refetching source', async () => {
  const writeText = vi.fn().mockRejectedValueOnce(new Error('Clipboard denied')).mockResolvedValueOnce(undefined)
  vi.stubGlobal('navigator', {clipboard: {writeText}})
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,arrayBuffer:async () => new TextEncoder().encode(source).buffer})))
  render(<PixelPreviewSource preview={preview}/>)
  const copy = screen.getByRole('button',{name:'Copy code'})
  await waitFor(() => expect(copy).toBeEnabled())
  fireEvent.click(copy)
  expect(await screen.findByRole('alert')).toHaveTextContent('Clipboard access failed')
  fireEvent.click(copy)
  await waitFor(() => expect(copy).toHaveTextContent('Copied'))
  expect(screen.queryByRole('alert')).toBeNull()
  expect(writeText).toHaveBeenNthCalledWith(2, source)
  expect(fetch).toHaveBeenCalledOnce()
})

it('does not retain Copied feedback when a later clipboard write fails', async () => {
  const writeText = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error('Clipboard denied'))
  vi.stubGlobal('navigator', {clipboard: {writeText}})
  vi.stubGlobal('fetch', vi.fn(async () => ({ok:true,arrayBuffer:async () => new TextEncoder().encode(source).buffer})))
  render(<PixelPreviewSource preview={preview}/>)
  const copy = screen.getByRole('button',{name:'Copy code'})
  await waitFor(() => expect(copy).toBeEnabled())
  fireEvent.click(copy)
  await waitFor(() => expect(copy).toHaveTextContent('Copied'))
  fireEvent.click(copy)
  await screen.findByRole('alert')
  expect(copy).not.toHaveTextContent('Copied')
  expect(copy).toBeEnabled()
})
