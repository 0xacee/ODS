const {chromium} = require('playwright')
const fs = require('fs/promises')
const assert = require('assert/strict')
;(async()=>{
 const browser = await chromium.launch({headless:true})
 const page = await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'})
 page.setDefaultTimeout(12000)
 const errors=[]
 page.on('pageerror',error=>errors.push(error.message))
 await page.route('**/api/**', async route=>{
   const path=new URL(route.request().url()).pathname
   const value=path==='/api/status' ? {gpu:null,services:[],model:null,bootstrap:null,uptime:0,version:'beta',inference:{}}
     :path==='/api/pixel/status' ? {available:true,model:'pixel/default',detail:'local'}
     :path==='/api/setup/status' ? {first_run:false}
     :path==='/api/external-links' ? [] : {}
   await route.fulfill({json:value})
 })
 await page.addInitScript(()=>{
   localStorage.setItem('ods.pixel.conversations.v1',JSON.stringify([
     {schema:1,chatId:'bad-record',messages:[null],updatedAt:1},
     {schema:1,chatId:'browser-export',messages:Array.from({length:80},(_,index)=>({role:index%2?'assistant':'user',content:'Browser turn '+index})),draft:'Retained draft',updatedAt:2}
   ]))
 })
 await page.goto(process.env.ODS_REVIEW_URL || 'http://127.0.0.1:18245')
 await page.getByRole('dialog',{name:'ODS',exact:true}).waitFor({state:'hidden'})
 await page.getByRole('button',{name:'Export chat: Browser turn 0'}).waitFor()
 console.log('LOADED',await page.title(),errors)
 await page.screenshot({path:'before-export.png'})
 await page.locator('.conversation-row').filter({has:page.getByRole('button',{name:'Export chat: Browser turn 0'})}).hover()
 const [download]=await Promise.all([
   page.waitForEvent('download'),
   page.getByRole('button',{name:'Export chat: Browser turn 0'}).click({timeout:5000}).catch(async e=>{console.log('CLICK',e.message,await page.locator('body').innerText());throw e})
 ])
 assert.equal(download.suggestedFilename(),'ods-pixel-browser-export.json')
 const archive=JSON.parse(await fs.readFile(await download.path(),'utf8'))
 assert.equal(archive.conversation.messages.length,80)
 assert.equal(archive.conversation.draft,'Retained draft')
 console.log('PASS real Chromium download: complete 80-message JSON beside malformed history')
 const input=page.getByPlaceholder('Message Pixel...')
 await input.fill('Keep this draft')
 await input.focus()
 await page.keyboard.press('Control+k')
 const search=page.getByRole('textbox',{name:'Search conversations and actions'})
 await search.fill('Research')
 await page.keyboard.press('Control+k')
 assert.equal(await search.inputValue(),'Research')
 await page.keyboard.press('Escape')
 assert.equal(await input.evaluate(el=>document.activeElement===el),true)
 assert.equal(await input.inputValue(),'Keep this draft')
 console.log('PASS native dialog repeated shortcut, Escape focus, retained composer draft')
 await page.getByRole('button',{name:'Open prompt commands'}).click()
 assert.equal(await page.getByRole('button',{name:/Plan Milestones/}).evaluate(el=>document.activeElement===el),true)
 await page.keyboard.press('ArrowDown')
 await page.keyboard.press('Enter')
 assert.match(await input.inputValue(),/Research this using current sources/)
 console.log('PASS keyboard-only prompt selection inserts into existing draft')
 await page.getByRole('button',{name:'Search',exact:true}).click()
 await page.getByRole('textbox',{name:'Search navigation'}).fill('Models')
 await page.getByRole('button',{name:'Collapse sidebar'}).click()
 await page.getByRole('link',{name:'Extensions',exact:true}).waitFor()
 console.log('PASS collapsing filtered sidebar restores hidden destinations')
 assert.deepEqual(errors,[])
 await page.screenshot({path:'beta-browser.png',fullPage:true})
 await browser.close()
})().catch(error=>{console.error(error);process.exit(1)})
