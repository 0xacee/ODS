import {act,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {createHash,webcrypto} from 'node:crypto'
import PortalWorkspace from './PortalWorkspace'
import PixelSnapshotChanges from './PixelSnapshotChanges'
const hash=text=>createHash('sha256').update(text).digest('hex')
const sources={'index.html':'<h1>Demo</h1>','src/app.js':'const answer = 42;','README.md':'# Project\n\n[Source](src/app.js)'}
const files=Object.entries(sources).map(([path,text])=>({path,bytes:new TextEncoder().encode(text).length,sha256:hash(text)}))
const preview={siteId:`site-${'a'.repeat(24)}`,sha256:'a'.repeat(64),entrySha256:hash(sources['index.html']),relativeDirectory:'demo',files:files.length,bytes:files.reduce((n,f)=>n+f.bytes,0)}
const changes=files.map(file=>({path:file.path,change:'published',additions:1,deletions:0,truncated:false,diff:[{type:'add',text:sources[file.path].split('\n')[0],newLine:1,oldLine:null}]}))
const manifest={schemaVersion:1,siteId:preview.siteId,sha256:preview.sha256,files,bytes:preview.bytes}
const comparison={schemaVersion:1,scope:'published-snapshots',siteId:preview.siteId,sha256:preview.sha256,beforeSiteId:null,beforeSha256:null,changes}
const access={url:'/pixel-preview/demo/',frameUrl:'/pixel-preview/demo/',sandbox:'allow-scripts',route:'test'}
const props={preview,previews:[preview],access,title:'Interactive Portal preview',onRefresh:vi.fn(),onClose:vi.fn(),onCollapse:vi.fn(),onExpand:vi.fn()}
beforeEach(()=>{
 vi.stubGlobal('crypto',webcrypto)
 vi.stubGlobal('fetch',vi.fn(async url=>({ok:true,headers:new Map(),arrayBuffer:async()=>new TextEncoder().encode(url.includes('__ods_manifest__')?JSON.stringify(manifest):url.includes('__ods_changes__')?JSON.stringify(comparison):sources[Object.keys(sources).find(path=>url.endsWith('/'+path))]).buffer})))
})
afterEach(()=>vi.unstubAllGlobals())
it('opens the clicked review file, then its source in one closable tab, without reloading the web frame',async()=>{
 const {container,rerender}=render(<PortalWorkspace {...props} request={{siteId:preview.siteId,kind:'review',path:'src/app.js'}}/>)
 expect(await screen.findByLabelText('Diff for src/app.js')).toBeVisible()
 const frame=container.querySelector('iframe')
 fireEvent.click(screen.getByRole('button',{name:'Open file src/app.js'}))
 expect(await screen.findByLabelText('Code for src/app.js')).toHaveTextContent('const answer = 42;')
 expect(screen.getAllByRole('tab',{name:'app.js'})).toHaveLength(1)
 fireEvent.click(screen.getByRole('tab',{name:'Review'}))
 fireEvent.click(await screen.findByRole('button',{name:'Open file src/app.js'}))
 expect(screen.getAllByRole('tab',{name:'app.js'})).toHaveLength(1)
 expect(container.querySelector('iframe')).toBe(frame)
 rerender(<PortalWorkspace {...props} collapsed/>)
 expect(container.querySelector('iframe')).toBe(frame)
 rerender(<PortalWorkspace {...props}/>)
 fireEvent.click(screen.getByRole('button',{name:'Close src/app.js'}))
 expect(screen.queryByRole('tab',{name:'app.js'})).toBeNull()
 expect(screen.getByRole('tab',{name:'Review'})).toHaveAttribute('aria-selected','true')
 expect(await screen.findByLabelText('Diff for src/app.js')).toBeVisible()
})
it('opens verified Markdown and its relative source link, with keyboard tab navigation',async()=>{
 render(<PortalWorkspace {...props}/>)
 fireEvent.click(screen.getByRole('button',{name:'Browse files'}))
 fireEvent.click(await screen.findByRole('button',{name:'Open README.md'}))
 expect(await screen.findByRole('heading',{name:'Project'})).toBeVisible()
 fireEvent.click(screen.getByRole('button',{name:'Source',exact:true}))
 expect(await screen.findByLabelText('Code for src/app.js')).toBeVisible()
 fireEvent.keyDown(screen.getByRole('tab',{name:'app.js'}),{key:'Home'})
 expect(screen.getByRole('tab',{name:'Preview'})).toHaveFocus()
 expect(screen.getByRole('tab',{name:'Preview'})).toHaveAttribute('aria-selected','true')
 expect(screen.queryByRole('button',{name:'Expand all changes'})).toBeNull()
})
it('a chat summary opens the actual selected filename instead of an unrelated preview',async()=>{
 const review=vi.fn(),open=vi.fn()
 render(<PixelSnapshotChanges preview={preview} variant="summary" onReview={review} onPreview={open}/>)
 fireEvent.click(await screen.findByRole('button',{name:/src\/app.js/}))
 expect(review).toHaveBeenCalledWith('src/app.js')
 fireEvent.click(screen.getByRole('button',{name:'Review',exact:true}));expect(review).toHaveBeenLastCalledWith(null)
 fireEvent.click(screen.getByRole('button',{name:/Web preview/}));expect(open).toHaveBeenCalledOnce()
 expect(screen.queryByRole('searchbox')).toBeNull()
})
it('waits for the new publication manifest before consuming a file request',async()=>{
 const nextSource='export const ready = true;',nextFile={path:'src/new.js',bytes:nextSource.length,sha256:hash(nextSource)}
 const nextFiles=[files[0],nextFile],next={...preview,siteId:`site-${'b'.repeat(24)}`,sha256:'b'.repeat(64),files:2,bytes:nextFiles.reduce((n,f)=>n+f.bytes,0)}
 const response=text=>({ok:true,headers:new Map(),arrayBuffer:async()=>new TextEncoder().encode(text).buffer})
 const original=fetch;let release
 fetch=vi.fn(url=>{
  if(!url.includes(next.siteId))return original(url)
  if(!url.includes('__ods_manifest__'))return Promise.resolve(response(nextSource))
  return new Promise(resolve=>{release=()=>resolve(response(JSON.stringify({...manifest,siteId:next.siteId,sha256:next.sha256,files:nextFiles,bytes:next.bytes})))})
 })
 const {rerender}=render(<PortalWorkspace {...props} request={{siteId:preview.siteId,kind:'file',path:'src/app.js'}}/>)
 expect(await screen.findByLabelText('Code for src/app.js')).toBeVisible()
 rerender(<PortalWorkspace {...props} preview={next} request={{siteId:next.siteId,kind:'file',path:nextFile.path}}/>)
 await waitFor(()=>expect(release).toBeTypeOf('function'))
 expect(screen.queryByText('This file is not available in this publication.')).toBeNull()
 expect(screen.queryByRole('tab',{name:'app.js'})).toBeNull()
 await act(async()=>release())
 expect(await screen.findByLabelText('Code for src/new.js')).toHaveTextContent(nextSource)
})
it('preserves an open-file action while a failed manifest is retried',async()=>{
 const original=fetch;let failManifest=true
 fetch=vi.fn(url=>url.includes('__ods_manifest__') && failManifest?Promise.reject(new Error('offline')):original(url))
 render(<PortalWorkspace {...props} request={{siteId:preview.siteId,kind:'review',path:'src/app.js'}}/>)
 fireEvent.click(await screen.findByRole('button',{name:'Open file src/app.js'}))
 expect(await screen.findByText('Files unavailable.')).toBeVisible()
 failManifest=false
 fireEvent.click(screen.getByRole('button',{name:'Retry',exact:true}))
 expect(await screen.findByLabelText('Code for src/app.js')).toHaveTextContent('const answer = 42;')
})
it('does not reopen a pending file after the user has switched tabs',async()=>{
 const original=fetch;let release
 fetch=vi.fn(url=>url.includes('__ods_manifest__')?new Promise(resolve=>{release=()=>resolve(original(url))}):original(url))
 render(<PortalWorkspace {...props} request={{siteId:preview.siteId,kind:'file',path:'src/app.js'}}/>)
 await waitFor(()=>expect(release).toBeTypeOf('function'))
 fireEvent.click(screen.getByRole('tab',{name:'Review'}))
 await act(async()=>release())
 expect(screen.getByRole('tab',{name:'Review'})).toHaveAttribute('aria-selected','true')
 expect(screen.queryByRole('tab',{name:'app.js'})).toBeNull()
})
