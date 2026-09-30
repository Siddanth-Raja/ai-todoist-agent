from __future__ import annotations
import asyncio
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.runtime_store import RuntimeConfig,RuntimeStore,RuntimeRefusal,bootstrap

try:
    import argon2, pyrage
    CRYPTO = True
except ImportError:
    CRYPTO = False


@unittest.skipUnless(CRYPTO,"Install pinned SID-157 synthetic runtime dependencies")
class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.runtime_auth import password_hasher
        cls.password_hash = password_hasher().hash("synthetic-test-password")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.config = RuntimeConfig(self.directory/'store',str(uuid.uuid4()),'synthetic-owner','synthetic-workspace')
        self.environment = patch.dict(os.environ,{"PYTHON_DOTENV_DISABLED":"1","APP_DB_PATH":str(self.config.database)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        bootstrap(self.config,self.password_hash)
        self.store = RuntimeStore(self.config)
        self.store.start()
        self.addCleanup(self.store.close)

    def service(self):
        from app.conversation_context import ContextScope, SharedConversationContextService
        return SharedConversationContextService(),ContextScope(self.config.actor_id,self.config.workspace_id)

    def grant(self):
        from app.conversation_context import CommandIdentity
        service,scope = self.service()
        return service.grant_capture_consent(scope,CommandIdentity('grant','grant-key'),capture_scope='college-operational',scope_version='1')

    def capture(self):
        from app.conversation_context import CommandIdentity
        self.grant()
        service,scope = self.service()
        now=datetime.now(timezone.utc)
        return service.capture_context(scope,CommandIdentity('capture','capture-key'),item_id='synthetic-item',capture_scope='college-operational',scope_version='1',context_kind='operational_attestation',content={'reported_update':'SYNTHETIC-CONTENT-CANARY'},raw_content='SYNTHETIC-RAW-CANARY',certainty='unknown',source_identity='synthetic-app',source_authority='user_report',conversation_id='synthetic-conversation',asserted_at=now)

    def vault(self,**kwargs):
        from app.runtime_backup import LocalVault
        path=self.directory/'vault'
        path.mkdir(exist_ok=True)
        return LocalVault(path,self.config.environment_id,b'k'*32,reserve=0,**kwargs)


    def test_retained_assessment_is_trusted_and_retry_identity_is_immutable(self):
        from app.runtime_integration import retained_assessment
        from app.college_domain import CollegeDomainService, CollegeScope
        from app.conversation_context import CommandIdentity
        self.capture()
        now=datetime.now(timezone.utc)
        payload={'operation':'request_assessment','command_id':'trusted-assess','idempotency_key':'trusted-assess-key',
                 'authorized_scope':{'kind':'cross_course','subject_ids':[]},
                 'horizon':{'start':now.isoformat(),'end':(now+timedelta(days=1)).isoformat()},
                 'timezone':'America/Chicago','valid_through':(now+timedelta(hours=1)).isoformat()}
        with self.store.write_gate():
            rejected=retained_assessment(self.store,{**payload,'baseline':{'injected':'untrusted'}})
            self.assertEqual(rejected.status_code,400)
            result=retained_assessment(self.store,payload)
            self.assertEqual(result.status_code,200)
            ack=json.loads(result.body);self.assertEqual(ack['receipt_state'],'applied')
            with self.store.connection(readonly=True) as c:
                row=c.execute('SELECT * FROM college_assessments').fetchone()
                self.assertIsNone(row['baseline_json']);self.assertIsNone(row['window_json'])
                self.assertIsNotNone(row['context_snapshot_id'])
                fingerprint=c.execute('SELECT * FROM runtime_assessment_inputs').fetchone()
                self.assertNotIn('CANARY',str(tuple(fingerprint)))
            changed=retained_assessment(self.store,{**payload,'timezone':'UTC'})
            self.assertEqual(changed.status_code,409)
            service,scope=self.service()
            service.revoke_capture_consent(scope,CommandIdentity('assessment-revoke','assessment-revoke-key'),capture_scope='college-operational',scope_version='1',expected_revision=1)
            duplicate=json.loads(retained_assessment(self.store,payload).body)
            self.assertEqual(duplicate['receipt_id'],ack['receipt_id'])
            self.assertEqual(duplicate['delivery_disposition'],'duplicate')
        # An interrupted immutable request cannot acquire a new context under its old key.
        service.forget_context(scope,CommandIdentity('assessment-forget','assessment-forget-key'),item_id='synthetic-item',expected_revision=1)
        with self.store.connection() as c:
            c.execute("UPDATE college_receipts SET state='retryable_failure' WHERE command_id='trusted-assess'")
        with self.store.write_gate():
            stale=retained_assessment(self.store,payload)
            self.assertEqual(stale.status_code,409,stale.body)

    def test_assessment_excludes_other_scope_and_sensitive_retained_context(self):
        from app.runtime_integration import retained_assessment
        from app.college_domain import CollegeDomainService
        from app.conversation_context import CommandIdentity
        self.grant()
        service,scope=self.service()
        now=datetime.now(timezone.utc)
        service.capture_context(scope,CommandIdentity('confirmed-context','confirmed-context-key'),
                item_id='synthetic-item',capture_scope='college-operational',scope_version='1',
                context_kind='operational_attestation',content={'reported_update':'Synthetic reviewed context'},
                certainty='confirmed',source_identity='synthetic-app',source_authority='user_report',
                asserted_at=now)
        base={'operation':'request_assessment','authorized_scope':{'kind':'cross_course','subject_ids':[]},
              'horizon':{'start':now.isoformat(),'end':(now+timedelta(days=1)).isoformat()},
              'timezone':'UTC','valid_through':(now+timedelta(hours=1)).isoformat()}
        versions=[]
        for command,scope,sensitive in [('other','other-operational',0),('sensitive','college-operational',1),('supported','college-operational',0)]:
            with self.store.connection() as c:
                c.execute("UPDATE shared_context_items SET scope=?,sensitive=? WHERE item_id='synthetic-item'",(scope,sensitive))
            with self.store.write_gate():
                result=retained_assessment(self.store,{**base,'command_id':command,'idempotency_key':command+'-key'})
                self.assertEqual(result.status_code,200,result.body)
            with self.store.connection(readonly=True) as c:
                versions.append(c.execute('SELECT snapshot_version FROM runtime_assessment_inputs WHERE command_id=?',(command,)).fetchone()[0])
        self.assertEqual(versions[:2],[CollegeDomainService()._fingerprint([])]*2)
        self.assertNotEqual(versions[2],versions[0])

    def test_exclusive_owner_and_missing_mount(self):
        other=RuntimeStore(self.config)
        with self.assertRaisesRegex(RuntimeRefusal,'second_owner'):
            other.start()
        mounted=RuntimeStore(RuntimeConfig(self.config.root,self.config.environment_id,self.config.actor_id,self.config.workspace_id,require_mount=True))
        with self.assertRaisesRegex(RuntimeRefusal,'durable_volume'):
            mounted.start()

    def test_restart_preserves_receipt_keys_and_session(self):
        from app.runtime_auth import OwnerAuth
        receipt=self.grant()
        token,csrf=OwnerAuth(self.store).login('synthetic-test-password')
        with self.store.connection(readonly=True) as c:
            before=c.execute("SELECT value FROM context_store_metadata WHERE key='hmac_key'").fetchone()[0]
        self.store.close(); self.store.start()
        self.assertEqual(self.grant()['receipt_id'],receipt['receipt_id'])
        OwnerAuth(self.store).verify(token,csrf=csrf)
        with self.store.connection(readonly=True) as c:
            self.assertEqual(before,c.execute("SELECT value FROM context_store_metadata WHERE key='hmac_key'").fetchone()[0])

    def test_missing_database_never_recreated(self):
        self.store.close(); self.config.database.unlink()
        with self.assertRaises(RuntimeRefusal): self.store.start()
        self.assertFalse(self.config.database.exists())

    def test_missing_fingerprint_key_and_schema_rollback_fail_closed(self):
        with self.store.connection() as c:
            c.execute("DELETE FROM context_store_metadata WHERE key='hmac_key'")
        self.store.close()
        with self.assertRaises(Exception): self.store.start()
        with closing(sqlite3.connect(self.config.database)) as c:
            self.assertIsNone(c.execute("SELECT value FROM context_store_metadata WHERE key='hmac_key'").fetchone())
            c.execute('PRAGMA user_version=15702')
        with self.assertRaisesRegex(RuntimeRefusal,'unsupported_schema_rollback'): self.store.start()

    def test_sqlite_flags_and_read_byte_stability(self):
        from app.college_reads import CollegeReadService,CollegeStatusReadRequest,TrustedCollegeContext
        self.grant()
        from app.runtime_auth import OwnerAuth
        token,csrf=OwnerAuth(self.store).login('synthetic-test-password')
        before=hashlib.sha256(self.config.database.read_bytes()).hexdigest()
        for _ in range(3):
            OwnerAuth(self.store).verify(token)
            result=CollegeReadService(self.config.database).get_update_status(TrustedCollegeContext(self.config.actor_id,self.config.workspace_id,allow_cross_course=True),CollegeStatusReadRequest(command_id='grant'))
            self.assertEqual(result['source'],'context')
            self.store.diagnostics()
            with self.store.connection(readonly=True) as c:
                self.assertEqual(c.execute('PRAGMA query_only').fetchone()[0],1)
                self.assertEqual(c.execute('PRAGMA synchronous').fetchone()[0],2)
                self.assertEqual(c.execute('PRAGMA journal_mode').fetchone()[0],'delete')
                self.assertEqual(c.execute('PRAGMA secure_delete').fetchone()[0],1)
                self.assertEqual(c.execute('PRAGMA foreign_keys').fetchone()[0],1)
        self.assertEqual(before,hashlib.sha256(self.config.database.read_bytes()).hexdigest())

    def test_privacy_outbox_atomic_and_outage_restart(self):
        from app.conversation_context import CommandIdentity
        receipt=self.capture()
        service,scope=self.service()
        forgotten=service.forget_context(scope,CommandIdentity('forget','forget-key'),item_id='synthetic-item',expected_revision=1)
        revoked=service.revoke_capture_consent(scope,CommandIdentity('revoke','revoke-key'),capture_scope='college-operational',scope_version='1',expected_revision=1)
        self.assertEqual(forgotten['state'],'applied'); self.assertEqual(revoked['state'],'applied')
        self.assertEqual(self.store.diagnostics()['backup_sanitation'],'pending')
        self.store.close();self.store.start()
        with self.store.connection(readonly=True) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM runtime_suppression_outbox').fetchone()[0],2)
            self.assertEqual(c.execute('SELECT capture_enabled FROM context_capture_consents').fetchone()[0],0)
            self.assertNotIn('SYNTHETIC-CONTENT-CANARY',str(c.execute('SELECT content_json FROM shared_context_items').fetchall()))
        self.assertEqual(service.get_receipt(scope,command_id='forget')['receipt_id'],forgotten['receipt_id'])

    def test_failed_privacy_rolls_back_receipt_and_outbox(self):
        from app.conversation_context import CommandIdentity,SharedConversationContextService
        self.capture()
        _,scope=self.service()
        def fail(point):
            if point=='after_receipt_insert': raise RuntimeError('injected')
        service=SharedConversationContextService(failure_injector=fail)
        with self.assertRaises(RuntimeError):
            service.forget_context(scope,CommandIdentity('forget','forget-key'),item_id='synthetic-item',expected_revision=1)
        with self.store.connection(readonly=True) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM runtime_suppression_outbox').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT privacy_generation FROM runtime_metadata').fetchone()[0],0)
            self.assertEqual(c.execute("SELECT status FROM shared_context_items WHERE item_id='synthetic-item'").fetchone()[0],'needs_review')

    def test_age_encryption_rotation_and_isolated_restore(self):
        from app.runtime_auth import OwnerAuth
        vault=self.vault(); identity=pyrage.x25519.Identity.generate()
        self.capture();old_token,_=OwnerAuth(self.store).login('synthetic-test-password')
        backup=vault.backup(self.store,str(identity.to_public()))
        self.assertNotIn(b'SYNTHETIC-CONTENT-CANARY',(vault.path/(backup+'.age')).read_bytes())
        config=RuntimeConfig(self.directory/'restored',str(uuid.uuid4()),self.config.actor_id,self.config.workspace_id)
        from app.runtime_auth import password_hasher
        new_hash=password_hasher().hash('synthetic-new-password')
        vault.restore(backup,str(identity),config,new_hash,authority=self.store)
        self.store.close()
        recovered=RuntimeStore(config); recovered.start()
        try:
            with self.assertRaises(RuntimeRefusal):OwnerAuth(recovered).verify(old_token)
            with self.assertRaises(RuntimeRefusal):OwnerAuth(recovered).login('synthetic-test-password')
            OwnerAuth(recovered).login('synthetic-new-password')
            self.assertTrue(recovered.diagnostics()['capture_disabled_for_recovery'])
        finally:recovered.close()
        self.store.start()
        for n in range(9):vault.backup(self.store,str(identity.to_public()),now=time.time()+n)
        self.assertEqual(len(list(vault.path.glob('*.age'))),7)
        vault.rotate(now=time.time()+8*86400)
        self.assertEqual(len(list(vault.path.glob('*.age'))),0)

    def test_old_clean_manifest_cannot_authorize_disk_loss_restore(self):
        vault=self.vault();identity=pyrage.x25519.Identity.generate()
        old=vault.backup(self.store,str(identity.to_public()))
        self.capture()
        from app.conversation_context import CommandIdentity
        service,scope=self.service()
        service.revoke_capture_consent(scope,CommandIdentity('revoke','revoke-key'),capture_scope='college-operational',scope_version='1',expected_revision=1)
        self.store.close();self.config.database.unlink()
        target=RuntimeConfig(self.directory/'recovered',str(uuid.uuid4()),self.config.actor_id,self.config.workspace_id)
        with self.assertRaisesRegex(RuntimeRefusal,'quarantined'):
            vault.restore(old,str(identity),target,self.password_hash)
        self.assertFalse(target.root.exists());self.assertTrue((vault.path/'QUARANTINED').is_file())
        bootstrap(target,self.password_hash,recovery=True)
        empty=RuntimeStore(target);empty.start()
        try:
            with empty.connection(readonly=True) as c:
                self.assertEqual(c.execute('SELECT count(*) FROM shared_context_items').fetchone()[0],0)
            self.assertTrue(empty.diagnostics()['capture_disabled_for_recovery'])
        finally:empty.close()

    def test_sync_retry_prunes_affected_copies_and_rejects_gaps(self):
        vault=self.vault();identity=pyrage.x25519.Identity.generate();self.capture()
        old=vault.backup(self.store,str(identity.to_public()))
        from app.conversation_context import CommandIdentity
        service,scope=self.service()
        service.forget_context(scope,CommandIdentity('forget','forget-key'),item_id='synthetic-item',expected_revision=1)
        self.assertEqual(vault.sync(self.store),1)
        self.assertEqual(vault.sync(self.store),1)
        self.assertFalse((vault.path/(old+'.age')).exists())
        self.assertEqual(self.store.diagnostics()['backup_sanitation'],'synced')
        with self.store.connection() as c:c.execute('DELETE FROM runtime_suppression_outbox WHERE generation=1')
        with self.assertRaisesRegex(RuntimeRefusal,'history_incomplete'):vault.sync(self.store)

    def test_backup_quota_failure_keeps_local_privacy(self):
        from app.conversation_context import CommandIdentity
        self.capture();service,scope=self.service()
        service.forget_context(scope,CommandIdentity('forget','forget-key'),item_id='synthetic-item',expected_revision=1)
        vault=self.vault(cap=1)
        with self.assertRaisesRegex(RuntimeRefusal,'capacity'):vault.sync(self.store)
        self.assertEqual(self.store.diagnostics()['backup_sanitation'],'pending')
        self.assertEqual(service.get_receipt(scope,command_id='forget')['state'],'applied')

    def test_session_csrf_rate_limits_and_reset(self):
        from app.runtime_auth import OwnerAuth
        auth=OwnerAuth(self.store)
        token,csrf=auth.login('synthetic-test-password')
        with self.assertRaisesRegex(RuntimeRefusal,'csrf'):auth.verify(token,csrf='foreign')
        auth.verify(token,csrf=csrf);auth.reset(self.password_hash)
        with self.assertRaises(RuntimeRefusal):auth.verify(token)
        for n in range(4):
            with self.assertRaises(RuntimeRefusal):auth.login('bad')
        with self.assertRaisesRegex(RuntimeRefusal,'rate_limited'):auth.login('synthetic-test-password')

    def test_serialized_capture_after_revoke_denied(self):
        from app.conversation_context import CommandIdentity,ContextStoreError
        self.grant();service,scope=self.service()
        ordering=[]
        def revoke():
            with self.store.write_gate():
                service.revoke_capture_consent(scope,CommandIdentity('revoke','revoke-key'),capture_scope='college-operational',scope_version='1',expected_revision=1)
                ordering.append('revoked')
        def capture():
            with self.store.write_gate():
                try:
                    service.capture_context(scope,CommandIdentity('late','late-key'),item_id='late',capture_scope='college-operational',scope_version='1',context_kind='operational_attestation',content={'reported_update':'late'},certainty='unknown',source_identity='synthetic-app',source_authority='user_report',conversation_id='synthetic',asserted_at=datetime.now(timezone.utc))
                except ContextStoreError:ordering.append('denied')
        thread=threading.Thread(target=revoke);thread.start();thread.join()
        thread=threading.Thread(target=capture);thread.start();thread.join()
        self.assertEqual(ordering,['revoked','denied'])

    def test_context_status_scope_and_lookup_kinds(self):
        from app.college_reads import CollegeReadService,CollegeStatusReadRequest,TrustedCollegeContext
        receipt=self.capture();reader=CollegeReadService(self.config.database)
        auth=TrustedCollegeContext(self.config.actor_id,self.config.workspace_id,allow_cross_course=True)
        for query in ({'command_id':'capture'},{'idempotency_key':'capture-key'},{'receipt_id':receipt['receipt_id']}):
            self.assertEqual(reader.get_update_status(auth,CollegeStatusReadRequest(**query))['receipt']['receipt_id'],receipt['receipt_id'])
        for restricted in (TrustedCollegeContext('synthetic-foreign',self.config.workspace_id,allow_cross_course=True),TrustedCollegeContext(self.config.actor_id,'synthetic-foreign',allow_cross_course=True),TrustedCollegeContext(self.config.actor_id,self.config.workspace_id,allowed_course_ids=frozenset({'course'}),allow_cross_course=True)):
            self.assertEqual(reader.get_update_status(restricted,CollegeStatusReadRequest(command_id='capture'))['status'],'not_found')

    def test_restart_interrupted_assessment_and_expired_raw(self):
        from app.college_domain import CollegeDomainService,CollegeScope,CollegeCommandIdentity
        self.capture()
        now=datetime.now(timezone.utc)
        domain=CollegeDomainService()
        scope=CollegeScope(self.config.actor_id,self.config.workspace_id)
        receipt=domain.queue_assessment(scope,CollegeCommandIdentity('assessment','assessment-key'),authorized_scope={'kind':'cross_course','subject_ids':[]},horizon={'start':now.isoformat(),'end':(now+timedelta(hours=1)).isoformat()},timezone_name='America/Chicago',valid_through=now+timedelta(hours=1))
        domain.start_assessment(scope,assessment_id=receipt['affected_ids'][0])
        with self.store.connection() as c:
            c.execute('UPDATE raw_conversation_evidence SET expires_at=?',((now-timedelta(seconds=1)).isoformat(),))
        self.store.close();self.store.start()
        with self.store.connection(readonly=True) as c:
            self.assertIsNone(c.execute('SELECT content FROM raw_conversation_evidence').fetchone()[0])
            row=c.execute("SELECT receipt_id,state,error_code FROM college_receipts WHERE command_id='assessment'").fetchone()
            self.assertEqual(tuple(row),(receipt['receipt_id'],'retryable_failure','interrupted'))
            self.assertEqual(c.execute('SELECT count(*) FROM runtime_suppression_outbox').fetchone()[0],1)

    def test_runtime_http_auth_limits_status_and_safe_logs(self):
        from app.runtime_api import create_runtime_app
        from app.conversation_context import CommandIdentity
        self.capture()
        self.store.close()
        application=create_runtime_app(self.config)
        async def request(method,path,payload=None,*,cookie=None,csrf=None,origin=True,query='',client='127.0.0.1',raw=None):
            body=raw if raw is not None else json.dumps(payload).encode() if payload is not None else b''
            headers=[(b'host',b'127.0.0.1:8017'),(b'content-type',b'application/json')]
            if origin:headers.append((b'origin',self.config.origin.encode()))
            if cookie:headers.append((b'cookie',cookie.encode()))
            if csrf:headers.append((b'x-csrf-token',csrf.encode()))
            scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','scheme':'http','method':method,'path':path,'raw_path':path.encode(),'query_string':query.encode(),'root_path':'','headers':headers,'client':(client,1234),'server':('127.0.0.1',8017)}
            delivered=False
            messages=[]
            async def receive():
                nonlocal delivered
                if not delivered:
                    delivered=True
                    return {'type':'http.request','body':body,'more_body':False}
                await asyncio.Event().wait()
            async def send(message):messages.append(message)
            await asyncio.wait_for(application(scope,receive,send),10)
            start=next(m for m in messages if m['type']=='http.response.start')
            content=b''.join(m.get('body',b'') for m in messages if m['type']=='http.response.body')
            return start['status'],json.loads(content),dict(start['headers'])
        async def exercise():
            async with application.router.lifespan_context(application):
                self.assertEqual((await request('GET','/college/surface/consent'))[0],401)
                self.assertEqual((await request('POST','/runtime/login',{'password':'synthetic-test-password'},origin=False))[0],403)
                status,data,headers=await request('POST','/runtime/login',{'password':'synthetic-test-password'})
                self.assertEqual(status,200)
                cookie=headers[b'set-cookie'].decode().split(';')[0];csrf=data['csrf']
                self.assertIn(b'HttpOnly',headers[b'set-cookie'])
                before=hashlib.sha256(self.config.database.read_bytes()).hexdigest()
                status,binding,_=await request('GET','/runtime/session',cookie=cookie)
                self.assertEqual(status,200);self.assertEqual(binding['auth_generation'],data['auth_generation'])
                status,parent,_=await request('GET','/today',cookie=cookie)
                self.assertEqual(status,200);self.assertIn('unavailable',parent['errors'][0])
                self.assertFalse(parent['recommendation']['evidence'][0]['value']['assessment_requested'])
                self.assertEqual(hashlib.sha256(self.config.database.read_bytes()).hexdigest(),before)
                self.assertEqual((await request('GET','/activity',cookie=cookie))[0],503)
                self.assertEqual((await request('GET','/morning-state',cookie=cookie))[0],503)
                self.assertEqual((await request('POST','/today',{},cookie=cookie,csrf=csrf))[0],405)
                self.assertEqual((await request('GET','/college/surface/consent',cookie=cookie))[0],200)
                status,result,_=await request('GET','/college/update-status',cookie=cookie,query='command_id=capture')
                self.assertEqual(status,200);self.assertEqual(result['source'],'context')
                self.assertEqual((await request('GET','/college/state',cookie=cookie,query='actor_id=foreign'))[0],422)
                self.assertEqual((await request('POST','/runtime/renew',{},cookie=cookie,csrf='foreign'))[0],403)
                self.assertEqual((await request('GET','/health/live',client='192.168.1.2'))[0],403)
                self.assertEqual((await request('POST','/runtime/login',raw=b'x'*131073))[0],413)
                self.assertEqual((await request('POST','/chat',{},cookie=cookie,csrf=csrf))[0],404)
                self.assertEqual((await request('POST','/college/update',[],cookie=cookie,csrf=csrf))[0],400)
                self.assertEqual((await request('GET','/health/ready'))[0],200)
                self.assertEqual((await request('POST','/college/update',{'operation':'request_assessment'},cookie=cookie,csrf=csrf))[0],400)
                capture_payload={'operation':'capture','command_id':'http-capture','idempotency_key':'http-capture-key','message':'Synthetic report with uncertain details','source_surface':'app','conversation_id':'synthetic-app-conversation','asserted_at':datetime.now(timezone.utc).isoformat(),'timezone':'America/Chicago'}
                status,receipt,_=await request('POST','/college/update',capture_payload,cookie=cookie,csrf=csrf)
                self.assertEqual(status,200);self.assertEqual(receipt['outcome'],'saved_for_review')
                status,lookup,_=await request('GET','/college/update-status',cookie=cookie,query='command_id=http-capture')
                self.assertEqual(lookup['receipt']['receipt_id'],receipt['receipt_id'])
                status,duplicate,_=await request('POST','/college/update',capture_payload,cookie=cookie,csrf=csrf)
                self.assertEqual(duplicate['receipt_id'],receipt['receipt_id'])
                self.assertEqual((await request('POST','/college/update',{**capture_payload,'message':'changed payload'},cookie=cookie,csrf=csrf))[0],409)
                payload={'operation':'revoke','command_id':'http-revoke','idempotency_key':'http-revoke-key','expected_revision':1}
                self.assertEqual((await request('POST','/college/surface/consent',payload,cookie=cookie,csrf=csrf))[0],200)
                status,result,_=await request('GET','/runtime/diagnostics',cookie=cookie)
                self.assertEqual(result['backup_sanitation'],'pending')
                self.assertEqual((await request('POST','/runtime/logout',{},cookie=cookie,csrf=csrf))[0],200)
                self.assertEqual((await request('GET','/college/surface/context',cookie=cookie))[0],401)
        with self.assertLogs('pcos.runtime',level='INFO') as logs:
            asyncio.run(exercise())
        for forbidden in ('synthetic-test-password','SYNTHETIC-CONTENT-CANARY','SYNTHETIC-RAW-CANARY','command_id=','foreign'):
            self.assertNotIn(forbidden,' '.join(logs.output))
        self.assertFalse(application.state.store.accepting)

    def test_real_process_crash_before_and_after_commit(self):
        import subprocess
        self.capture();self.store.close()
        common="from app.runtime_store import RuntimeConfig,RuntimeStore; from pathlib import Path; import os; from app.conversation_context import SharedConversationContextService,ContextScope,CommandIdentity; c=RuntimeConfig(Path("+repr(str(self.config.root))+"),"+repr(self.config.environment_id)+",'synthetic-owner','synthetic-workspace'); s=RuntimeStore(c); s.start(); scope=ContextScope(c.actor_id,c.workspace_id); "
        env=dict(os.environ,PYTHONPATH=os.pathsep.join(sys.path),PYTHON_DOTENV_DISABLED='1',PCOS_SYNTHETIC_RUNTIME='1')
        before=common+"service=SharedConversationContextService(failure_injector=lambda p: os._exit(23) if p=='after_receipt_insert' else None); service.forget_context(scope,CommandIdentity('crash-forget','crash-forget-key'),item_id='synthetic-item',expected_revision=1)"
        result=subprocess.run([sys.executable,'-c',before],env=env,timeout=20,capture_output=True)
        self.assertEqual(result.returncode,23)
        self.store.start()
        with self.store.connection(readonly=True) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM runtime_suppression_outbox').fetchone()[0],0)
            self.assertIsNone(c.execute("SELECT 1 FROM context_command_receipts WHERE command_id='crash-forget'").fetchone())
        self.store.close()
        after=common+"service=SharedConversationContextService(); service.forget_context(scope,CommandIdentity('crash-forget','crash-forget-key'),item_id='synthetic-item',expected_revision=1); os._exit(24)"
        result=subprocess.run([sys.executable,'-c',after],env=env,timeout=20,capture_output=True)
        self.assertEqual(result.returncode,24)
        self.store.start()
        with self.store.connection(readonly=True) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM runtime_suppression_outbox').fetchone()[0],1)
            self.assertEqual(c.execute("SELECT state FROM context_command_receipts WHERE command_id='crash-forget'").fetchone()[0],'applied')

    def test_age_wrong_identity_and_tampered_manifest_refused(self):
        vault=self.vault();identity=pyrage.x25519.Identity.generate()
        backup=vault.backup(self.store,str(identity.to_public()))
        target=RuntimeConfig(self.directory/'wrong-key',str(uuid.uuid4()),self.config.actor_id,self.config.workspace_id)
        with self.assertRaises(Exception):vault.restore(backup,str(pyrage.x25519.Identity.generate()),target,self.password_hash,authority=self.store)
        self.assertFalse(target.root.exists())
        manifest=vault.path/(backup+'.manifest.json')
        value=json.loads(manifest.read_text());value['value']['generation']=999
        manifest.write_text(json.dumps(value))
        with self.assertRaisesRegex(RuntimeRefusal,'authentication_failed'):vault.restore(backup,str(identity),target,self.password_hash,authority=self.store)

    def test_lost_sync_reply_leaves_pending_then_exact_retry_settles(self):
        from app.conversation_context import CommandIdentity
        from app import runtime_backup
        self.capture();service,scope=self.service()
        service.forget_context(scope,CommandIdentity('forget','forget-key'),item_id='synthetic-item',expected_revision=1)
        vault=self.vault();real_atomic=runtime_backup.atomic
        def lost_reply(path,data):
            real_atomic(path,data)
            if Path(path).name=='suppression.json':raise OSError('synthetic lost reply')
        with patch.object(runtime_backup,'atomic',side_effect=lost_reply):
            with self.assertRaises(OSError):vault.sync(self.store)
        self.assertEqual(self.store.diagnostics()['backup_sanitation'],'pending')
        self.assertEqual(vault.sync(self.store),1)
        self.assertEqual(len(vault.ledger()['records']),1)

    def test_capture_and_revocation_race_obeys_commit_order(self):
        from app.college_capture import CollegeCaptureAdapter,CollegeCaptureRequest,TrustedCollegeCaptureContext,CollegeCaptureError
        from app.college_domain import CollegeDomainService,CollegeScope,CollegeCommandIdentity
        from app.conversation_context import CommandIdentity
        service,scope=self.service();self.grant();domain=CollegeDomainService()
        cs=CollegeScope(self.config.actor_id,self.config.workspace_id)
        now=datetime.now(timezone.utc)
        for ident,kind,parents in [('synthetic-course','course',()),('synthetic-section','section',('synthetic-course',))]:
            domain.create_identity(cs,CollegeCommandIdentity(ident,ident+'-key'),canonical_id=ident,identity_kind=kind,identity_status='resolved',attributes={'label':'Synthetic fixture'},parent_ids=parents,reviewed_composite={'kind':kind,'code':ident})
        service.create_course_binding(scope,CommandIdentity('binding','binding-key'),binding_id='synthetic-binding',term_id='synthetic-term',section_id='synthetic-section',binding_scope='course',review_provenance='synthetic-user-reviewed',reviewed_at=now,valid_from=now-timedelta(days=1),valid_until=now+timedelta(days=1),explicitly_selected=True)
        auth=TrustedCollegeCaptureContext(self.config.actor_id,self.config.workspace_id,allow_cross_course=True)
        request=CollegeCaptureRequest(command_id='raced-capture',idempotency_key='raced-capture-key',message='We covered derivatives; I am lost on definition problems',source_surface='app',conversation_id='synthetic-conversation',asserted_at=now,timezone_name='America/Chicago',binding_id='synthetic-binding',explicitly_selected_binding=True)
        checked=threading.Event();release=threading.Event();revoked=threading.Event();outcomes=[]
        def before_apply():
            checked.set()
            if not release.wait(5):raise RuntimeError('race timeout')
        adapter=CollegeCaptureAdapter(context_service=service,college_service=domain,before_apply=before_apply)
        def capture():
            try:
                with self.store.write_gate():outcomes.append(adapter.record_college_update(auth,request)['outcome'])
            except Exception as exc:outcomes.append(type(exc).__name__)
        def revoke():
            try:
                with self.store.write_gate():
                    service.revoke_capture_consent(scope,CommandIdentity('race-revoke','race-revoke-key'),capture_scope='college-operational',scope_version='1',expected_revision=1)
                    outcomes.append('revoked');revoked.set()
            except Exception as exc:outcomes.append(type(exc).__name__)
        writer=threading.Thread(target=capture);writer.start()
        self.assertTrue(checked.wait(5))
        revoker=threading.Thread(target=revoke);revoker.start()
        self.assertFalse(revoked.wait(.05));release.set()
        writer.join(5);revoker.join(5)
        self.assertFalse(writer.is_alive());self.assertFalse(revoker.is_alive())
        self.assertEqual(outcomes,['applied','revoked'])
        with self.store.write_gate(),self.assertRaises(CollegeCaptureError):adapter.record_college_update(auth,request)
        with self.store.connection(readonly=True) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM college_receipts WHERE command_id='raced-capture'").fetchone()[0],1)

    def test_lifecycle_retry_retains_receipt_and_records_suppression(self):
        from app.college_capture import CollegeCaptureAdapter,CollegeCaptureRequest,TrustedCollegeCaptureContext
        from app.college_domain import CollegeDomainService,CollegeScope,CollegeCommandIdentity
        from app.conversation_context import CommandIdentity
        service,scope=self.service();self.grant();domain=CollegeDomainService()
        cs=CollegeScope(self.config.actor_id,self.config.workspace_id);now=datetime.now(timezone.utc)
        for ident,kind,parents in [('synthetic-course','course',()),('synthetic-section','section',('synthetic-course',))]:
            domain.create_identity(cs,CollegeCommandIdentity(ident,ident+'-key'),canonical_id=ident,identity_kind=kind,identity_status='resolved',attributes={'label':'Synthetic fixture'},parent_ids=parents,reviewed_composite={'kind':kind,'code':ident})
        service.create_course_binding(scope,CommandIdentity('binding','binding-key'),binding_id='synthetic-binding',term_id='synthetic-term',section_id='synthetic-section',binding_scope='course',review_provenance='synthetic-user-reviewed',reviewed_at=now,valid_from=now-timedelta(days=1),valid_until=now+timedelta(days=1),explicitly_selected=True)
        auth=TrustedCollegeCaptureContext(self.config.actor_id,self.config.workspace_id,allow_cross_course=True)
        request=CollegeCaptureRequest(command_id='create-fact',idempotency_key='create-fact-key',message='We covered derivatives; I am lost on definition problems',source_surface='app',conversation_id='synthetic-conversation',asserted_at=now,timezone_name='America/Chicago',binding_id='synthetic-binding',explicitly_selected_binding=True)
        CollegeCaptureAdapter(context_service=service,college_service=domain).record_college_update(auth,request)
        claim=domain.inspect_state(cs)['claims'][0]['claim_id']
        def fail(point):
            if point=='after_domain_mutation':raise sqlite3.OperationalError('synthetic disk full')
        failed=CollegeDomainService(failure_injector=fail).forget_claim(cs,CollegeCommandIdentity('forget-fact','forget-fact-key'),claim_id=claim)
        self.assertEqual(failed['state'],'retryable_failure')
        with self.store.connection(readonly=True) as c:self.assertEqual(c.execute('SELECT count(*) FROM runtime_suppression_outbox').fetchone()[0],0)
        applied=domain.forget_claim(cs,CollegeCommandIdentity('forget-fact','forget-fact-key'),claim_id=claim)
        self.assertEqual(applied['state'],'applied');self.assertEqual(applied['receipt_id'],failed['receipt_id'])
        with self.store.connection(readonly=True) as c:
            self.assertEqual(c.execute('SELECT receipt_id FROM runtime_suppression_outbox').fetchone()[0],applied['receipt_id'])

    def test_no_provider_or_frozen_import_in_fresh_runtime(self):
        import subprocess
        code="import sys; from app.runtime_api import create_runtime_app; from app.runtime_store import RuntimeConfig; from pathlib import Path; import uuid; from app.runtime_api import build_surface; from app.runtime_store import bootstrap,RuntimeStore; from app.runtime_auth import password_hasher; import tempfile; d=tempfile.TemporaryDirectory(); c=RuntimeConfig(Path(d.name)/'fresh',str(uuid.uuid4()),'synthetic-owner','synthetic-workspace'); bootstrap(c,password_hasher().hash('synthetic-password')); s=RuntimeStore(c); s.start(); build_surface(s,'synthetic-internal-key'); assert 'app.config' not in sys.modules; assert 'app.main' not in sys.modules; assert not any(x in sys.modules for x in ['app.gmail_client','app.email_analysis','app.microsoft_graph_mail','requests']); s.close()"
        env=dict(os.environ,PYTHON_DOTENV_DISABLED='1',PCOS_SYNTHETIC_RUNTIME='1',PYTHONPATH=os.pathsep.join(sys.path))
        subprocess.run([sys.executable,'-c',code],env=env,check=True,capture_output=True,timeout=20)


if __name__=='__main__':unittest.main()
