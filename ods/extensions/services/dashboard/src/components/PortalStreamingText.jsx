import './portal-agent-experience.css'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import PortalInlineCitation from './PortalInlineCitation'
import {useRef,useMemo} from 'react'

// Fade only newly delivered text nodes. Content is never queued, timed out,
// split into artificial tokens or delayed behind the animation.
function revealNewText({boundaries}) {
  return tree=>{
    function visit(node,insideCode=false) {
      if(!node.children)return
      const code=insideCode || ['pre','code'].includes(node.tagName)
      node.children=node.children.flatMap(child=>{
        if(child.type!=='text' || code){visit(child,code);return [child]}
        const start=child.position?.start?.offset
        if(!Number.isInteger(start))return [child]
        const cuts=[0,...boundaries.filter(n=>n>start && n<start+child.value.length).map(n=>n-start),child.value.length]
        return cuts.slice(0,-1).map((cut,i)=>({type:'element',tagName:'span',properties:{className:['portal-stream-reveal'],'data-stream-offset':start+cut},children:[{type:'text',value:child.value.slice(cut,cuts[i+1])}]}))
      })
    }
    visit(tree)
  }
}

function StreamSpan({node,...props}) {return <span {...props}/>}
const EMPTY_COMPONENTS={}
export default function PortalStreamingText({children, active=false, components=EMPTY_COMPONENTS}) {
  const received=useRef({text:'',boundaries:[0]})
  const source=String(children ?? '')
  if(source!==received.current.text) {
    const previous=received.current
    received.current={text:source,boundaries:source.startsWith(previous.text)?[0,...previous.boundaries.filter(n=>n!==0 && n!==previous.text.length).slice(-254),...(previous.text.length?[previous.text.length]:[])]:[0]}
  }
  const boundaries=received.current.boundaries
  const plugins=useMemo(()=>[rehypeHighlight,[revealNewText,{boundaries}]],[boundaries])
  const renderers=useMemo(()=>({...components,a:PortalInlineCitation,span:StreamSpan}),[components])
  return <div className={`portal-streaming-text ${active?'is-streaming':''}`} aria-busy={active}>
    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={plugins} components={renderers}>{source}</ReactMarkdown>
    {active && <span className="portal-stream-cursor" aria-hidden="true"/>}
  </div>
}
