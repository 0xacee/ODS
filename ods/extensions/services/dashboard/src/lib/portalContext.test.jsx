import {act,renderHook,waitFor} from '@testing-library/react'
import {compactCommand,historySnapshot,parseConversationContext,usePortalContext} from './portalContext'

const context=(used=1200)=>({schemaVersion:1,status:'ready',sessionRevision:null,model:{id:'small',provider:'local',contextWindow:4096},
  context:{used,window:4096,measuredAt:'2026-09-16T12:00:00.000Z'},compaction:{status:'idle',count:0},history:{revision:null,acknowledgedMessages:2}})
const response=body=>({ok:true,status:200,json:async()=>body})
afterEach(()=>vi.restoreAllMocks())
it('recognizes only exact compaction commands and bounds history by UTF-8 bytes without truncating it',()=>{
  expect(compactCommand(' /COMPACTAR \n')).toBe(true)
  expect(compactCommand('/compact')).toBe(true)
  expect(compactCommand('/compact my work')).toBe(false)
  expect(compactCommand('/compactness')).toBe(false)
  expect(historySnapshot([{role:'assistant',content:'A'.repeat(18000),status:'done'}]).messages[0]).toEqual({role:'assistant',content:'A'.repeat(18000)})
  expect(()=>historySnapshot([{role:'user',content:'😀'.repeat(1024*1024+1)}])).toThrow('4 MB')
  expect(()=>historySnapshot(Array.from({length:2001},()=>({role:'user',content:'x'})))).toThrow('2,000')
})
it('validates context telemetry and accepts a measured zero without inventing one',()=>{
  expect(parseConversationContext(context(0))).toBeTruthy()
  expect(parseConversationContext({...context(),context:{used:-1,window:4096}})).toBeNull()
  expect(parseConversationContext({...context(),compaction:{status:'completed',requestId:'unsafe/path'}})).toBeNull()
  expect(parseConversationContext({...context(),compaction:{status:'completed',requestId:`history-${'a'.repeat(64)}`}})).toBeTruthy()
  expect(parseConversationContext({...context(),context:{used:100,window:4096,measuredAt:'not a date'}})).toBeNull()
})
it('refuses a compaction while the caller reports model switching or active work',async()=>{
  globalThis.fetch=vi.fn();const persist=vi.fn()
  const {result}=renderHook(()=>usePortalContext({chatId:'a',runtimeKey:'small',capacity:4096,blocked:true,onPendingChange:persist}))
  await act(async()=>{expect(await result.current.compact()).toBe(false)})
  expect(persist).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled()
})
it('invalidates measurements on model changes and ignores late results from the previous conversation',async()=>{
  let finish
  globalThis.fetch=vi.fn().mockImplementation(()=>new Promise(resolve=>{finish=()=>resolve(response(context()))}))
  const persist=vi.fn(),props={chatId:'a',runtimeKey:'small',capacity:4096,onPendingChange:persist}
  const {result,rerender}=renderHook(value=>usePortalContext(value),{initialProps:props})
  act(()=>void result.current.refresh(true))
  const old=finish
  rerender({...props,chatId:'b'})
  await act(async()=>old())
  expect(result.current.context).toBeNull()
  globalThis.fetch.mockResolvedValue(response(context()))
  await act(async()=>result.current.refresh(true))
  expect(result.current.context.used).toBe(1200)
  rerender({...props,chatId:'b',runtimeKey:'larger',capacity:8192})
  expect(result.current.context).toBeNull()
  await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(3))
  expect(result.current.context).toBeNull()
})

it('polls a running native compaction to completion without dispatching it again',async()=>{
  vi.useFakeTimers()
  try {
    let id,checks=0
    globalThis.fetch=vi.fn().mockImplementation(async(url,options)=>{
      if(url.endsWith('/compact'))id=JSON.parse(options.body).request_id
      if(url.endsWith('/context'))checks++
      return response({...context(),compaction:{status:checks>=2?'completed':'running',requestId:id,count:checks>=2?1:0}})
    })
    const persist=vi.fn()
    const {result}=renderHook(()=>usePortalContext({chatId:'a',runtimeKey:'small',capacity:4096,onPendingChange:persist}))
    await act(async()=>result.current.compact())
    expect(result.current.busy).toBe(true)
    expect(result.current.phase).toBe('running')
    await act(async()=>vi.advanceTimersByTimeAsync(2000))
    expect(result.current.phase).toBe('completed')
    expect(result.current.busy).toBe(false)
    expect(fetch.mock.calls.filter(([url])=>url.endsWith('/compact'))).toHaveLength(1)
    expect(persist.mock.calls.map(([value])=>value)).toEqual([id,null])
  }finally {vi.useRealTimers()}
})

it('does not recycle old measurements when the model changes but keeps the same context capacity',async()=>{
  let current=context()
  globalThis.fetch=vi.fn().mockImplementation(async()=>response(current))
  const props={chatId:'a',runtimeKey:'first-model',capacity:4096,onPendingChange:vi.fn()}
  const {result,rerender}=renderHook(value=>usePortalContext(value),{initialProps:props})
  await act(async()=>result.current.refresh(true));expect(result.current.context.used).toBe(1200)
  rerender({...props,runtimeKey:'second-model'})
  await act(async()=>{})
  expect(result.current.context).toBeNull()
  current={...context(300),context:{...context(300).context,measuredAt:'2026-09-16T12:10:00.000Z'}}
  await act(async()=>result.current.refresh(true))
  expect(result.current.context.used).toBe(300)
})

it('keeps an unconfirmed request reusable without locking the composer when context storage is unavailable',async()=>{
  const id='11111111-2222-4333-8444-555555555555',persist=vi.fn()
  globalThis.fetch=vi.fn().mockResolvedValue(response({...context(),status:'unavailable',context:null}))
  const {result}=renderHook(()=>usePortalContext({chatId:'a',runtimeKey:'small',capacity:4096,initialRequestId:id,onPendingChange:persist}))
  await waitFor(()=>expect(result.current.phase).toBe('unavailable'))
  expect(result.current.busy).toBe(false)
  expect(persist).not.toHaveBeenCalled()
  await act(async()=>result.current.compact())
  const post=fetch.mock.calls.find(([url])=>url.endsWith('/compact'))
  expect(JSON.parse(post[1].body).request_id).toBe(id)
  expect(persist).not.toHaveBeenCalled()
})

it('accepts hydration compaction telemetry without presenting it as this tab’s manual request',async()=>{
  globalThis.fetch=vi.fn().mockResolvedValue(response({...context(),compaction:{status:'completed',count:2,requestId:`history-${'a'.repeat(64)}`}}))
  const persist=vi.fn()
  const {result}=renderHook(()=>usePortalContext({chatId:'a',runtimeKey:'small',capacity:4096,onPendingChange:persist}))
  await act(async()=>result.current.refresh(true))
  expect(result.current.phase).toBe('idle')
  expect(result.current.notice).toBe('')
  expect(result.current.context.used).toBe(1200)
  expect(persist).not.toHaveBeenCalled()
})

it('never cancels from inspection and requires unknown history plus an explicit recovery action',async()=>{
  let history='ready'
  globalThis.fetch=vi.fn().mockImplementation(async url=>response(url.endsWith('/cancel')?{aborted:true}:{...context(),history:{...context().history,status:history}}))
  const props={chatId:'a',runtimeKey:'small',capacity:4096,onPendingChange:vi.fn(),blocked:false}
  const {result,rerender}=renderHook(value=>usePortalContext(value),{initialProps:props})
  await act(async()=>result.current.refresh(true))
  await act(async()=>expect(await result.current.resolveInterrupted()).toBe(false))
  history='unknown'
  await act(async()=>result.current.refresh(true))
  expect(result.current.historyUnknown).toBe(true)
  expect(result.current.phase).toBe('idle')
  expect(fetch.mock.calls.filter(([url])=>url.endsWith('/cancel'))).toHaveLength(0)
  rerender({...props,blocked:true})
  await act(async()=>expect(await result.current.resolveInterrupted()).toBe(false))
  expect(fetch.mock.calls.filter(([url])=>url.endsWith('/cancel'))).toHaveLength(0)
  rerender(props)
  history='ready'
  await act(async()=>expect(await result.current.resolveInterrupted()).toBe(true))
  expect(fetch.mock.calls.filter(([url])=>url.endsWith('/cancel')).map(([,options])=>JSON.parse(options.body))).toEqual([{chat_id:'a'}])
  expect(result.current.historyUnknown).toBe(false)
})

it.each(['runtime-restarted','result-unconfirmed'])('distinguishes a stopped runtime from an unconfirmed running compaction (%s)',async reason=>{
  const id='11111111-2222-4333-8444-555555555555',persist=vi.fn()
  globalThis.fetch=vi.fn().mockResolvedValue(response({...context(),
    compaction:{status:'unknown',requestId:id,count:0,reason},history:{...context().history,status:'unknown'}}))
  const {result}=renderHook(()=>usePortalContext({chatId:'a',runtimeKey:'small',capacity:4096,initialRequestId:id,onPendingChange:persist}))
  await waitFor(()=>expect(result.current.phase).toBe(reason==='runtime-restarted'?'interrupted':'unknown'))
  expect(result.current.historyUnknown).toBe(true)
  expect(result.current.busy).toBe(reason!=='runtime-restarted')
  expect(result.current.canResolve).toBe(reason==='runtime-restarted')
  if(reason==='runtime-restarted') {
    expect(result.current.notice).toBe('Runtime restarted before compaction could be confirmed. Your conversation is preserved; you can continue.')
    expect(persist).toHaveBeenCalledExactlyOnceWith(null,'a')
  }else expect(persist).not.toHaveBeenCalled()
  expect(fetch.mock.calls.every(([url])=>url==='/api/pixel/chat/context')).toBe(true)
})

it('prefers authoritative session capacity over general status and scopes its measurement to the current runtime',async()=>{
  const measured={...context(3590),model:{...context().model,contextWindow:65536},context:{...context(3590).context,window:65536}}
  let snapshot=measured
  globalThis.fetch=vi.fn().mockImplementation(async()=>response(snapshot))
  const props={chatId:'a',runtimeKey:'first-model',capacity:32768,onPendingChange:vi.fn()}
  const {result,rerender}=renderHook(value=>usePortalContext(value),{initialProps:props})
  await act(async()=>result.current.refresh(true))
  expect(result.current.context).toEqual(measured.context)
  expect(result.current.observedCapacity).toBe(65536)
  snapshot={...measured,context:null}
  await act(async()=>result.current.refresh(true))
  expect(result.current.context).toBeNull()
  expect(result.current.observedCapacity).toBe(65536)
  snapshot=measured
  rerender({...props,runtimeKey:'second-model'})
  expect(result.current.observedCapacity).toBeNull()
  await act(async()=>{})
  expect(result.current.context).toBeNull()
  snapshot={...measured,context:{...measured.context,used:4000,measuredAt:'2026-09-16T12:10:00.000Z'}}
  await act(async()=>result.current.refresh(true))
  expect(result.current.context.used).toBe(4000)
  rerender({...props,chatId:'b',runtimeKey:'second-model'})
  expect(result.current.observedCapacity).toBeNull()
})
