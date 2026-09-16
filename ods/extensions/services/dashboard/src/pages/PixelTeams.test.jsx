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
