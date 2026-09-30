import assert from 'node:assert/strict';
import test from 'node:test';
import {acceptRuntimeSession,clearRuntimeSession,resumeRuntimeSession,runtimeFetch,runtimeScope,onRuntimeSessionChange} from '../src/lib/runtime-session.ts';
import {RetainedQueryStore} from '../src/lib/retained-query-store.ts';
const binding={environment_id:'environment-a',actor_id:'synthetic-owner',workspace_id:'synthetic-workspace',auth_generation:'generation-a'};
function storage() {
 const result={};
 Object.defineProperties(result,{
  getItem:{value:(key)=>Object.hasOwn(result,key)?result[key]:null},
  setItem:{value:(key,value)=>{result[key]=String(value);}},
  removeItem:{value:(key)=>{delete result[key];}},
 }); return result;
}
test('verified environment survives reload, mismatch destroys incompatible journals', async()=>{
 globalThis.sessionStorage=storage();
 acceptRuntimeSession(binding,'synthetic-csrf');
 sessionStorage.setItem('pcos.college.delivery.v1.old','sensitive retry text');
 globalThis.fetch=async()=>new Response(JSON.stringify(binding),{status:200});
 assert.equal(await resumeRuntimeSession(),true);
 assert.match(runtimeScope(),/environment-a/);
 assert.equal(sessionStorage.getItem('pcos.college.delivery.v1.old'),'sensitive retry text');
 globalThis.fetch=async()=>new Response(JSON.stringify({...binding,environment_id:'environment-b'}),{status:200});
 assert.equal(await resumeRuntimeSession(),false);
 assert.equal(sessionStorage.getItem('pcos.college.delivery.v1.old'),null);
 assert.equal(runtimeScope(),'unauthenticated');
});
test('cookie and CSRF transport strips developer authorization, rejects revoked access and late results', async()=>{
 globalThis.sessionStorage=storage();acceptRuntimeSession(binding,'synthetic-csrf');
 let seen;
 globalThis.fetch=async(url,options)=>{seen={url,options};return new Response('{}',{status:200});};
 await runtimeFetch('/college/update',{method:'POST',body:'{}',headers:{Authorization:'Bearer developer-key'}});
 assert.equal(seen.url,'/runtime-api/college/update');assert.equal(seen.options.credentials,'same-origin');
 assert.equal(seen.options.headers.get('authorization'),null);assert.equal(seen.options.headers.get('x-csrf-token'),'synthetic-csrf');
 let deliver;globalThis.fetch=()=>new Promise(resolve=>{deliver=resolve;});
 const pending=runtimeFetch('/today');clearRuntimeSession();acceptRuntimeSession(binding,'different-local-csrf');
 deliver(new Response('{}',{status:200}));await assert.rejects(pending,/discarded/);
 globalThis.fetch=async()=>new Response('{}',{status:401});await runtimeFetch('/today');
 assert.equal(runtimeScope(),'unauthenticated');await assert.rejects(runtimeFetch('/today'),/Sign in/);
});
test('session invalidation clears retained reads and prevents an older in-flight completion from restoring them', async()=>{
 const store=new RetainedQueryStore(),scope={};
 await store.refresh(scope,'/today',async()=>({secret:'synthetic'}));
 let deliver;const pending=store.refresh(scope,'/today',()=>new Promise(resolve=>{deliver=resolve;}));
 store.clear();assert.equal(store.snapshot(scope,'/today').data,null);
 deliver({secret:'old synthetic result'});await pending;
 assert.equal(store.snapshot(scope,'/today').data,null);
});

test('blocked browser storage still revokes the mounted authentication state',()=>{
 globalThis.sessionStorage=storage();acceptRuntimeSession(binding,'synthetic-csrf');
 let notified=false;const unsubscribe=onRuntimeSessionChange(()=>{notified=true;});
 globalThis.sessionStorage={removeItem:()=>{throw Error('storage blocked');}};
 assert.throws(clearRuntimeSession,/storage blocked/);
 assert.equal(runtimeScope(),'unauthenticated');assert.equal(notified,true);unsubscribe();
});
