/*!
 * Adapted from UImaxxing Counter Progress Ring, © 2026 Yogi Suria.
 * Free to use, modify and ship in products, including commercial products.
 * Not for republication as a component library or ML training data.
 * https://uimaxx.ing/r/counter-progress-ring.json
 * provenance-mark: uim1-1ea983e5.0d5c62d4
 */
import {useId, useState} from 'react'
import './portal-agent-experience.css'

export default function PortalContextRing({context, capacity, capacityLabel='', pending = false}) {
  const id = useId(), [open, setOpen] = useState(false)
  const valid = value => Number.isSafeInteger(value) && value > 0 && value <= 10_000_000
  const measured = context && valid(context.used) && valid(context.window)
  const percent = measured ? Math.round(100 * context.used / context.window) : null
  const window = measured ? context.window : valid(capacity) ? capacity : null
  const detail = measured ? `${percent}% full · ${context.used.toLocaleString()} / ${window.toLocaleString()} tokens used`
    : `Token usage unavailable${window ? ` · ${window.toLocaleString()} token capacity` : ''}`
  return <span className="portal-context" onMouseEnter={()=>setOpen(true)} onMouseLeave={()=>setOpen(false)}>
    <button type="button" className="portal-context-trigger" aria-label={detail} aria-describedby={open ? id : undefined}
      onFocus={()=>setOpen(true)} onBlur={()=>setOpen(false)} onClick={()=>setOpen(true)} onKeyDown={event=>{if(event.key==='Escape')setOpen(false)}}>
      <svg viewBox="0 0 48 48" fill="none" aria-hidden="true"><circle cx="24" cy="24" r="22" strokeWidth="2.8" className="portal-context-track"/>
        {measured && <circle cx="24" cy="24" r="22" pathLength="100" strokeWidth="2.8" className="portal-context-arc" strokeDasharray="100" strokeDashoffset={100-Math.min(percent,100)}/>}
      </svg><span title="Model context window shared by instructions, conversation, tools, and reply">{measured ? `${percent}%` : capacityLabel || '—'}</span>
    </button>
    {open && <span role="tooltip" id={id} className="portal-context-tooltip"><strong>{detail}</strong><small>{measured ? `Last measured model call${pending ? '; this turn is still running' : ''}. Includes instructions, tools and reply. This is not a lifetime total.` : 'The provider has not supplied a measurement for this turn.'}</small></span>}
  </span>
}
