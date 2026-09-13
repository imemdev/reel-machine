const { app, BrowserWindow, Menu, dialog, shell, session, Tray, nativeImage } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
app.setName('Kite');
let window, backend, tray, origin, quitting = false, stopping = false;
const token = crypto.randomBytes(32).toString('hex');
const root = app.isPackaged ? path.join(process.resourcesPath, 'payload') : path.join(__dirname, 'payload');
const data = path.join(app.getPath('userData'), 'library');
const python = path.join(root, 'python', 'bin', 'python3');
const model = path.join(app.getPath('home'), 'Library', 'Caches', 'kite', 'FarukSTT');
const logDir = path.join(app.getPath('userData'), 'logs');
fs.mkdirSync(logDir, {recursive:true});
const log = fs.openSync(path.join(logDir, 'backend.log'), 'a');
const env = {...process.env, PYTHONUNBUFFERED:'1', PYTHONPYCACHEPREFIX:path.join(app.getPath('userData'),'python-cache'), PYTHONNOUSERSITE:'1', PYTHONPATH:root,
  PATH:`${path.join(root,'tools')}:${path.join(root,'python','bin')}:/usr/bin:/bin:/usr/sbin:/sbin`,
  DATABASE_PATH:path.join(data,'library.db'), ARTIFACT_ROOT:path.join(data,'runs'),
  FARUKSTT_MODEL:model, ALLOW_FIXTURE_SOURCES:'false', HF_HUB_OFFLINE:'1', TRANSFORMERS_OFFLINE:'1',
  YTA_FUNCTION:'yta', YTDLP:path.join(root,'tools','yt-dlp'), GALLERY_DL:path.join(root,'tools','gallery-dl'),
  FFMPEG:path.join(root,'tools','ffmpeg'), API_ORIGINS:'', KITE_DESKTOP_TOKEN:token};
function run(args) {
  return new Promise((resolve,reject) => {
    const child=spawn(python,args,{cwd:root,env,stdio:['ignore',log,log]});
    child.once('error',reject); child.once('exit',code=>code===0?resolve():reject(new Error(`Setup failed (${code}). See ${logDir}`)));
  });
}
function showWindow() { if(window) { window.show(); window.focus(); } }
async function launch() {
  window=new BrowserWindow({width:1380,height:920,minWidth:390,minHeight:600,title:'Kite',backgroundColor:'#f5f6f8',webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true}});
  window.on('close', e=>{if(!quitting){e.preventDefault();window.hide();}});
  window.loadURL('data:text/html;charset=utf-8,'+encodeURIComponent('<body style="background:#f5f6f8;font:16px -apple-system;padding:80px;color:#17202d"><h1>Kite</h1><p>Opening your local library…</p><p>Your videos and transcripts stay on this Mac.</p></body>'));
  const migration=JSON.parse(fs.readFileSync(path.join(__dirname,'migration.json')));
  await run([path.join(root,'server.py'),'--migrate',migration.sourceData,data]);
  if(!fs.existsSync(path.join(model,'config.json'))) throw new Error(`FarukSTT is missing at ${model}. Restore the model directory, then reopen Kite.`);
  backend=spawn(python,[path.join(root,'server.py')],{cwd:root,env,stdio:['ignore','pipe',log]});
  let buffer='';
  const port=await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error('The backend took too long to start. See '+logDir)),60000);
    backend.once('error',e=>{clearTimeout(timer);reject(e);});
    backend.once('exit',code=>{clearTimeout(timer);reject(new Error(`Backend exited (${code}). See ${logDir}`));});
    backend.stdout.on('data',chunk=>{fs.writeSync(log,chunk);buffer+=chunk; const match=buffer.match(/KITE_READY=(\d+)/);if(match){clearTimeout(timer);resolve(Number(match[1]));}});
  });
  origin=`http://127.0.0.1:${port}`;
  session.defaultSession.webRequest.onBeforeSendHeaders((details, callback)=>{
    if(details.url.startsWith(origin+'/')) details.requestHeaders['X-Kite-Token']=token;
    callback({requestHeaders:details.requestHeaders});
  });
  for(let i=0;i<100;i++){
    try{const r=await fetch(origin+'/api/health',{headers:{'X-Kite-Token':token}});if(r.ok)break;}catch{}
    if(i===99)throw new Error('Backend is not responding. See '+logDir);
    await new Promise(r=>setTimeout(r,200));
  }
  window.webContents.setWindowOpenHandler(({url})=>{
    if(url.startsWith(origin+'/api/')) window.webContents.downloadURL(url);
    else if(/^https?:\/\//.test(url)) shell.openExternal(url);
    return {action:'deny'};
  });
  window.webContents.on('will-navigate',(event,url)=>{if(!url.startsWith(origin+'/')){event.preventDefault();if(/^https?:\/\//.test(url))shell.openExternal(url);}});
  session.defaultSession.setPermissionRequestHandler((_wc,permission,callback)=>callback(permission==='clipboard-sanitized-write'));
  backend.on('exit',()=>{if(!quitting){dialog.showErrorBox('Kite backend stopped','Your saved library is retained. Quit and reopen Kite. Logs: '+logDir);}});
  await window.loadURL(origin);
  tray=new Tray(nativeImage.createFromDataURL('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg=='));
  tray.setTitle('Kite'); tray.setToolTip('Kite — local video library');
  tray.setContextMenu(Menu.buildFromTemplate([{label:'Open Kite',click:showWindow},{label:'Open data folder',click:()=>shell.openPath(data)},{type:'separator'},{role:'quit',label:'Quit Kite'}]));
}
if(!app.requestSingleInstanceLock()){app.quit();}else{
  app.on('second-instance',showWindow);
  app.on('activate',showWindow);
  app.on('window-all-closed',()=>{});
  app.whenReady().then(()=>{
    Menu.setApplicationMenu(Menu.buildFromTemplate([{label:'Kite',submenu:[{role:'about'},{label:'Open Kite',click:showWindow},{label:'Open data folder',click:()=>shell.openPath(data)},{type:'separator'},{role:'hide'},{role:'quit'}]},{role:'editMenu'},{role:'viewMenu'},{role:'windowMenu'}]));
    return launch();
  }).catch(error=>{dialog.showErrorBox('Kite could not start',error.message);app.quit();});
  app.on('before-quit',event=>{
    quitting=true;
    if(backend&&backend.exitCode===null&&!stopping){
      event.preventDefault();stopping=true;
      backend.once('exit',()=>app.quit());backend.kill('SIGTERM');
      setTimeout(()=>{if(backend.exitCode===null)backend.kill('SIGKILL');app.quit();},10000).unref();
    }
  });
}
