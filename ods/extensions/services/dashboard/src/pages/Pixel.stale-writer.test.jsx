import {act, fireEvent, screen, waitFor, within} from '@testing-library/react'
import {render} from '../test/test-utils'
import {CHAT_KEY, readConversations, saveConversation, SELECT_EVENT} from '../lib/pixelConversations'
// eslint-disable-next-line no-unused-vars
import Pixel from './Pixel'

const original = {schema:1, chatId:'shared-chat', messages:[{role:'user',content:'Original turn'}], draft:'Initial draft'}
const stored = () => JSON.parse(localStorage.getItem(CHAT_KEY))
const resultEvents = 'data: {"choices":[{"delta":{"content":"Final two-tab answer"}}]}\n\ndata: [DONE]\n\n'

async function startDeferredSender() {
  const originalFetch = fetch.getMockImplementation()
  let release
  let terminal = false
  const nextRead = () => new Promise(resolve => {release = resolve})
  fetch.mockImplementation(async (url, options) => {
    if (url === '/api/pixel/chat/result') return {ok:true,json:async()=>({state:terminal?'complete':'active',events:terminal?resultEvents:''})}
    if (url === '/api/pixel/chat/activity') return {ok:true,json:async()=>({state:'active'})}
    if (url !== '/api/pixel/chat/stream') return originalFetch(url, options)
    options.signal.addEventListener('abort',()=>release?.({done:true}),{once:true})
    return {ok:true,status:200,body:{getReader:()=>({read:nextRead,releaseLock(){}})}}
  })
  const sender = render(<Pixel/>)
  await within(sender.container).findByText('Available')
  fireEvent.change(within(sender.container).getByPlaceholderText(/Message Portal/),{target:{value:'Build a site across tabs'}})
  fireEvent.click(within(sender.container).getByTitle('Send'))
  await waitFor(()=>expect(stored().inFlight).toBe(true))
  await waitFor(()=>expect(release).toBeTypeOf('function'))
  return {sender, completeBackend:()=>{terminal=true},
    deliver:async events=>act(async()=>release({done:false,value:new TextEncoder().encode(events)}))}
}

beforeEach(() => {
  localStorage.clear()
  saveConversation(original)
  vi.stubGlobal('fetch', vi.fn(async url => {
    if (url === '/api/pixel/status') return {ok:true,json:async()=>({available:true,model:'pixel/default'})}
    return {ok:false,status:404,json:async()=>({})}
  }))
})
afterEach(() => {vi.unstubAllGlobals(); vi.restoreAllMocks()})

it('opening a second tab on an active request does not overwrite the streaming sender', async () => {
  const originalFetch = fetch.getMockImplementation()
  let finish
  const firstRead = new Promise(resolve => {finish = resolve})
  let read = false
  fetch.mockImplementation(async (url, options) => {
    if (url === '/api/pixel/chat/result') return {ok:true,json:async()=>({state:'active',events:''})}
    if (url === '/api/pixel/chat/activity') return {ok:true,json:async()=>({state:'active'})}
    if (url !== '/api/pixel/chat/stream') return originalFetch(url, options)
    return {ok:true,status:200,body:{getReader:()=>({
      read:async()=>read?{done:true}:(read=true,firstRead),releaseLock(){},
    })}}
  })
  const sender = render(<Pixel/>)
  await within(sender.container).findByText('Available')
  fireEvent.change(within(sender.container).getByPlaceholderText(/Message Portal/), {target:{value:'Build a two-tab check'}})
  fireEvent.click(within(sender.container).getByTitle('Send'))
  await waitFor(()=>expect(stored().inFlight).toBe(true))
  const before = localStorage.getItem(CHAT_KEY)
  const observer = render(<Pixel/>)
  try {
    await within(observer.container).findByText(/The previous request is still active in this chat/)
    expect(localStorage.getItem(CHAT_KEY)).toBe(before)
  } finally {
    observer.unmount()
    await act(async()=>finish({done:false,value:new TextEncoder().encode('data: {"choices":[{"delta":{"content":"Two-tab check completed"}}]}\n\ndata: [DONE]\n\n')}))
  }
  expect(await within(sender.container).findByText('Two-tab check completed')).toBeVisible()
  expect(within(sender.container).queryByRole('button',{name:'Download recovery copy'})).not.toBeInTheDocument()
})

it('allows terminal recovery before the originating SSE drains, including a late partial save',async()=>{
  const {sender,completeBackend,deliver} = await startDeferredSender()
  completeBackend()
  const observer = render(<Pixel/>)
  await within(observer.container).findByText('Final two-tab answer')
  expect(stored().inFlight).toBe(false)
  const recovered = localStorage.getItem(CHAT_KEY)
  await deliver('data: {"choices":[{"delta":{"content":"Final two-tab "}}]}\n\n')
  await within(sender.container).findByText('Final two-tab')
  expect(localStorage.getItem(CHAT_KEY)).toBe(recovered)
  await deliver('data: {"choices":[{"delta":{"content":"answer"}}]}\n\ndata: [DONE]\n\n')
  await waitFor(()=>expect(within(sender.container).queryByText('Working')).not.toBeInTheDocument())
  expect(stored().messages.at(-1)).toMatchObject({content:'Final two-tab answer',status:'done'})
  expect(stored().recoverySource).toBeUndefined()
  expect(within(sender.container).queryByRole('button',{name:'Download recovery copy'})).not.toBeInTheDocument()
  expect(within(observer.container).queryByRole('button',{name:'Download recovery copy'})).not.toBeInTheDocument()
})

it('rejects the late sender after a real user edit in the recovered observer',async()=>{
  const {sender,completeBackend,deliver} = await startDeferredSender()
  completeBackend()
  const observer = render(<Pixel/>)
  await within(observer.container).findByText('Final two-tab answer')
  await within(observer.container).findByText('Available')
  fireEvent.change(within(observer.container).getByPlaceholderText(/Message Portal/),{target:{value:'Keep my next draft'}})
  expect(stored().draft).toBe('Keep my next draft')
  const edited = localStorage.getItem(CHAT_KEY)
  await deliver(resultEvents)
  expect(await within(sender.container).findByRole('button',{name:'Download recovery copy'})).toBeEnabled()
  expect(localStorage.getItem(CHAT_KEY)).toBe(edited)
  expect(stored().messages.at(-1).content).toBe('Final two-tab answer')
})

it('persists recovery after the original mounted sender closes and survives another reload',async()=>{
  const {sender,completeBackend} = await startDeferredSender()
  sender.unmount()
  await act(async()=>{})
  completeBackend()
  const restored = render(<Pixel/>)
  await within(restored.container).findByText('Final two-tab answer')
  expect(stored()).toMatchObject({inFlight:false,interrupted:false,requestId:null})
  restored.unmount()
  const again = render(<Pixel/>)
  expect(await within(again.container).findByText('Final two-tab answer')).toBeVisible()
  expect(fetch.mock.calls.filter(([url])=>url==='/api/pixel/chat/stream')).toHaveLength(1)
})

it('recovers from the latest request snapshot without losing image, context, or preview metadata',async()=>{
  const image = {id:'img-'+'a'.repeat(32),sha256:'b'.repeat(64),media_type:'image/png',bytes:10,width:1,height:1}
  const siteId = 'site-'+'c'.repeat(24)
  const preview = {schemaVersion:1,kind:'ods-pixel-workspace-preview',relativeDirectory:'saved-site',siteId,port:9437,
    url:`http://${siteId}.localhost:9437/${siteId}/`,files:1,bytes:10,sha256:'c'.repeat(64),entrySha256:'d'.repeat(64)}
  const source = {...original,requestId:'recover-metadata',inFlight:true,draft:'Keep this draft',draftImages:[image],
    contextStart:1,compactionRequestId:'11111111-2222-4333-8444-555555555555',preview,workspaceOpen:false,
    futureMetadata:{keep:true},messages:[{role:'user',content:'Inspect image',images:[{id:image.id,sha256:image.sha256}]},
      {role:'assistant',content:'Previous answer',status:'done',publication:preview},
      {role:'user',content:'Finish it'},{role:'assistant',content:'Partial'}]}
  saveConversation(source)
  const originalFetch = fetch.getMockImplementation()
  let finishLookup
  fetch.mockImplementation(async (url, options)=>url==='/api/pixel/chat/result'
    ? {ok:true,json:()=>new Promise(resolve=>{finishLookup=resolve})} : originalFetch(url,options))
  const observer = render(<Pixel/>)
  await waitFor(()=>expect(finishLookup).toBeTypeOf('function'))
  // A sender checkpoint after observer mount must be used by recovery.
  act(()=>saveConversation({...stored(),draft:'Latest saved draft',futureMetadata:{keep:'latest'}}))
  await act(async()=>finishLookup({state:'complete',events:resultEvents}))
  await within(observer.container).findByText('Final two-tab answer')
  expect(stored()).toMatchObject({draft:'Latest saved draft',draftImages:[image],contextStart:1,
    compactionRequestId:source.compactionRequestId,preview,workspaceOpen:false,futureMetadata:{keep:'latest'},inFlight:false})
  expect(stored().messages.slice(0,3)).toEqual(source.messages.slice(0,3))
  expect(within(observer.container).getByPlaceholderText(/Message Portal/)).toHaveValue('Latest saved draft')
})

async function openChat() {
  render(<Pixel/>)
  await screen.findByText('Available')
  return screen.getByPlaceholderText(/Message Portal/)
}

it('preserves newer saved text when an older mounted tab edits its draft', async () => {
  const input = await openChat()
  const newer = {...stored(), messages:[...original.messages,{role:'assistant',content:'New response from another tab'}], draft:'Newer saved draft'}
  act(() => saveConversation(newer))
  const before = localStorage.getItem(CHAT_KEY)
  fireEvent.change(input,{target:{value:'Unsent old-tab draft'}})
  expect(localStorage.getItem(CHAT_KEY)).toBe(before)
  expect(readConversations()[0].draft).toBe('Newer saved draft')
  expect(input).toHaveValue('Unsent old-tab draft')
  expect(await screen.findByRole('button',{name:'Download recovery copy'})).toBeEnabled()
})

it('checks the original conversation even after another tab switches the current pointer', async () => {
  const input = await openChat()
  act(() => {
    saveConversation({...stored(),draft:'Newer library draft'})
    saveConversation({schema:1,chatId:'different-chat',messages:[],draft:'Other task'})
  })
  const before = localStorage.getItem(CHAT_KEY)
  fireEvent.change(input,{target:{value:'Stale edit'}})
  expect(localStorage.getItem(CHAT_KEY)).toBe(before)
  expect(readConversations().find(chat=>chat.chatId==='shared-chat').draft).toBe('Newer library draft')
})

it('does not start a backend task when a newer saved revision appeared before Send', async () => {
  const input = await openChat()
  fireEvent.change(input,{target:{value:'Local send draft'}})
  act(() => saveConversation({...stored(),draft:'Other tab owns this revision'}))
  const before = localStorage.getItem(CHAT_KEY)
  fireEvent.click(screen.getByTitle('Send'))
  await waitFor(()=>expect(screen.queryByText('Working')).not.toBeInTheDocument())
  expect(fetch.mock.calls.some(([url])=>url==='/api/pixel/chat/stream')).toBe(false)
  expect(localStorage.getItem(CHAT_KEY)).toBe(before)
  expect(screen.getByText('This conversation changed in another tab. No task was started. Download a recovery copy, then reload to read the saved version.')).toBeVisible()
  expect(screen.queryByText(/Check browser storage and try again/)).not.toBeInTheDocument()
})

it('starts and saves a new task after another active tab moves the shared pointer', async () => {
  const input = await openChat()
  const originalFetch = fetch.getMockImplementation()
  fetch.mockImplementation(async (url, options) => {
    if (url !== '/api/pixel/chat/stream') return originalFetch(url, options)
    const bytes = new TextEncoder().encode('data: {"choices":[{"delta":{"content":"New task answer"}}]}\n\ndata: [DONE]\n\n')
    let read = false
    return {ok:true,status:200,body:{getReader:()=>({read:async()=>read?{done:true}:(read=true,{done:false,value:bytes}),releaseLock(){}})}}
  })
  fireEvent.click(screen.getByRole('button', {name:'New chat'}))
  const newId = stored().chatId
  expect(newId).not.toBe(original.chatId)
  act(() => saveConversation({...original, draft:'Other active tab'}))
  fireEvent.change(input, {target:{value:'Make a forest page'}})
  fireEvent.click(screen.getByTitle('Send'))
  expect(await screen.findByText('New task answer')).toBeVisible()
  const posts = fetch.mock.calls.filter(([url]) => url === '/api/pixel/chat/stream')
  expect(posts).toHaveLength(1)
  expect(JSON.parse(posts[0][1].body).chat_id).toBe(newId)
  expect(readConversations().find(chat => chat.chatId === original.chatId)).toMatchObject({messages:original.messages,draft:'Other active tab'})
  expect(readConversations().find(chat => chat.chatId === newId).messages.at(-1).content).toBe('New task answer')
  expect(screen.queryByRole('button', {name:'Download recovery copy'})).not.toBeInTheDocument()
})

it('can explicitly select a different saved conversation and continue saving', async () => {
  const input = await openChat()
  act(() => saveConversation({schema:1,chatId:'selected-chat',messages:[],draft:'Selected draft'}))
  act(() => window.dispatchEvent(new CustomEvent(SELECT_EVENT,{detail:'selected-chat'})))
  expect(input).toHaveValue('Selected draft')
  fireEvent.change(input,{target:{value:'Intentional new edit'}})
  expect(stored().draft).toBe('Intentional new edit')
})
