import {useCallback,useEffect,useRef,useState} from 'react'

export const ACTIVE_TEAMS = new Set(['queued','running','waiting','stopping','interrupted'])
export function agentCommand(input) {
  const match=String(input).match(/^\/(?:agents|agentes)(?:\s+([\s\S]*))?$/i)
  return match ? {task:(match[1] || '').trim()} : null
}
export function teamMetadata(message) {
  if(message.role!=='assistant') return {}
  return {...(/^[a-f0-9]{32}$/.test(message.teamId || '') ? {teamId:message.teamId} : {}),
    ...(/^[A-Za-z0-9_-]{1,128}$/.test(message.teamRequestId || '') ? {teamRequestId:message.teamRequestId} : {})}
}
export function teamSummary(team) {
  const completed=team.agents.filter(a=>a.status==='completed').length
  const heading=team.agents[0]?.role==='coordinator' ? 'Portal is planning the team…' : `Agent team · ${completed}/${team.agents.length} finished · ${team.status}`
  if(ACTIVE_TEAMS.has(team.status)) return heading
  const reports=team.agents.map(agent=>{
    const reply=agent.conversation?.filter(m=>m.role==='assistant').at(-1)?.content
    return `**${agent.name} · ${agent.status}**\n${reply?.slice(0,1800) || agent.error || 'No result was produced.'}`
  }).join('\n\n')
  const incomplete=team.agents.some(a=>a.role==='reviewer' && a.status!=='completed') ? '\n\nReview incomplete — earlier outputs have not been independently validated.' : ''
  return `${heading}${incomplete}\n\n${reports}`.slice(0,14000)
}
export async function teamRequest(action,body,signal) {
  const response=await fetch(`/api/pixel/agents/${action}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal})
  const data=await response.json()
  if(!response.ok) throw new Error(typeof data.detail==='string' ? data.detail : 'Agent team request failed. Please retry.')
  return data
}
export function usePortalTeams(chatId,enabled) {
  const [teams,setTeams]=useState([]),[error,setError]=useState(''),[launching,setLaunching]=useState(false)
  const [selected,setSelected]=useState(null),[revision,setRevision]=useState(0)
  const current=useRef(chatId),starting=useRef(false),mutation=useRef(0)
  current.current=chatId
  useEffect(()=>{setTeams([]);setSelected(null);setError('')},[chatId])
  useEffect(()=>{
    if(!enabled) return
    const abort=new AbortController();let timer
    async function poll() {
      const version=mutation.current
      try {
        const data=await teamRequest('list',{chat_id:chatId},abort.signal)
        if(abort.signal.aborted || current.current!==chatId) return
        if(!Array.isArray(data.teams)) throw new Error('Agent state is unavailable')
        if(version===mutation.current){setTeams(data.teams);setError('')}
        timer=setTimeout(poll,data.teams.some(t=>ACTIVE_TEAMS.has(t.status)) ? 1600 : 10000)
      } catch(e) {if(!abort.signal.aborted){setError(e.message);timer=setTimeout(poll,4000)}}
    }
    poll()
    return ()=>{abort.abort();clearTimeout(timer)}
  },[chatId,enabled,revision])
  const update=useCallback(team=>{mutation.current++;setTeams(previous=>[team,...previous.filter(t=>t.id!==team.id)])},[])
  const start=useCallback(async(payload)=>{
    if(starting.current) return null
    starting.current=true;setLaunching(true);setError('')
    try {
      const team=await teamRequest('start',{...payload,chat_id:chatId})
      if(current.current===chatId){update(team);setSelected({teamId:team.id,agentId:'0'});setRevision(v=>v+1)}
      return team
    } catch(e){if(current.current===chatId)setError(e.message);throw e}
    finally {starting.current=false;setLaunching(false)}
  },[chatId,update])
  const act=useCallback(async(action,payload)=>{
    try {const team=await teamRequest(action,payload);if(current.current===chatId){update(team);setError('');setRevision(v=>v+1)}}
    catch(e){if(current.current===chatId)setError(e.message)}
  },[chatId,update])
  return {teams,error,launching,selected,select:setSelected,start,
    busy:launching || teams.some(t=>ACTIVE_TEAMS.has(t.status)),
    stop:teamId=>act('stop',{team_id:teamId}),
    retry:(teamId,agentId)=>act('retry',{team_id:teamId,agent_id:agentId}),
    answer:(teamId,agentId,answers)=>act('answer',{team_id:teamId,agent_id:agentId,answers})}
}
