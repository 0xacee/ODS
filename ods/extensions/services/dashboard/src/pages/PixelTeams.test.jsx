import {fireEvent,screen,waitFor} from '@testing-library/react'
import {render} from '../test/test-utils'
import Pixel from './Pixel'

beforeEach(()=>{localStorage.clear();sessionStorage.clear()})
afterEach(()=>{vi.unstubAllGlobals();vi.restoreAllMocks()})
it('turns /agents into a conversational mode and asks the backend to plan without a numeric argument',async()=>{
  let team
  const fetcher=vi.fn(async(url,options)=>{
    const body=options?.body && JSON.parse(options.body)
    let data={available:true,model:'pixel/default'}
    if(url.endsWith('/agents/list'))data={teams:team?[team]:[]}
    if(url.endsWith('/agents/start')){
      team={id:'b'.repeat(32),request_id:body.request_id,goal:body.task,status:'running',agents:[{id:'0',name:'Coordinator',role:'coordinator',task:'Plan the team',status:'running',turn:0,conversation:[]}]};data=team
    }
    return {ok:true,json:async()=>data}
  })
  vi.stubGlobal('fetch',fetcher)
  render(<Pixel/>);await screen.findByText('Available')
  fireEvent.change(screen.getByPlaceholderText('Message Portal...'),{target:{value:'/agents'}})
  expect(screen.getByPlaceholderText('Message Portal...')).toHaveValue('')
  expect(screen.getByRole('button',{name:'Send',exact:true})).toBeDisabled()
  expect(screen.queryByRole('combobox',{name:'Number of agents'})).not.toBeInTheDocument()
  fireEvent.change(screen.getByPlaceholderText('Message Portal...'),{target:{value:'Escreva e revise um anúncio curto'}})
  fireEvent.click(screen.getByRole('button',{name:'Send',exact:true}))
  await screen.findByRole('dialog',{name:'Agent team activity'})
  const payload=JSON.parse(fetcher.mock.calls.find(([url])=>url.endsWith('/agents/start'))[1].body)
  expect(payload.task).toBe('Escreva e revise um anúncio curto')
  expect(payload).not.toHaveProperty('count')
  await waitFor(()=>expect(screen.getByText('Portal is planning the team…')).toBeInTheDocument())
  expect(fetcher.mock.calls.some(([url])=>url.includes('/chat/stream'))).toBe(false)
})

it('runs /goal through the durable controller, answers inline and exposes stop',async()=>{
  let team
  const time='2026-09-15T10:00:00.000Z'
  const activity={schemaVersion:2,runId:'chatcmpl_11111111-2222-4333-8444-555555555555',startedAt:time,finishedAt:time,state:'finished',calls:0,failures:0,blocked:0,truncated:false,activities:[],events:[],context:null,goal:{status:'waiting',summary:'Choose a style',steps:[{id:'work',title:'Create the proposal',status:'pending'}]}}
  const fetcher=vi.fn(async(url,options)=>{
    const body=options?.body && JSON.parse(options.body)
    let data={available:true,model:'pixel/default'}
    if(url.endsWith('/agents/list'))data={teams:team?[team]:[]}
    if(url.endsWith('/agents/start')) {
      team={id:'b'.repeat(32),request_id:body.request_id,goal:body.task,mode:'goal',status:'waiting',agents:[{id:'0',name:'Builder',role:'builder',task:'Do the work',status:'waiting',turn:0,activity,conversation:[],questions:[{id:'style',question:'Qual estilo?',options:['Clean','Colorido']}]}]};data=team
    }
    if(url.endsWith('/agents/answer')){team={...team,status:'running',agents:[{...team.agents[0],status:'running',questions:null}]};data=team}
    if(url.endsWith('/agents/stop')){team={...team,status:'cancelled',agents:[{...team.agents[0],status:'cancelled'}]};data=team}
    return {ok:true,json:async()=>data}
  })
  vi.stubGlobal('fetch',fetcher)
  const view=render(<Pixel/>);await screen.findByText('Available')
  fireEvent.change(screen.getByPlaceholderText('Message Portal...'),{target:{value:'/'}})
  fireEvent.click(screen.getByRole('button',{name:'Goal Plan, work and verify the outcome'}))
  expect(screen.getByPlaceholderText('Message Portal...')).toHaveValue('')
  expect(screen.getByRole('button',{name:'Send',exact:true})).toBeDisabled()
  fireEvent.change(screen.getByPlaceholderText('Message Portal...'),{target:{value:'Escreva uma proposta'}})
  fireEvent.click(screen.getByRole('button',{name:'Send',exact:true}))
  await screen.findByRole('region',{name:'Questions for you'})
  expect(screen.queryByRole('dialog')).toBeNull()
  const payload=JSON.parse(fetcher.mock.calls.find(([url])=>url.endsWith('/agents/start'))[1].body)
  expect(payload).toMatchObject({mode:'goal',task:'Escreva uma proposta'})
  fireEvent.click(screen.getByRole('radio',{name:/Clean/}))
  fireEvent.click(screen.getByRole('button',{name:'Continue',exact:true}))
  await waitFor(()=>expect(fetcher.mock.calls.some(([url])=>url.endsWith('/agents/answer'))).toBe(true))
  const answer=JSON.parse(fetcher.mock.calls.find(([url])=>url.endsWith('/agents/answer'))[1].body)
  expect(answer.answers).toEqual({style:'Clean'})
  view.unmount()
  render(<Pixel/>)
  await screen.findByRole('button',{name:'View goal history'})
  fireEvent.click((await screen.findAllByRole('button',{name:'Stop goal'}))[0])
  await waitFor(()=>expect(fetcher.mock.calls.some(([url])=>url.endsWith('/agents/stop'))).toBe(true))
  expect(fetcher.mock.calls.filter(([url])=>url.endsWith('/agents/start'))).toHaveLength(1)
  expect(fetcher.mock.calls.some(([url])=>url.includes('/chat/stream'))).toBe(false)
})
