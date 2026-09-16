/*!
 * Activity layout adapted from UImaxxing, © 2026 Yogi Suria.
 * Free to use, modify and ship in products, including commercial products.
 * Not for republication as a component library or ML training data.
 * https://uimaxx.ing/r/issue-activity-card.json
 * provenance-mark: uim1-1ea983e5.00acec93
 */
import {Activity, Check, Circle, Clock3, FileSearch, FilePenLine, Globe2, Terminal, AlertCircle, Layers} from 'lucide-react'
import {parseTaskActivity} from '../lib/pixelTaskActivity'
import './portal-agent-experience.css'

const labels = {read:'Reading', run:'Commands / checks', edit:'File edits', browser:'Web / browser', preview:'Preview publication', action:'Operations', agent:'Agent coordination', unknown:'Other tools'}
const icons = {read:FileSearch,run:Terminal,edit:FilePenLine,browser:Globe2,preview:Layers}
export default function PixelLiveActivity({task: raw, active = false}) {
  const task = parseTaskActivity(raw, raw?.runId)
  if (!task) return null
  return <details className="portal-activity-card" open={active || undefined}>
    <summary><Activity size={16}/><span>{active ? 'Live activity' : 'Recorded activity'}</span><span className="portal-activity-count">{task.calls} tool {task.calls===1?'call':'calls'}</span></summary>
    <div className="portal-activity-body">
      {task.events?.length ? <ol className="portal-step-list" aria-label="Execution steps">{task.events.map(event=>{
        const Icon=icons[event.kind] || Circle
        const running=event.state==='running' && active
        const label=event.state==='running' ? active?'Running':'Unconfirmed' : event.state==='completed'?'Finished':event.state==='blocked'?'Blocked':'Failed'
        return <li key={event.sequence} className={running?'is-active':''}>
          <span className="portal-step-icon"><Icon size={15}/></span><div><span>{labels[event.kind]}</span><small>{label}</small></div>
          <span className="portal-step-status" aria-label={label}>{running?<Clock3 size={14}/>:event.state==='completed'?<Check size={14}/>:<AlertCircle size={14}/>}</span>
        </li>
      })}</ol> : <ul className="portal-step-list">{task.activities.map(item=><li key={item.kind}><span>{labels[item.kind]}</span><small>{item.calls}{item.failures?` · ${item.failures} failed`:''}</small></li>)}</ul>}
      {!task.calls && <p>{active?'The runtime started this turn. No tool calls observed yet.':'No tool calls were recorded.'}</p>}
      <p className="portal-activity-note">Observed execution steps · {task.events ? `last ${task.events.length} of ${task.calls} calls` : 'grouped calls'}. Tool activity does not confirm the whole task is complete.{task.truncated?' Recording limit reached.':''}</p>
    </div>
  </details>
}
