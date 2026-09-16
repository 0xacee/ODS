import PortalAgentActivity from './PortalAgentActivity'
import PortalStreamingText from './PortalStreamingText'
import {useEffect,useRef,useState} from 'react'
import {createPortal} from 'react-dom'
import {X,Check,AlertCircle,Clock3,Square,Users} from 'lucide-react'
import PixelQuestions from './PixelQuestions'
import {ACTIVE_TEAMS} from '../lib/portalTeams'

const colors=['#67d9ed','#bb9afa','#f6bd69','#f59cac','#8fddb1','#92aff8']
const states={queued:'Queued',running:'Working',waiting:'Your input',completed:'Finished',failed:'Needs attention',cancelled:'Stopped',skipped:'Skipped',interrupted:'Unconfirmed',stopping:'Stopping'}
export function MiniPortal({index=0,state='queued'}) {
  return <span className="relative inline-flex h-8 w-8 shrink-0 items-center justify-center" aria-hidden="true">
    <svg viewBox="0 0 100 100" className={`h-7 w-7 ${state==='running'?'motion-safe:animate-pulse':''}`}><rect x="19" y="20" width="62" height="60" rx="19" fill={colors[index%colors.length]} transform="rotate(-7 50 50)"/><path d="M40 42v14m20-14v14" stroke="#20232d" strokeWidth="8" strokeLinecap="round"/></svg>
    {state==='completed' && <Check size={11} className="absolute -bottom-0.5 -right-0.5 rounded-full bg-theme-card text-emerald-400"/>}
    {['failed','interrupted'].includes(state) && <AlertCircle size={11} className="absolute bottom-0 right-0 text-amber-400"/>}
  </span>
}
export default function PortalAgentDock({controller,renderApproval}) {
  const {teams,selected,select,error,answer,stop,retry}=controller
  const latest=teams[0],team=teams.find(t=>t.id===selected?.teamId),agent=team?.agents.find(a=>a.id===selected?.agentId)
  const [drafts,setDrafts]=useState({}),[acting,setActing]=useState(false)
  const close=useRef(null),previousFocus=useRef(null),actingRef=useRef(false)
  const draftKey=agent ? `portal-team-answer:${team.id}:${agent.id}:${agent.turn}` : ''
  useEffect(()=>{
    if(!draftKey)return
    try {const value=JSON.parse(sessionStorage.getItem(draftKey));if(value && typeof value==='object' && !Array.isArray(value))setDrafts(v=>({...v,[draftKey]:value}))} catch {}
  },[draftKey])
  function changeDraft(value) {setDrafts(v=>({...v,[draftKey]:value}));try{sessionStorage.setItem(draftKey,JSON.stringify(value))}catch{}}
  useEffect(()=>{
    if(!selected) return
    previousFocus.current=document.activeElement;close.current?.focus()
    const escape=e=>{if(e.key==='Escape')select(null)}
    window.addEventListener('keydown',escape)
    return ()=>{window.removeEventListener('keydown',escape);previousFocus.current?.focus?.()}
  },[Boolean(selected)])
  async function perform(fn) {if(actingRef.current)return;actingRef.current=true;setActing(true);try{await fn()}finally{actingRef.current=false;setActing(false)}}
  if(!latest) return null
  return <>
    {latest.mode!=='goal' && <div className="ml-2 flex min-w-0 items-center -space-x-1" aria-label="Portal agent team">
      {latest.agents.map((item,index)=><button key={item.id} type="button" aria-label={`${item.name} · ${states[item.status] || item.status}`} title={`${item.name} · ${states[item.status] || item.status}`} onClick={()=>select({teamId:latest.id,agentId:item.id})} className="rounded-full bg-transparent transition hover:-translate-y-0.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-theme-accent"><MiniPortal index={index} state={item.status}/></button>)}
    </div>}
    {team && agent && createPortal(<div className="fixed inset-0 z-[80] flex justify-end bg-black/20 p-2" onPointerDown={e=>{if(e.target===e.currentTarget)select(null)}}>
      <section role="dialog" aria-modal="true" aria-label="Agent team activity" className="flex h-full w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-theme-border bg-theme-card text-theme-text shadow-2xl" onKeyDown={e=>{
        if(e.key!=='Tab')return
        const nodes=[...e.currentTarget.querySelectorAll('button:not(:disabled),textarea:not(:disabled),select:not(:disabled),input:not(:disabled),a[href]')]
        if(e.shiftKey && document.activeElement===nodes[0]){e.preventDefault();nodes.at(-1)?.focus()}
        else if(!e.shiftKey && document.activeElement===nodes.at(-1)){e.preventDefault();nodes[0]?.focus()}
      }}>
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-theme-border p-4">
          <div><h2 className="flex items-center gap-2 text-sm font-semibold"><Users size={16}/>Portal team</h2><p className="mt-1 text-xs text-theme-text-muted">{team.agents.filter(a=>a.status==='completed').length} / {team.agents.length} finished · {states[team.status] || team.status}</p></div>
          <button ref={close} type="button" aria-label="Close agent activity" onClick={()=>select(null)} className="rounded-lg p-2 hover:bg-theme-border/30"><X size={18}/></button>
        </header>
        <div className="shrink-0 border-b border-theme-border p-3">
          {teams.length>1 && <select aria-label="Agent team history" value={team.id} onChange={e=>select({teamId:e.target.value,agentId:'0'})} className="mb-2 w-full rounded-lg border border-theme-border bg-theme-bg p-2 text-xs">{teams.map(t=><option key={t.id} value={t.id}>{t.goal.slice(0,75)}</option>)}</select>}
          <p className="line-clamp-3 text-sm leading-relaxed">{team.goal}</p>
          <p className="mt-2 text-xs text-theme-text-muted">Separate conversations · one agent at a time on the shared model.</p>
          <div className="mt-3 flex flex-wrap gap-1" role="group" aria-label="Choose an agent">{team.agents.map((item,index)=><button key={item.id} type="button" aria-label={`${item.name} ${states[item.status]}`} aria-pressed={item.id===agent.id} onClick={()=>select({teamId:team.id,agentId:item.id})} className={`flex items-center gap-1 rounded-xl px-2 py-1 text-xs ${item.id===agent.id?'bg-theme-border/60':'hover:bg-theme-border/30'}`}><MiniPortal index={index} state={item.status}/><span>{item.name}<span className="block text-[10px] text-theme-text-muted">{states[item.status]}</span></span></button>)}</div>
        </div>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain p-4">
          <div className="rounded-xl bg-theme-bg/50 p-3"><h3 className="text-sm font-medium">{agent.name}</h3><p className="mt-1 text-xs leading-relaxed text-theme-text-secondary">{agent.task}</p></div>
          {agent.status==='queued' && <p className="flex items-center gap-2 text-xs text-theme-text-muted"><Clock3 size={14}/>Waiting for its turn; it has not started.</p>}
          {agent.status==='running' && <p role="status" className="text-xs text-theme-text-secondary">Working{agent.activity ? ` · ${agent.activity.calls || 0} tool calls · ${agent.activity.failures || 0} failures` : ' · waiting for model output'}.</p>}
          {agent.runtime_wait && <p role="status" className="text-xs text-amber-300">Waiting for the model runtime to become ready. No new work has been sent.</p>}
          <PortalAgentActivity task={agent.activity} active={agent.status==='running'}/>
          {agent.conversation.map((message,index)=><article key={index} className={`min-w-0 rounded-xl p-3 ${message.role==='user'?'bg-theme-bg/60':'border border-theme-border/50'}`}><p className="mb-2 text-[10px] uppercase tracking-wider text-theme-text-muted">{message.role==='user'?'Assignment / owner input':agent.name}</p><div className="prose prose-sm prose-invert max-w-none break-words text-theme-text [&_pre]:overflow-x-auto"><PortalStreamingText>{message.content}</PortalStreamingText></div></article>)}
          {agent.output && <div aria-label="Agent live response" className="prose prose-sm prose-invert max-w-none break-words text-theme-text"><PortalStreamingText active={agent.status==='running'}>{agent.output}</PortalStreamingText></div>}
          {renderApproval && agent.conversation.filter(m=>m.role==='assistant').map((message,index)=><div key={index}>{renderApproval(message.content)}</div>)}
          {agent.questions && agent.status==='waiting' && <PixelQuestions key={draftKey} questions={agent.questions} answers={drafts[draftKey] || {}} onChange={changeDraft} disabled={acting} onSubmit={()=>perform(()=>answer(team.id,agent.id,drafts[draftKey]))}/>}
          {(agent.error || team.notice || error) && <p role="alert" className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs leading-relaxed">{error || agent.error || team.notice}</p>}
          {agent.retryable && <button type="button" disabled={acting} onClick={()=>perform(()=>retry(team.id,agent.id))} className="rounded-lg border border-theme-border px-3 py-2 text-sm hover:bg-theme-border/30 disabled:opacity-50">Retry this agent</button>}
        </div>
        {ACTIVE_TEAMS.has(team.status) && <footer className="border-t border-theme-border p-3"><button type="button" disabled={acting} onClick={()=>perform(()=>stop(team.id))} className="flex items-center gap-2 rounded-lg border border-theme-border px-3 py-2 text-xs hover:bg-theme-border/30 disabled:opacity-50"><Square size={12}/>{team.status==='stopping'?'Confirm stop':'Stop team'}</button></footer>}
      </section>
    </div>,document.body)}
  </>
}
