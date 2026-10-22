import { fireEvent, screen, waitFor } from '@testing-library/react'
import { render } from '../test/test-utils'
import ODSTalk from './ODSTalk' // eslint-disable-line no-unused-vars

const encode = value => new TextEncoder().encode(`data: ${JSON.stringify(value)}\n\n`)
const json = body => ({ ok: true, status: 200, json: async () => body })

function stream(frames, { open = false, fail = false, split = false } = {}) {
  const cancel = vi.fn()
  let transport
  const body = new globalThis.ReadableStream({
    start(controller) {
      transport = controller
      for (const frame of frames) {
        const bytes = encode(frame)
        if (split) {
          for (const byte of bytes) controller.enqueue(new Uint8Array([byte]))
        } else controller.enqueue(bytes)
      }
      if (!open && !fail) controller.close()
    },
    cancel,
  })
  return { response: { ok: true, status: 200, body }, body, cancel,
    fail: () => transport.error(new Error('Network connection lost')) }
}

async function start(reply, { spoken = false, attachment = false } = {}) {
  localStorage.setItem('ods-talk-spoken-replies', spoken ? '1' : '0')
  const fetcher = vi.fn(async url => {
    if (url === '/api/talk/status') return json({ capabilities: { text_chat: true, tts: spoken } })
    if (url === '/api/talk/message/stream' || url === '/api/talk/attachment') return reply.response
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.stubGlobal('fetch', fetcher)
  render(<ODSTalk />)
  await screen.findByText('Ready')
  if (attachment) {
    fireEvent.change(document.querySelector('input[type="file"][accept*="image"]'), {
      target: { files: [new File(['reference'], 'notes.txt', { type: 'text/plain' })] },
    })
  }
  fireEvent.change(screen.getByPlaceholderText('Message ODS'), { target: { value: 'Check this answer' } })
  fireEvent.click(screen.getByRole('button', { name: 'Send message' }))
  return fetcher
}

afterEach(() => { localStorage.removeItem('ods-talk-spoken-replies'); vi.unstubAllGlobals() })

it.each([
  ['empty EOF', []],
  ['status-only EOF', [{ type: 'status', label: 'Searching' }]],
  ['done without completion', [{ type: 'done' }]],
])('does not present %s as a successful answer', async (_name, frames) => {
  const reply = stream(frames)
  await start(reply)
  expect(await screen.findByRole('alert')).toHaveTextContent('ended before it was complete')
  expect(screen.getByRole('button', { name: 'Retry last message' })).toBeEnabled()
  expect(reply.body.locked).toBe(false)
})

it.each([false, true])('retains interrupted text and suppresses speech (attachment: %s)', async attachment => {
  const reply = stream([{ type: 'delta', text: 'Received partial answer' }])
  const fetcher = await start(reply, { spoken: true, attachment })
  expect(await screen.findByRole('alert')).toHaveTextContent('ended before it was complete')
  expect(screen.getByText('Received partial answer')).toBeVisible()
  expect(fetcher.mock.calls.some(([url]) => url === '/api/talk/speak')).toBe(false)
  expect(fetcher.mock.calls.some(([url]) => url === (attachment ? '/api/talk/attachment' : '/api/talk/message/stream'))).toBe(true)
})

it('preserves partial text separately from the server failure and permits retry', async () => {
  const reply = stream([{ type: 'delta', text: 'Useful partial result' }, { type: 'error', detail: 'Hermes stopped working.' }, { type: 'done' }])
  await start(reply)
  expect(await screen.findByRole('alert')).toHaveTextContent('Hermes stopped working.')
  expect(screen.getByText('Useful partial result')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Retry last message' })).toBeEnabled()
})

it('retains text if the transport rejects after a delta', async () => {
  const reply = stream([{ type: 'delta', text: 'Result before disconnect' }], { fail: true })
  await start(reply)
  await screen.findByText('Result before disconnect')
  reply.fail()
  expect(await screen.findByRole('alert')).toHaveTextContent('Network connection lost')
  expect(screen.getByText('Result before disconnect')).toBeVisible()
  expect(reply.body.locked).toBe(false)
})

it('finishes at done without waiting for socket closure, cancels unread frames and releases the reader', async () => {
  const reply = stream([{ type: 'delta', text: 'Draft answer' }, { type: 'complete', text: 'Final answer', warning: 'Check the sources.' }, { type: 'done' }, { type: 'delta', text: 'must be ignored' }], { open: true, split: true })
  await start(reply)
  expect(await screen.findByText('Final answer')).toBeVisible()
  expect(screen.getByText('Check the sources.')).toBeVisible()
  await waitFor(() => expect(reply.cancel).toHaveBeenCalledTimes(1))
  expect(reply.body.locked).toBe(false)
  expect(screen.queryByText(/must be ignored/)).toBeNull()
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.queryByRole('button', { name: 'Retry last message' })).toBeNull()
  fireEvent.change(screen.getByPlaceholderText('Message ODS'), { target: { value: 'Next question' } })
  expect(screen.getByRole('button', { name: 'Send message' })).toBeEnabled()
})

it('accepts the authoritative complete receipt when EOF precedes done', async () => {
  const reply = stream([{ type: 'complete', text: 'Complete answer' }])
  await start(reply)
  expect(await screen.findByText('Complete answer')).toBeVisible()
  expect(screen.queryByRole('alert')).toBeNull()
  expect(reply.body.locked).toBe(false)
})