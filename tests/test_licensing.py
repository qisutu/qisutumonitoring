"""Offline signing, persistent identity and device capacity under concurrent writes."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import uuid
from netzmonitor.core import Store
from netzmonitor.license_format import (PLANS, canonical, openssl, public_key_id,
                                       sign_document, today, verify_document)


@unittest.skipUnless(shutil.which('openssl'), 'OpenSSL erforderlich')
class LicenseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys = tempfile.TemporaryDirectory()
        cls.private = Path(cls.keys.name)/'private.pem'
        cls.public = Path(cls.keys.name)/'public.pem'
        result = openssl(['genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:3072','-out',str(cls.private)], timeout=30)
        assert result.returncode == 0
        result = openssl(['pkey','-in',str(cls.private),'-pubout','-out',str(cls.public)])
        assert result.returncode == 0
        cls.pem = cls.public.read_text()

    @classmethod
    def tearDownClass(cls):
        cls.keys.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.key_patch = patch('netzmonitor.licensing.PUBLIC_KEY', self.public)
        self.key_patch.start()
        self.store = Store(self.temp.name)

    def tearDown(self):
        self.key_patch.stop()
        self.temp.cleanup()

    def payload(self, plan='service-100', **changes):
        data = dict(product='netzmonitor', license_id=str(uuid.uuid4()),
                    installation_id=self.store.license_status()['installation_id'],
                    customer='Prüfkunde & Partner <GmbH>',contract_id='Vertrag 2026-001',
                    plan=plan,device_limit=PLANS[plan][0],issued_at=int(time.time()),
                    valid_from=today().isoformat(),valid_until=(today()+timedelta(days=364)).isoformat())
        return {**data, **changes}

    def license(self, plan='service-100', **changes):
        return sign_document(self.payload(plan, **changes),self.private,self.pem)

    def activate(self, raw):
        preview=self.store.preview_license({'file':raw})
        return self.store.import_license(dict(file=raw, revision=preview['revision']))

    def add(self, n):
        return self.store.save_device(dict(name='Gerät '+str(n), address='device-%s.test'%n))

    def discoveries(self, count):
        with self.store.connect() as db:
            db.executemany('INSERT INTO discoveries(ip,hostname,first_seen,last_seen) VALUES(?,?,?,?)',
                           [('192.0.2.%s'%n,'',time.time(),time.time()) for n in range(1,count+1)])

    def choose(self, ids, limit=10):
        info=self.store.license_status()
        source=info['selection'] if info['device_limit']==limit else info['fallback_selection']
        return self.store.save_license_selection(dict(limit=limit,ids=ids,
            revision=source['revision'],license_revision=info['revision']))

    def test_preselection_expiry_restart_and_renewal_preserve_manual_pause(self):
        self.activate(self.license(valid_until=today().isoformat()))
        ids=[self.add(n) for n in range(12)]
        with self.store.connect() as db:db.execute('UPDATE devices SET enabled=0 WHERE id=?',(ids[0],))
        chosen=ids[:10]
        result=self.choose(chosen)
        self.assertEqual(result['permitted_devices'],12)
        self.assertFalse(any(d['license_blocked'] for d in self.store.state()['devices']))
        with patch('netzmonitor.licensing.today',return_value=today()+timedelta(days=1)):
            state=self.store.state()
            self.assertEqual([d['id'] for d in state['devices'] if not d['license_blocked']],chosen)
            self.assertEqual(state['license']['permitted_devices'],10)
            self.assertEqual(Store(self.temp.name).license_status()['selection']['ids'],chosen)
            self.assertEqual(self.store.rows('SELECT enabled FROM devices WHERE id=?',(ids[0],))[0]['enabled'],0)
            with self.assertRaises(ValueError):self.add(99)
            self.activate(self.license(valid_from=(today()+timedelta(days=1)).isoformat()))
            self.assertFalse(any(d['license_blocked'] for d in self.store.state()['devices']))
            self.assertEqual(self.store.rows('SELECT enabled FROM devices WHERE id=?',(ids[0],))[0]['enabled'],0)

    def test_selection_validation_conflicts_and_atomicity(self):
        self.activate(self.license())
        ids=[self.add(n) for n in range(12)]
        info=self.store.license_status()
        base=dict(limit=10,ids=ids[:10],revision=0,license_revision=info['revision'])
        for changes in [dict(ids=ids[:11]),dict(ids=[True]),dict(ids=[ids[0],ids[0]]),dict(ids=[999999]),dict(limit=9),dict(revision=True),dict(license_revision=-1)]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                self.store.save_license_selection({**base,**changes})
            self.assertEqual(self.store.license_status(),info)
        self.store.save_license_selection(base)
        with self.assertRaisesRegex(ValueError,'inzwischen'):self.store.save_license_selection(base)
        self.activate(self.license('service-500'))
        with self.assertRaisesRegex(ValueError,'Vertrag wurde'):self.store.save_license_selection({**base,'revision':1})

    def test_selection_swap_new_slots_and_batch_import_with_archived_devices(self):
        self.activate(self.license(valid_until=today().isoformat()))
        ids=[self.add(n) for n in range(12)]
        with patch('netzmonitor.licensing.today',return_value=today()+timedelta(days=1)):
            self.choose(ids[:10])
            self.choose(ids[2:12])
            self.assertFalse(self.store.license_allows(ids[0]))
            self.assertTrue(self.store.license_allows(ids[11]))
            self.choose(ids[2:9])
            new=self.add(99)
            self.discoveries(3)
            self.assertEqual(self.store.import_devices(['192.0.2.1','192.0.2.2']),2)
            info=self.store.license_status()
            self.assertEqual(info['used_devices'],15);self.assertEqual(info['permitted_devices'],10)
            self.assertIn(new,info['selection']['ids'])
            with self.assertRaises(ValueError):self.store.import_devices(['192.0.2.3'])
            self.assertEqual(self.store.license_status()['used_devices'],15)

    def test_smaller_paid_contract_requires_its_own_selection(self):
        self.activate(self.license('service-500'))
        ids=[self.add(n) for n in range(101)]
        self.choose(ids[:10])
        self.activate(self.license('service-100'))
        self.assertTrue(self.store.license_status()['selection_required'])
        self.assertEqual(self.store.license_status()['permitted_devices'],0)
        self.choose(ids[:100],limit=100)
        self.assertEqual(self.store.license_status()['permitted_devices'],100)
        self.assertFalse(self.store.license_allows(ids[-1]))
        self.activate(self.license('service-unlimited'))
        self.assertEqual(self.store.license_status()['permitted_devices'],101)

    def test_workers_and_late_measurements_cannot_use_locked_devices(self):
        from netzmonitor.core import Engine
        from netzmonitor.services import SERVICE_SELECT
        from netzmonitor.resources import RESOURCE_SELECT
        from netzmonitor.integrations import SELECT
        from netzmonitor.integration_common import metric
        self.activate(self.license(valid_until=today().isoformat()))
        ids=[self.add(n) for n in range(12)];did=ids[-1]
        self.store.save_service(dict(device_id=did,type='ping',name='Ping'))
        self.store.save_resource(dict(device_id=did,method='snmp',version='2c',community='secret',port=161))
        with self.store.connect() as db:
            device=db.execute('SELECT * FROM devices WHERE id=?',(did,)).fetchone()
            self.store.save_integrations(db,device,[dict(kind='printer',config=dict(version='2c',community='secret'))])
        service=self.store.rows(SERVICE_SELECT)[0];resource=self.store.rows(RESOURCE_SELECT)[0];integration=self.store.rows(SELECT)[0]
        ping=dict(kind='up',rtt=1,message='OK',ip='192.0.2.1')
        memory=dict(kind='error',metrics=[],message='Testfehler')
        printer=dict(kind='ok',metrics=[metric('state:1','Bereit',3)])
        self.store.record_service(service,ping);self.store.record_resource(resource,memory);self.store.record_integration(integration,printer)
        tables=['service_samples','samples','integration_samples']
        before={t:self.store.rows('SELECT * FROM '+t) for t in tables}
        p,r,i=Mock(return_value=ping),Mock(return_value=memory),Mock(return_value=printer)
        engine=Engine(self.store,probe_fn=p,resource_probe=r,integration_probe=i)
        try:
            with patch('netzmonitor.licensing.today',return_value=today()+timedelta(days=1)):
                engine.check_service(service);engine.check_resource(resource);engine.check_integration(integration)
                p.assert_not_called();r.assert_not_called();i.assert_not_called()
                self.store.record_service(service,ping);self.store.record_resource(resource,memory);self.store.record_integration(integration,printer)
                self.assertEqual({t:self.store.rows('SELECT * FROM '+t) for t in tables},before)
                for fn,ident in [(self.store.service_action,service['id']),(self.store.resource_action,resource['id'])]:
                    with self.assertRaisesRegex(ValueError,'nicht freigeschaltet'):fn(ident,'check')
                self.choose(ids[2:12])
                # Even after reselecting, results started before revocation stay stale.
                self.store.record_service(service,ping);self.store.record_resource(resource,memory);self.store.record_integration(integration,printer)
                self.assertEqual({t:self.store.rows('SELECT * FROM '+t) for t in tables},before)
                engine.check_service(self.store.rows(SERVICE_SELECT)[0]);engine.check_resource(self.store.rows(RESOURCE_SELECT)[0]);engine.check_integration(self.store.rows(SELECT)[0])
                p.assert_called_once();r.assert_called_once();i.assert_called_once()
                self.assertGreater(len(self.store.rows('SELECT * FROM service_samples')),len(before['service_samples']))
        finally:engine.close()

    def test_flow_subscriptions_and_temporary_tests_stop_at_expiration(self):
        from netzmonitor.flow import FlowCollector
        self.activate(self.license(valid_until=today().isoformat()))
        ids=[self.add(n) for n in range(12)]
        with self.store.connect() as db:
            for n,did in enumerate((ids[0],ids[-1])):
                device=db.execute('SELECT * FROM devices WHERE id=?',(did,)).fetchone()
                self.store.save_integrations(db,device,[dict(kind='flow',config=dict(host='192.0.2.'+str(n+1)))])
        self.choose(ids[:10]);collector=FlowCollector(self.store)
        collector.tests[('192.0.2.3',2055,ids[-1])]=time.monotonic()+60
        self.assertEqual(len(collector.subscriptions()),3)
        with patch('netzmonitor.licensing.today',return_value=today()+timedelta(days=1)):
            self.assertEqual(collector.subscriptions(),{('192.0.2.1',2055)})
            self.assertFalse(collector.tests)
            with self.assertRaisesRegex(ValueError,'nicht freigeschaltet'):
                collector.test(dict(device_id=ids[-1],config='{}',timeout=1))

    def test_concurrent_selection_has_one_winner_and_empty_selection_is_explicit(self):
        ids=[self.add(n) for n in range(10)]
        request=dict(limit=10,ids=ids[:5],revision=0,license_revision=0)
        def attempt(_):
            try:self.store.save_license_selection(request);return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,range(2)))
        self.assertEqual(sum(results),1)
        self.choose([])
        self.assertEqual(self.store.license_status()['permitted_devices'],0)
        self.assertTrue(all(d['license_blocked'] for d in self.store.state()['devices']))

    def encrypted(self,raw,request=None):
        try:from license_test_envelope import encrypted
        except ImportError:from tests.license_test_envelope import encrypted
        return encrypted(raw,(request or self.store.license_request())['encryption_public_key'])

    def test_encrypted_all_tiers_and_no_cleartext(self):
        import base64
        from netzmonitor.license_envelope import TRANSPORT,MAGIC
        for plan,(limit,_) in PLANS.items():
            raw=self.encrypted(self.license(plan))
            binary=base64.b64decode(raw[len(TRANSPORT):])
            self.assertTrue(binary.startswith(MAGIC))
            self.assertNotIn('Prüfkunde'.encode(),binary)
            self.assertNotIn(b'device_limit',binary)
            self.assertEqual(self.activate(raw)['device_limit'],limit)
        self.assertEqual(Store(self.temp.name).license_status()['device_limit'],None)

    def test_encrypted_corruption_wrong_installation_and_atomic_import(self):
        import base64
        from netzmonitor.license_envelope import TRANSPORT
        active=self.activate(self.license())
        raw=self.encrypted(self.license('service-500'))
        binary=bytearray(base64.b64decode(raw[len(TRANSPORT):]))
        for offset in (0,8,392,405,len(binary)-1):
            changed=bytearray(binary);changed[offset]^=1
            with self.subTest(offset=offset),self.assertRaises(ValueError):self.activate(TRANSPORT+base64.b64encode(changed).decode())
            self.assertEqual(self.store.license_status(),active)
        with tempfile.TemporaryDirectory() as temp:
            other=Store(temp);foreign=other.license_request()
            with self.assertRaisesRegex(ValueError,'anderen Installation'):
                self.activate(self.encrypted(self.license(),foreign))
        for value in (TRANSPORT+'!',TRANSPORT+'AA==',TRANSPORT+'A'*50000):
            with self.assertRaises(ValueError):self.activate(value)
        self.assertEqual(self.store.license_status(),active)

    def test_encrypted_requires_valid_manufacturer_signature(self):
        document=json.loads(self.license());document['payload']['customer']='Geändert'
        with self.assertRaisesRegex(ValueError,'Signatur'):
            self.activate(self.encrypted(json.dumps(document)))
        self.assertEqual(self.store.license_status()['status'],'free')

    def test_recipient_is_stable_private_and_concurrent(self):
        with ThreadPoolExecutor(max_workers=2) as pool:requests=list(pool.map(lambda _:self.store.license_request(),range(2)))
        self.assertEqual(requests[0],requests[1])
        self.assertEqual(Store(self.temp.name).license_request(),requests[0])
        self.assertNotIn('PRIVATE KEY',json.dumps(requests[0]))
        self.assertNotIn('private_key',json.dumps(self.store.state()))
        self.assertTrue(requests[0]['token'].startswith('NMREQ2.'))

    def test_encrypted_expiration_and_renewal_keep_ten_device_rule(self):
        self.activate(self.encrypted(self.license(valid_until=today().isoformat())))
        ids=[self.add(n) for n in range(12)];self.choose(ids[:10])
        with patch('netzmonitor.licensing.today',return_value=today()+timedelta(days=1)):
            state=self.store.state();self.assertEqual(state['license']['permitted_devices'],10)
            self.assertEqual(sum(d['license_blocked'] for d in state['devices']),2)
            self.activate(self.encrypted(self.license(valid_from=(today()+timedelta(days=1)).isoformat())))
            self.assertFalse(any(d['license_blocked'] for d in self.store.state()['devices']))

    def test_free_limit_editing_paused_and_many_checks(self):
        ids=[self.add(i) for i in range(10)]
        with self.assertRaisesRegex(ValueError,'Gerätebegrenzung'):self.add(11)
        self.store.save_device(dict(id=ids[0],name='Umbenannt',address='renamed.test'))
        with self.store.connect() as db:db.execute('UPDATE devices SET enabled=0 WHERE id=?',(ids[0],))
        with self.assertRaisesRegex(ValueError,'Gerätebegrenzung'):self.add(11)
        for n in range(12):self.store.save_service(dict(device_id=ids[0],type='tcp',name='Port '+str(n),port=1000+n))
        self.assertEqual(self.store.license_status()['used_devices'],10)
        self.assertEqual(len(self.store.state()['services']),12)

    def test_batch_import_atomic_capacity_and_existing_dedup(self):
        for n in range(9):self.add(n)
        self.discoveries(4)
        with self.assertRaisesRegex(ValueError,'Gerätebegrenzung'):
            self.store.import_devices(['192.0.2.1','192.0.2.2'])
        self.assertEqual(self.store.license_status()['used_devices'],9)
        self.assertEqual(self.store.import_devices(['192.0.2.1','192.0.2.1']),1)
        self.assertEqual(self.store.import_devices(['192.0.2.1']),0)
        with self.assertRaises(ValueError):self.store.import_devices(['192.0.2.2','192.0.2.99'])
        self.assertEqual(self.store.license_status()['used_devices'],10)

    def test_concurrent_creates_cannot_exceed_limit(self):
        for n in range(9):self.add(n)
        def attempt(n):
            try:self.add(n);return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(attempt,range(20,28)))
        self.assertEqual(sum(results),1)
        self.assertEqual(self.store.license_status()['used_devices'],10)

    def test_concurrent_batch_and_single_share_same_limit(self):
        for n in range(9):self.add(n)
        self.discoveries(1)
        def attempt(n):
            try:
                self.store.import_devices(['192.0.2.1']) if n==0 else self.add(20)
                return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,[0,1]))
        self.assertEqual(sum(results),1)
        self.assertEqual(self.store.license_status()['used_devices'],10)

    def test_all_plans_and_restart_identity_and_date(self):
        identity=self.store.license_status()['installation_id']
        for plan,(limit,label) in PLANS.items():
            with self.subTest(plan=plan):
                active=self.activate(self.license(plan))
                self.assertEqual(active['device_limit'],limit)
                self.assertEqual(active['plan_label'],label)
                self.assertEqual(active['status'],'active')
                restored=Store(self.temp.name).license_status()
                self.assertEqual(restored,active)
                self.assertEqual(restored['installation_id'],identity)
        self.assertNotIn('signature',self.store.state()['license'])
        self.assertEqual(set(self.store.license_request()),{'format','product','installation_id','registered_devices','encryption_public_key','token'})

    def test_paid_limits_and_unlimited_admission(self):
        self.activate(self.license('service-100'))
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.store.check_device_capacity(db,100)
            with self.assertRaisesRegex(ValueError,'Gerätebegrenzung'):self.store.check_device_capacity(db,101)
        self.activate(self.license('service-500'))
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self.store.check_device_capacity(db,500)
            with self.assertRaisesRegex(ValueError,'Gerätebegrenzung'):self.store.check_device_capacity(db,501)
        self.activate(self.license('service-unlimited'))
        with self.store.connect() as db:self.store.check_device_capacity(db,1000000)
        self.assertIsNone(self.store.license_status()['remaining_devices'])

    def test_tampering_wrong_installation_and_no_side_effect(self):
        active=self.activate(self.license())
        raw=self.license('service-500')
        for field,value in [('customer','Manipuliert'),('valid_until','2099-12-31'),('installation_id',str(uuid.uuid4()))]:
            modified=json.loads(raw);modified['payload'][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'Signatur'):
                self.store.preview_license({'file':json.dumps(modified)})
        with self.assertRaisesRegex(ValueError,'anderen Installation'):
            self.activate(self.license(installation_id=str(uuid.uuid4())))
        modified=json.loads(raw);modified['key_id']='0'*64
        with self.assertRaisesRegex(ValueError,'Hersteller'):self.activate(json.dumps(modified))
        modified=json.loads(raw);modified['payload']['device_limit']=100000
        with self.assertRaisesRegex(ValueError,'passen nicht'):self.activate(json.dumps(modified))
        self.assertEqual(self.store.license_status(),active)

    def test_strict_file_validation_and_existing_license_survives(self):
        active=self.activate(self.license())
        raw=self.license()
        malformed=['', '[]', '{', '{}', '\ud800', 'x'*16385, None, {}, [], 123,
                   raw.replace('"format":', '"format":"duplicate","format":',1),
                   raw.replace('"issued_at":', '"issued_at":NaN,"other":',1)]
        for value in malformed:
            with self.subTest(value=str(value)[:50]),self.assertRaises(ValueError):self.store.preview_license({'file':value})
        self.assertEqual(self.store.license_status(),active)

    def test_dates_inclusive_expiration_locks_checks_and_renewal_restores(self):
        raw=self.license(valid_until=today().isoformat())
        self.activate(raw)
        ids=[self.add(n) for n in range(12)]
        sid=self.store.save_service(dict(device_id=ids[-1],type='tcp',name='Weiter prüfen',port=443))
        before={table:self.store.rows('SELECT * FROM '+table) for table in ['devices','services']}
        self.assertEqual(self.store.license_status()['status'],'active')
        with patch('netzmonitor.licensing.today',return_value=today()+timedelta(days=1)):
            state=self.store.state();result=state['license']
            self.assertTrue(all(d['license_blocked'] for d in state['devices']))
            self.assertEqual(state['services'][0]['effective_status'],'unlicensed')
            self.assertEqual(result['permitted_devices'],0)
            self.assertEqual(result['status'],'expired');self.assertTrue(result['over_limit'])
            self.assertEqual(result['device_limit'],10)
            with self.assertRaisesRegex(ValueError,'Gerätebegrenzung'):self.add(99)
            with self.assertRaisesRegex(ValueError,'abgelaufen'):self.activate(raw)
            self.assertEqual(self.store.rows('SELECT * FROM services'),before['services'])
            self.assertEqual(self.store.license_status()['used_devices'],12)
            self.assertEqual(self.store.rows('SELECT enabled FROM services WHERE id=?',(sid,))[0]['enabled'],1)
        self.activate(self.license(valid_until=(today()+timedelta(days=365)).isoformat()))
        self.add(99)
        self.assertFalse(any(d['license_blocked'] for d in self.store.state()['devices']))

    def test_not_yet_valid_file_and_clock_backwards(self):
        raw=self.license(valid_from=(today()+timedelta(days=1)).isoformat())
        with self.assertRaisesRegex(ValueError,'noch nicht gültig'):self.activate(raw)
        self.activate(self.license())
        with patch('netzmonitor.licensing.today',return_value=today()-timedelta(days=1)):
            self.assertEqual(self.store.license_status()['status'],'not_yet_valid')

    def test_preview_revision_and_failed_import_are_atomic(self):
        raw=self.license();preview=self.store.preview_license({'file':raw})
        self.assertEqual(self.store.license_status()['status'],'free')
        self.activate(self.license('service-500'))
        with self.assertRaisesRegex(ValueError,'inzwischen'):self.store.import_license(dict(file=raw,revision=preview['revision']))
        current=self.store.license_status()
        with self.assertRaises(ValueError):self.store.import_license(dict(file='{}',revision=current['revision']))
        self.assertEqual(self.store.license_status(),current)
        for rev in [None,True,'1',-1]:
            with self.assertRaises(ValueError):self.store.import_license(dict(file=raw,revision=rev))

    def test_corrupt_or_missing_key_is_visible_but_does_not_stop_checks(self):
        self.activate(self.license())
        ident=self.add(1);self.store.save_service(dict(device_id=ident,type='ping',name='Ping'))
        with patch('netzmonitor.licensing.PUBLIC_KEY',Path(self.temp.name)/'missing.pem'):
            state=self.store.state();self.assertEqual(state['license']['status'],'invalid')
            self.assertEqual(state['services'][0]['enabled'],1)
        with self.store.connect() as db:db.execute("UPDATE license_state SET document='broken'")
        self.assertEqual(self.store.state()['license']['status'],'invalid')

    def test_existing_large_installation_keeps_every_device(self):
        self.activate(self.license())
        for n in range(15):self.add(n)
        before=self.store.rows('SELECT * FROM devices')
        with self.store.connect() as db:db.execute('DROP TABLE license_state')
        upgraded=Store(self.temp.name)
        after=upgraded.rows('SELECT * FROM devices')
        self.assertTrue(all(d['license_blocked'] for d in after))
        self.assertEqual([{k:v for k,v in d.items() if k not in ('revision','license_blocked')} for d in after],[{k:v for k,v in d.items() if k not in ('revision','license_blocked')} for d in before])
        self.assertTrue(upgraded.license_status()['over_limit'])
        with self.assertRaisesRegex(ValueError,'Gerätebegrenzung'):upgraded.save_device(dict(address='new.test'))
        upgraded.save_device(dict(id=before[0]['id'],name='Bearbeitet',address=before[0]['address']))

    def test_signatures_verify_with_independent_cryptography_when_installed(self):
        try:
            from cryptography.hazmat.primitives import hashes,serialization
            from cryptography.hazmat.primitives.asymmetric import padding
        except ImportError:self.skipTest('optionale unabhängige cryptography-Prüfung nicht verfügbar')
        import base64
        document=json.loads(self.license())
        key=serialization.load_pem_public_key(self.pem.encode())
        key.verify(base64.b64decode(document['signature']),canonical(document['payload']),
                   padding.PSS(mgf=padding.MGF1(hashes.SHA256()),salt_length=32),hashes.SHA256())


if __name__=='__main__':unittest.main()
