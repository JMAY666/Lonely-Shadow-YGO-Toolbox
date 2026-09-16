'use strict';

// Keep one request in flight and only the newest waiting placement. Scrolling
// must never leave a FIFO of old coordinates replaying after the page settles.
function latestLayout(send) {
  let pending, running=false;
  async function drain() {
    running=true;
    while(pending) {
      const batch=pending;pending=null;
      try {const result=await send(batch.value);for(const waiter of batch.waiters)waiter.resolve(result);}
      catch(error) {for(const waiter of batch.waiters)waiter.reject(error);}
    }
    running=false;
  }
  return value=>new Promise((resolve,reject)=>{
    if(pending){pending.value=value;pending.waiters.push({resolve,reject});}
    else pending={value,waiters:[{resolve,reject}]};
    if(!running)void drain();
  });
}
module.exports={latestLayout};
