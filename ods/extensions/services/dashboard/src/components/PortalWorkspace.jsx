import {useEffect,useId,useRef,useState} from 'react'
import {Globe2,FileCode2,FileText,Files,PanelRightClose,PanelRightOpen,RefreshCw,ExternalLink,X,MoreHorizontal,Maximize2,Minimize2} from 'lucide-react'
import {loadSnapshotFiles} from '../lib/pixelArtifacts'
import PixelPreviewSource from './PixelPreviewSource'
import PixelPreviewViewport from './PixelPreviewViewport'
import PixelPreviewHistory from './PixelPreviewHistory'
import PixelSnapshotChanges from './PixelSnapshotChanges'
import PortalFileTree from './PortalFileTree'
import './portal-workspace.css'

export default function PortalWorkspace({preview,before,previews=[],access,title,request,refresh=0,onRefresh,onSelectPreview,onClose,collapsed,onCollapse,onPublish,expanded,onExpand}) {
  const [active,setActive]=useState('preview'),[tabs,setTabs]=useState([]),[manifest,setManifest]=useState(null)
  const [pendingPath,setPendingPath]=useState(null),[missingPath,setMissingPath]=useState(null)
  const manifestKey=`${preview?.siteId}/${preview?.sha256}`
  const files=manifest?.key===manifestKey?manifest.files:null,error=manifest?.key===manifestKey && manifest.error
  const workspaceId=useId()
  const tabDomId=key=>`${workspaceId}-tab-${encodeURIComponent(key)}`
  const panelDomId=key=>`${workspaceId}-panel-${key.startsWith('file:')?'file':key}`
  const [treeOpen,setTreeOpen]=useState(false),[reviewPath,setReviewPath]=useState(null),[options,setOptions]=useState(false),[retry,setRetry]=useState(0)
  const consumed=useRef(null),root=useRef(null)
  useEffect(()=>{
    setTabs([]);setActive(request?.siteId===preview?.siteId && request?.kind==='review'?'review':'preview');setReviewPath(null);setOptions(false);setPendingPath(null);setMissingPath(null)
  },[preview?.siteId])
  useEffect(()=>{
    setManifest(null)
    if(!preview)return
    let current=true;const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),12000)
    loadSnapshotFiles(preview,controller.signal).then(value=>{if(current)setManifest({key:manifestKey,files:value,error:false})}).catch(()=>{if(current)setManifest({key:manifestKey,files:null,error:true})}).finally(()=>clearTimeout(timer))
    return ()=>{current=false;controller.abort();clearTimeout(timer)}
  },[preview?.siteId,preview?.sha256,preview?.entrySha256,preview?.files,preview?.bytes,refresh,retry])
  function openFile(path) {
    if(!files){setPendingPath(path);return}
    if(!files.some(file=>file.path===path)){setMissingPath(path);return}
    setMissingPath(null)
    setTabs(value=>value.includes(path)?value:[...value,path]);setActive(`file:${path}`);setTreeOpen((root.current?.clientWidth || 0)>=560)
  }
  useEffect(()=>{if(files && pendingPath){openFile(pendingPath);setPendingPath(null)}},[files,pendingPath])
  useEffect(()=>{
    if(!request || request===consumed.current || request.siteId!==preview?.siteId)return
    if(request.kind==='file' && !files)return
    consumed.current=request
    if(request.kind==='file')openFile(request.path)
    else {setPendingPath(null);setMissingPath(null);setActive(request.kind==='review'?'review':'preview');setReviewPath(request.path || null)}
  },[request,preview?.siteId,files])
  const selected=files?.find(file=>`file:${file.path}`===active)
  const fileView=!['preview','review'].includes(active)
  const tabList=[{id:'preview',label:'Preview',Icon:Globe2},{id:'review',label:'Review',Icon:FileCode2},...tabs.map(path=>({id:`file:${path}`,label:path.split('/').at(-1),Icon:FileText}))]
  function switchTab(id) {consumed.current=request;setPendingPath(null);setMissingPath(null);setActive(id);setOptions(false)}
  function closeTab(id) {const path=id.slice(5);setTabs(value=>value.filter(item=>item!==path));if(active===id)setActive('review');setTimeout(()=>root.current?.querySelector('[role=tab][aria-selected=true]')?.focus(),0)}
  return <div ref={root} className="portal-workbench" data-collapsed={collapsed}>
    <header className="portal-workbench-tabs">
      {!collapsed && <div role="tablist" aria-label="Workspace tabs" onKeyDown={event=>{
        if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return
        const index=tabList.findIndex(tab=>tab.id===active)
        const next=event.key==='Home'?0:event.key==='End'?tabList.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabList.length)%tabList.length
        event.preventDefault();switchTab(tabList[next].id)
        event.currentTarget.querySelectorAll('[role=tab]')[next]?.focus()
      }}>{tabList.map(({id,label,Icon})=><div key={id} className="portal-workbench-tab" data-selected={active===id}>
        <button type="button" role="tab" id={tabDomId(id)} aria-controls={panelDomId(id)} aria-selected={active===id} tabIndex={active===id?0:-1} title={id.startsWith('file:')?id.slice(5):undefined} onClick={()=>switchTab(id)}><Icon size={13}/><span>{label}</span></button>
        {!['preview','review'].includes(id) && <button type="button" aria-label={`Close ${id.slice(5)}`} onClick={()=>closeTab(id)}><X size={12}/></button>}
      </div>)}</div>}
      <div className="portal-workbench-window-actions">
        {!collapsed && fileView && <button type="button" aria-label="Browse files" aria-pressed={treeOpen} onClick={()=>setTreeOpen(value=>!value)}><Files size={14}/></button>}
        {!collapsed && <button type="button" title={expanded?'Restore workspace size':'Expand workspace'} aria-label={expanded?'Restore workspace size':'Expand workspace'} onClick={onExpand}>{expanded?<Minimize2 size={14}/>:<Maximize2 size={14}/>}</button>}
        <button type="button" title={collapsed?'Expand preview':'Collapse preview'} aria-label={collapsed?'Expand preview':'Collapse preview'} onClick={onCollapse}>{collapsed?<PanelRightOpen size={14}/>:<PanelRightClose size={14}/>}</button>
        <button type="button" title="Close preview" aria-label="Close preview" onClick={onClose}><X size={14}/></button>
      </div>
    </header>
    {!collapsed && !preview && <section className="portal-workbench-empty"><Files size={24}/><h2>No files to show yet</h2><p>Published files and web previews will appear here.</p>{onPublish && <button type="button" onClick={onPublish}>Ask Portal to publish</button>}</section>}
    {preview && <div className="portal-workbench-body" hidden={collapsed}>
      {missingPath && <p role="status" className="portal-source-notice">This file is not available in this publication. <button type="button" onClick={()=>setMissingPath(null)}>Dismiss</button></p>}
      {pendingPath && <p role="status" className="portal-source-notice">{error?'Files unavailable.':'Opening file…'}{error && <button type="button" onClick={()=>setRetry(value=>value+1)}>Retry</button>}</p>}
      {!fileView && <div className="portal-workbench-toolbar">
        <span className="portal-workbench-location" title={preview.relativeDirectory}>{active==='review'?'Changes':preview.relativeDirectory || 'Web preview'}</span>
        <button type="button" title="Reload preview" aria-label="Reload preview" onClick={onRefresh}><RefreshCw size={14}/></button>
        {active==='preview' && <>
          <button type="button" title="Browse files" aria-label="Browse files" onClick={()=>{setTreeOpen(value=>!value)}} aria-pressed={treeOpen}><Files size={14}/></button>
          <a href={access.url} target="_blank" rel="noopener noreferrer" title="Open preview in a new tab" aria-label="Open preview in a new tab"><ExternalLink size={14}/></a>
        </>}
        <button type="button" aria-label="Workspace options" aria-expanded={options} onClick={()=>setOptions(value=>!value)}><MoreHorizontal size={16}/></button>
      </div>}
      {options && <div className="portal-workbench-options"><PixelPreviewHistory previews={previews} selected={preview} onSelect={onSelectPreview}/><p>Files belong to this published version.</p></div>}
      {/* Retain the frame while reading/reviewing files so its local state survives tab switches. */}
      <div className="portal-workbench-content" id={panelDomId('preview')} role="tabpanel" aria-labelledby={tabDomId('preview')} hidden={active!=='preview'}>
        <PixelPreviewViewport key={`${preview.siteId}/${refresh}`} access={access} title={title} hidden={collapsed || active!=='preview'} compact/>
        {treeOpen && <aside className="portal-workbench-file-tree">{files?<PortalFileTree files={files} selectedPath={null} onSelectFile={path=>openFile(path)} label="Published files" filterLabel="Filter task files"/>:error?<p role="alert">Files unavailable. <button onClick={()=>setRetry(value=>value+1)}>Retry</button></p>:<p role="status">Loading files…</p>}</aside>}
      </div>
      {active==='review' && <div className="portal-workbench-review" id={panelDomId('review')} role="tabpanel" aria-labelledby={tabDomId('review')}><PixelSnapshotChanges key={`${preview.siteId}/${refresh}`} preview={preview} before={before} selectedPath={reviewPath} onSelectFile={path=>setReviewPath(path)} onOpenFile={file=>openFile(file.path)}/></div>}
      {fileView && <div className="portal-workbench-content" id={panelDomId(active)} role="tabpanel" aria-labelledby={tabDomId(active)}>
        <div className="portal-workbench-document">{selected?<PixelPreviewSource key={`${preview.siteId}/${active}/${refresh}`} preview={preview} file={selected} workbench onOpenFile={openFile}/>:<p role="status">{error?'File unavailable.':'Loading file…'}{error && <button type="button" onClick={()=>setRetry(value=>value+1)}>Retry</button>}</p>}</div>
        <aside className="portal-workbench-file-tree" hidden={!treeOpen}>{files && <PortalFileTree files={files} selectedPath={selected?.path} onSelectFile={path=>openFile(path)} label="Published files" filterLabel="Filter task files"/>}</aside>
      </div>}
    </div>}
  </div>
}
