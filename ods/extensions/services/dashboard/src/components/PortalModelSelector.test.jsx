import {act,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {MemoryRouter} from 'react-router-dom'
import PortalModelSelector,{modelDisplayName} from './PortalModelSelector'

const old='community/qwen-4b',target='Qwen/Qwen 3.5 2B'
const technical='extra.hf-HauhauCS-Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q4_K_M-e4a219e5.gguf'
const inventory=[
  {id:old,name:'Qwen3.5-4B-Uncensored-HauhauCS-Aggressive · Q4_K_M',status:'loaded',fitsVram:true,contextLength:32768,quantization:'Q4_K_M'},
  {id:target,name:'Qwen 3.5 2B',status:'downloaded',fitsVram:true,contextLength:8192,quantization:'Q4_K_M'},
  {id:'remote/huge',name:'Large 100B',status:'downloaded',fitsVram:false,contextLength:32768},
  {id:'not-installed',name:'Install me',status:'available',fitsVram:true},
]
let current,ready,postResult,lifecycle
const payload=()=>({models:inventory,currentModel:current,loadedModel:technical,activationReadyModel:ready,odsMode:'lemonade',configuredMode:'lemonade',llmBackend:'lemonade',modelLifecycle:lifecycle,gpu:{vramTotal:8}})
const view=props=><MemoryRouter><PortalModelSelector activeModel={technical} runtimeSource="local-switchboard" {...props}/></MemoryRouter>
beforeEach(()=>{
  current=old;ready=old;postResult={ok:true};lifecycle=null
  vi.stubGlobal('fetch',vi.fn(async (url,options)=>options?.method==='POST'?postResult:{ok:true,json:async()=>payload()}))
})
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals()})
const posts=()=>fetch.mock.calls.filter(([,options])=>options?.method==='POST')
async function open() {
  const button=await screen.findByRole('button',{name:'Choose model: Qwen 3.5 4B'})
  fireEvent.click(button)
  await screen.findByRole('menuitemradio',{name:/Qwen 3.5 2B/})
  return button
}

it('shows readable names and an installed-model menu, with an explicit switch confirmation',async()=>{
  render(view())
  const trigger=await open()
  expect(screen.queryByText(technical)).toBeNull()
  expect(screen.getByRole('menuitemradio',{name:/Uncensored/})).toHaveAttribute('aria-checked','true')
  expect(screen.queryByRole('menuitemradio',{name:/Install me/})).toBeNull()
  expect(screen.getByRole('menuitemradio',{name:/Large 100B/})).toBeDisabled()
  fireEvent.click(screen.getByRole('menuitemradio',{name:/Qwen 3.5 2B/}))
  expect(screen.getByText('This changes the active model across ODS.')).toBeVisible()
  expect(screen.getByRole('button',{name:'Cancel'})).toHaveFocus()
  expect(posts()).toHaveLength(0)
  fireEvent.click(screen.getByRole('button',{name:'Cancel'}))
  fireEvent.keyDown(screen.getByRole('menuitemradio',{name:/Uncensored/}),{key:'ArrowDown'})
  expect(screen.getByRole('menuitemradio',{name:/Qwen 3.5 2B/})).toHaveFocus()
  fireEvent.keyDown(window,{key:'Escape'})
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(screen.getByRole('button',{name:'Choose model: Qwen 3.5 4B'})).toHaveFocus()
  expect(posts()).toHaveLength(0)
})

it('uses the real encoded activation route and waits for readiness instead of marking a POST as success',async()=>{
  vi.useFakeTimers()
  const switching=vi.fn(),settled=vi.fn()
  render(view({onSwitchingChange:switching,onSettled:settled}))
  await act(async()=>{})
  fireEvent.click(screen.getByRole('button',{name:'Choose model: Qwen 3.5 4B'}))
  await act(async()=>{})
  fireEvent.click(screen.getByRole('menuitemradio',{name:/Qwen 3.5 2B/}))
  fireEvent.click(screen.getByRole('button',{name:'Switch model',exact:true}))
  expect(posts()).toHaveLength(1)
  expect(posts()[0][0]).toBe(`/api/models/${encodeURIComponent(target)}/load`)
  expect(posts()[0][1]).toMatchObject({method:'POST',signal:expect.any(AbortSignal)})
  expect(switching).toHaveBeenLastCalledWith(true)
  current=target;ready=null
  await act(async()=>{await vi.advanceTimersByTimeAsync(5000)})
  expect(screen.getByRole('menuitemradio',{name:/Qwen 3.5 2B/})).toHaveAttribute('aria-checked','false')
  expect(settled).not.toHaveBeenCalled()
  ready=target
  await act(async()=>{await vi.advanceTimersByTimeAsync(5000)})
  expect(screen.getByRole('menuitemradio',{name:/Qwen 3.5 2B/})).toHaveAttribute('aria-checked','true')
  expect(switching).toHaveBeenLastCalledWith(false)
  expect(settled).toHaveBeenCalledOnce()
  expect(posts()).toHaveLength(1)
})

it('keeps the current model selected when the host rejects a swap during work',async()=>{
  vi.useFakeTimers()
  postResult={ok:false,status:409,json:async()=>({detail:{code:'pixel_chat_active',message:'Portal is working. Stop the active response before changing models.'}})}
  render(view())
  await act(async()=>{})
  fireEvent.click(screen.getByRole('button',{name:'Choose model: Qwen 3.5 4B'}))
  await act(async()=>{})
  fireEvent.click(screen.getByRole('menuitemradio',{name:/Qwen 3.5 2B/}))
  fireEvent.click(screen.getByRole('button',{name:'Switch model',exact:true}))
  await act(async()=>{await vi.advanceTimersByTimeAsync(5000)})
  expect(screen.getByRole('alert')).toHaveTextContent('Portal is working.')
  expect(screen.getByRole('menuitemradio',{name:/Uncensored/})).toHaveAttribute('aria-checked','true')
  expect(screen.getByRole('menuitemradio',{name:/Qwen 3.5 2B/})).toHaveAttribute('aria-checked','false')
})

it('prevents a pending confirmation from switching models after a task starts',async()=>{
  const {rerender}=render(view())
  await open()
  fireEvent.click(screen.getByRole('menuitemradio',{name:/Qwen 3.5 2B/}))
  rerender(view({busy:true}))
  expect(screen.getByRole('button',{name:'Switch model',exact:true})).toBeDisabled()
  fireEvent.click(screen.getByRole('button',{name:'Switch model',exact:true}))
  expect(posts()).toHaveLength(0)
})

it('routes remote-provider conversations to their settings instead of switching an unrelated local model',async()=>{
  render(view({runtimeSource:'remote-provider',activeModel:'gpt-5.2'}))
  fireEvent.click(screen.getByRole('button',{name:'Choose model: gpt 5.2'}))
  await waitFor(()=>expect(screen.getByRole('menuitemradio',{name:/Qwen 3.5 2B/})).toBeDisabled())
  expect(screen.getByRole('link',{name:'Provider settings'})).toHaveAttribute('href','/pixel/settings?section=connections')
  expect(screen.getByRole('menuitemradio',{name:/gpt 5.2/})).toHaveAttribute('aria-checked','true')
  expect(posts()).toHaveLength(0)
})

it.each([undefined,'unrecognized-source'])('blocks local activation until runtime source %s is confirmed',async runtimeSource=>{
  const {rerender}=render(view({runtimeSource,activeModel:'Remote Chat Model'}))
  fireEvent.click(screen.getByRole('button',{name:'Choose model: Remote Chat Model'}))
  const targetOption=await screen.findByRole('menuitemradio',{name:/Qwen 3.5 2B/})
  expect(targetOption).toBeDisabled()
  expect(screen.getByRole('button',{name:'Choose model: Remote Chat Model'})).toBeVisible()
  expect(screen.getByRole('menuitemradio',{name:/Remote Chat Model/})).toHaveAttribute('aria-checked','true')
  expect(screen.getByRole('menuitemradio',{name:/Uncensored/})).toHaveAttribute('aria-checked','false')
  expect(screen.getByRole('link',{name:'Manage models'})).toHaveAttribute('href','/models')
  fireEvent.click(targetOption)
  expect(screen.queryByRole('button',{name:'Switch model',exact:true})).toBeNull()
  expect(posts()).toHaveLength(0)
  rerender(view({runtimeSource:'local-switchboard'}))
  expect(screen.getByRole('menuitemradio',{name:/Qwen 3.5 2B/})).toBeEnabled()
  expect(screen.getByRole('button',{name:'Choose model: Qwen 3.5 4B'})).toBeVisible()
})

it('keeps chat available while another model downloads, while preventing a concurrent swap',async()=>{
  lifecycle={active:true,operation:'model_download',modelId:'another-model'}
  const switching=vi.fn()
  render(view({onSwitchingChange:switching}))
  await open()
  expect(screen.getByRole('menuitemradio',{name:/Qwen 3.5 2B/})).toBeDisabled()
  expect(switching).toHaveBeenLastCalledWith(false)
  expect(switching).not.toHaveBeenCalledWith(true)
  expect(screen.queryByText('Switching…')).toBeNull()
  expect(posts()).toHaveLength(0)
})

it.each([
  [technical,true,'Qwen 3.5 4B'],
  ['Qwen2.5-0.5B-Instruct-GGUF · Q4_K_M',true,'Qwen 2.5 0.5B'],
  ['DeepSeek-R1-Distill-Qwen-7B',true,'DeepSeek R 1 Distill Qwen 7B'],
  ['My Custom Model',false,'My Custom Model'],
])('formats %s without changing the model identifier', (name,compact,expected)=>{
  const model={id:'exact/model-id',name}
  expect(modelDisplayName(model,compact)).toBe(expected)
  expect(model.id).toBe('exact/model-id')
})

it('does not request or poll the model catalog until the selector is first opened',async()=>{
  vi.useFakeTimers()
  const {rerender}=render(view())
  await act(async()=>{await vi.advanceTimersByTimeAsync(60000)})
  expect(fetch).not.toHaveBeenCalled()
  rerender(view({activeModel:'Qwen3.5-2B'}))
  expect(screen.getByRole('button',{name:'Choose model: Qwen 3.5 2B'})).toBeVisible()
  expect(fetch).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button',{name:'Choose model: Qwen 3.5 2B'}))
  await act(async()=>{})
  expect(fetch).toHaveBeenCalledWith('/api/models',expect.any(Object))
  fireEvent.keyDown(window,{key:'Escape'})
  expect(screen.queryByRole('dialog')).toBeNull()
  const reads=fetch.mock.calls.length
  await act(async()=>{await vi.advanceTimersByTimeAsync(30000)})
  expect(fetch.mock.calls.length).toBeGreaterThan(reads)
})
