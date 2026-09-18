const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../src/trainer/web/duel-smart.js'),'utf8');
test('restarting a closed client captures a new connection before monitoring',async()=>{
  const state={automatic:{connection:{capture_id:'old'},smartRun:{value:{stage:'closed'}}}},calls=[];
  const scope=vm.createContext({module:{exports:{}},duelState:()=>state,calls});vm.runInContext(source,scope);
  vm.runInContext(`cancelSmartRecognition=async()=>{calls.push('cancel');duelState().automatic.smartRun=null;};captureDuelProcess=async()=>{calls.push('capture');duelState().automatic.connection={capture_id:'new'};};beginSmartRecognition=async()=>calls.push(duelState().automatic.connection.capture_id);`,scope);
  await vm.runInContext('restartSmartRecognition()',scope);assert.deepEqual(calls,['cancel','capture','new']);
});
test('a failed recapture cannot start monitoring the previous process token',async()=>{
  const state={automatic:{connection:{capture_id:'old'},smartRun:{value:{stage:'closed'}}}},calls=[];
  const scope=vm.createContext({module:{exports:{}},duelState:()=>state,calls});vm.runInContext(source,scope);
  vm.runInContext(`cancelSmartRecognition=async()=>{duelState().automatic.smartRun=null;};captureDuelProcess=async()=>{duelState().automatic.connection=null;};beginSmartRecognition=async()=>calls.push('unexpected-start');`,scope);
  await vm.runInContext('restartSmartRecognition()',scope);assert.deepEqual(calls,[]);
});
