// Closed, content-free projection. This is telemetry, never proof of task success.
export function parseTaskActivity(value, runId) {
  const keys = (item, expected) => item && typeof item === 'object' && !Array.isArray(item)
    && Object.keys(item).sort().join(',') === expected.split(',').sort().join(',');
  const timestamp = item => typeof item === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(item)
    && Number.isFinite(Date.parse(item)) && new Date(item).toISOString() === item;
  const count = item => Number.isInteger(item) && item >= 0 && item <= 512;
  const extended = value?.schemaVersion === 2;
  if (!keys(value,'schemaVersion,runId,startedAt,finishedAt,state,calls,failures,blocked,truncated,activities' + (extended ? ',events,context,goal' : ''))
    || ![1,2].includes(value.schemaVersion) || value.runId !== runId
    || typeof runId !== 'string' || !/^chatcmpl_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(runId)
    || !timestamp(value.startedAt) || !['running','completed','failed','finished'].includes(value.state)
    || (value.state === 'running' ? value.finishedAt !== null : !timestamp(value.finishedAt) || value.finishedAt < value.startedAt)
    || !count(value.calls) || !count(value.failures) || !count(value.blocked)
    || typeof value.truncated !== 'boolean' || !Array.isArray(value.activities) || value.activities.length > 8) return null;
  if (extended) {
    if (value.goal !== null) {
      const goal=value.goal, ids=new Set();
      const text=(s,n)=>typeof s==='string' && s.trim().length>0 && s.length<=n && !/[\u0000-\u001f\u007f]/.test(s);
      if (!keys(goal,'status,summary,steps') || !['active','completed','blocked','waiting'].includes(goal.status)
        || !text(goal.summary,300) || !Array.isArray(goal.steps) || goal.steps.length>8) return null;
      for(const step of goal.steps) {
        if(!keys(step,'id,title,status') || typeof step.id !== 'string' || !/^[a-z][a-z0-9_]{0,31}$/.test(step.id) || ids.has(step.id)
          || !text(step.title,160) || !['pending','running','completed','blocked'].includes(step.status))return null;
        ids.add(step.id);
      }
      if(goal.status==='completed' && (!goal.steps.length || goal.steps.some(step=>step.status!=='completed')))return null;
    }
    if (!Array.isArray(value.events) || value.events.length !== Math.min(value.calls,24)) return null;
    let sequence = value.calls - value.events.length;
    for (const event of value.events) {
      if (!keys(event,'sequence,kind,state,startedAt,finishedAt') || event.sequence !== ++sequence
        || !['read','agent','run','edit','browser','preview','action','unknown'].includes(event.kind)
        || !['running','completed','failed','blocked'].includes(event.state)
        || !timestamp(event.startedAt) || event.startedAt < value.startedAt
        || (event.state === 'running' ? event.finishedAt !== null : !timestamp(event.finishedAt) || event.finishedAt < event.startedAt)) return null;
    }
    const context = value.context;
    const tokens = n => Number.isSafeInteger(n) && n >= 1 && n <= 10_000_000;
    if (context !== null && (!keys(context,'used,window,measuredAt') || !tokens(context.used)
      || !tokens(context.window) || !timestamp(context.measuredAt) || context.measuredAt < value.startedAt)) return null;
  }
  const seen = new Set();
  let calls = 0, failures = 0, blocked = 0;
  for (const item of value.activities) {
    if (!keys(item,'kind,calls,failures,blocked') || !['read','agent','run','edit','browser','preview','action','unknown'].includes(item.kind)
      || seen.has(item.kind) || !count(item.calls) || item.calls === 0 || !count(item.failures) || !count(item.blocked)
      || item.blocked > item.failures || item.failures > item.calls) return null;
    seen.add(item.kind); calls += item.calls; failures += item.failures; blocked += item.blocked;
  }
  return calls === value.calls && failures === value.failures && blocked === value.blocked ? value : null;
}

export function parseTaskActivityFrame(frame) {
  if (frame?.object === 'ods.task.activity' && Object.keys(frame).sort().join(',') === 'id,object,pixel_task') {
    const task = parseTaskActivity(frame.pixel_task, frame.id);
    return task?.state === 'running' ? task : null;
  }
  if (frame?.choices?.[0]?.finish_reason !== 'stop') return null;
  return parseTaskActivity(frame.pixel_task, frame.id);
}
