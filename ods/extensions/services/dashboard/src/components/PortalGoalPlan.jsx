import {Check, Circle, CircleDot, ListChecks, AlertCircle} from 'lucide-react'
import {parseTaskActivity} from '../lib/pixelTaskActivity'

export default function PortalGoalPlan({task, active=false, onResume, disabled=false}) {
  const goal=parseTaskActivity(task,task?.runId)?.goal
  if(!goal)return null
  const completed=goal.steps.filter(step=>step.status==='completed').length
  const status=goal.status==='active' && !active ? 'Paused' : {active:'Working toward your goal',completed:'Plan completed',blocked:'Needs attention',waiting:'Waiting for you'}[goal.status]
  return <section className="portal-goal-plan" aria-label="Goal plan">
    <header><ListChecks size={17}/><strong>{status}</strong><span>{goal.steps.length ? `${completed}/${goal.steps.length}` : 'Planning'}</span></header>
    <p>{goal.summary}</p>
    <ol>{goal.steps.map(step=>{
      const Icon=step.status==='completed'?Check:step.status==='running'?CircleDot:step.status==='blocked'?AlertCircle:Circle
      return <li key={step.id} data-state={step.status}><Icon size={16} aria-label={step.status}/><span>{step.title}</span></li>
    })}</ol>
    <footer><small>Progress reported by the agent. Check the result and evidence below.</small>
      {!active && onResume && goal.status!=='completed' && <button type="button" disabled={disabled} onClick={onResume}>Continue goal</button>}
    </footer>
  </section>
}
