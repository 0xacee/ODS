import {useState} from 'react'
import {render,screen,fireEvent,waitFor,cleanup} from '@testing-library/react'
import {describe,it,expect,vi,afterEach} from 'vitest'
import PortalAgentDock from './PortalAgentDock'
import {agentCommand,teamMetadata,teamSummary,usePortalTeams} from '../lib/portalTeams'

const id='a'.repeat(32)
const team={id,goal:'Name a cafe',status:'waiting',agents:[
  {id:'0',name:'Builder',task:'Create names',status:'waiting',turn:0,conversation:[{role:'assistant',content:'Choose a style'}],questions:[{id:'style',question:'Which style?',options:['Clean','Playful']}]},
  {id:'1',name:'Reviewer',task:'Check names',status:'queued',turn:0,conversation:[]},
]}
afterEach(()=>{cleanup();sessionStorage.clear();vi.unstubAllGlobals()})
function Fixture({answer=vi.fn(),stop=vi.fn()}) {
  const [selected,select]=useState({teamId:id,agentId:'0'})
  return <PortalAgentDock controller={{teams:[team],selected,select,answer,stop}}/>
}
describe('Portal agent teams',()=>{
  it('parses counts, Portuguese alias and multiline tasks without treating other commands as teams',()=>{
    expect(agentCommand('/agents 3 Write\nand review')).toEqual({task:'3 Write\nand review'})
    expect(agentCommand('/agentes Crie nomes')).toEqual({task:'Crie nomes'})
    expect(agentCommand('/agents Review this').task).toBe('Review this')
    expect(agentCommand('/agentsElse')).toBeNull()
    expect(teamMetadata({role:'user',teamId:id})).toEqual({})
    expect(teamSummary({...team,status:'failed'})).toContain('No result was produced.')
  })
  it('opens each real conversation, retains preference drafts across remount and submits to its exact agent',async()=>{
    const answer=vi.fn();let view=render(<Fixture answer={answer}/>)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio',{name:/Playful/}))
    view.unmount();view=render(<Fixture answer={answer}/>)
    await waitFor(()=>expect(screen.getByRole('radio',{name:/Playful/})).toBeChecked())
    fireEvent.click(screen.getByRole('button',{name:'Continue'}))
    expect(answer).toHaveBeenCalledExactlyOnceWith(id,'0',{style:'Playful'})
    fireEvent.click(screen.getByRole('button',{name:'Reviewer Queued'}))
    expect(screen.getByText('Waiting for its turn; it has not started.')).toBeInTheDocument()
    expect(screen.queryByText('Choose a style')).not.toBeInTheDocument()
    fireEvent.keyDown(window,{key:'Escape'})
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button',{name:'Builder · Your input'}))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
  it('does not send duplicate starts while the request is pending',async()=>{
    let resolveStart,controller
    vi.stubGlobal('fetch',vi.fn(url=>url.endsWith('/start')?new Promise(resolve=>{resolveStart=resolve}):Promise.resolve({ok:true,json:async()=>({teams:[]})})))
    function Hook(){controller=usePortalTeams('chat',true);return <button onClick={()=>controller.start({request_id:'one',count:2,task:'Names'})}>Start</button>}
    render(<Hook/>);fireEvent.click(screen.getByText('Start'));fireEvent.click(screen.getByText('Start'))
    expect(fetch.mock.calls.filter(([url])=>url.endsWith('/start'))).toHaveLength(1)
    resolveStart({ok:true,json:async()=>team})
    await waitFor(()=>expect(controller.launching).toBe(false))
  })
})
