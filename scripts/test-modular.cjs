'use strict';
// Every suite gets a hidden Electron host and the isolated -modular profile.
const {spawn}=require('node:child_process');
const path=require('node:path');
const flags={core:null,implicit:'YGO_MODULAR_IMPLICIT_ONLY',preferences:'YGO_MODULAR_PREFERENCES_ONLY',routes:'YGO_MODULAR_ADDITIONAL_ONLY',cross:'YGO_MODULAR_CROSS_ONLY',mechanics:'YGO_MODULAR_MECHANICS_ONLY',if:'YGO_MODULAR_IF_ONLY',precision:'YGO_MODULAR_PRECISION_ONLY',planning:'YGO_MODULAR_PLANNING_ONLY',pipeline:'YGO_MODULAR_PIPELINE_ONLY',forecast:'YGO_MODULAR_FORECAST_ONLY'};
const requested=process.argv.find(a=>a.startsWith('--suite='))?.slice(8);
if(requested&&!Object.hasOwn(flags,requested))throw new Error('Unknown modular suite');
(async()=>{
  for(const name of requested?[requested]:Object.keys(flags)) {
    const env={...process.env};
    for(const key of Object.keys(env))if(key.startsWith('YGO_MODULAR_'))delete env[key];
    if(flags[name])env[flags[name]]='1';
    console.log(`Modular acceptance: ${name}`);
    const child=spawn(process.execPath,[path.join(__dirname,'../desktop/smoke.cjs'),'--modular-only',
      ...(process.argv.includes('--packaged')?['--packaged']:[])],{env,stdio:'inherit',windowsHide:true});
    const code=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',resolve);});
    if(code!==0){process.exitCode=1;return;}
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
