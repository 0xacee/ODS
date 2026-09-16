import './portal-agent-experience.css'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import PortalInlineCitation from './PortalInlineCitation'

export default function PortalStreamingText({children, active=false, components={}}) {
  return <div className={`portal-streaming-text ${active?'is-streaming':''}`}>
    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]} components={{...components,a:PortalInlineCitation}}>{children}</ReactMarkdown>
    {active && <span className="portal-stream-cursor" aria-hidden="true"/>}
  </div>
}
