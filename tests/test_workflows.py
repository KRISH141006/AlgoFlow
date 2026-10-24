import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import migrate, connection
from backend.services import ingest, today, after

EXPORT=Path.home()/'Downloads/sync_at_10_1_2026_6h11_leetcode.json'
SOURCE=Path('/Users/krishsondagar/Krish/code/Ideas/dsa_tracker_app/dsa_tracker.db')


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('ALGOFLOW_DB',str(tmp_path/'test.db'))
    with TestClient(app) as client:
        yield client


def submission(**changes):
    return {'platform':'leetcode','id':'20','name':'Valid Parentheses','slug':'valid-parentheses','difficulty':'Easy','topic_tags':['Stack'],'problem_html':'<p>Given brackets.</p>','userCode':'class Solution {};','language':'cpp',**changes}


def upload(client,data,path='/sync/upload'):
    return client.post('/api/v1'+path,files={'file':('data.json',json.dumps(data),'application/json')})


def test_real_batch_exact_code_and_repeat(client):
    if not EXPORT.exists(): pytest.skip('Personal export is not available')
    data=json.loads(EXPORT.read_text())
    result=upload(client,data)
    assert result.status_code==200
    assert result.json()=={'created':274,'updated':0,'skipped':0,'invalid':0,'errors':[]}
    items=client.get('/api/v1/problems').json()
    assert len(items)==274
    assert all(p['solve_state']=='accepted' and p['solved_at'] is None and p['next_review_date']==after(today(),1) for p in items)
    assert client.get('/api/v1/stats').json()['heatmap']=={}
    for source in data:
        p=next(p for p in items if p['slug']==source['slug'])
        version=client.get(f'/api/v1/problems/{p["id"]}/versions').json()[0]
        assert version['code']==source['userCode']
        assert p['problem_html']
    again=upload(client,data).json()
    assert again['skipped']==274 and again['created']==again['updated']==0
    stats=client.get('/api/v1/stats').json()
    assert stats['versions']==274
    assert stats['difficulty']=={'Easy':143,'Medium':98,'Hard':33}


def test_original_migration_preserves_state(tmp_path,monkeypatch):
    if not SOURCE.exists(): pytest.skip('Original tracker is not available')
    dest=tmp_path/'migrated.db'
    original=sqlite3.connect(SOURCE.as_uri()+'?mode=ro',uri=True)
    copied=sqlite3.connect(dest); original.backup(copied); copied.close()
    before={t:original.execute(f'SELECT * FROM {t} ORDER BY id').fetchall() for t in ('problems','topics','review_history','topic_review_history')}
    columns=[r[1] for r in original.execute('PRAGMA table_info(problems)')]
    original.close();monkeypatch.setenv('ALGOFLOW_DB',str(dest))
    migrate();migrate()
    with connection() as db:
        for t in before:
            selection=','.join(columns) if t=='problems' else '*'
            assert [tuple(r) for r in db.execute(f'SELECT {selection} FROM {t} ORDER BY id')]==before[t]
        p=db.execute('SELECT * FROM problems WHERE id=1').fetchone()
        assert p['slug']=='apply-operations-on-array-to-maximize-sum-of-squares'
    ingest(submission(slug=p['slug'],name='A canonical title'))
    with connection() as db:
        row=db.execute('SELECT * FROM problems WHERE id=1').fetchone()
        assert row['name']==p['name'] and row['next_review_date']==p['next_review_date'] and row['stage']==p['stage']
        assert db.execute('SELECT COUNT(*) FROM problems').fetchone()[0]==1


def test_gfg_shapes_distinct_ids_and_repeat(client):
    data={'id':700226,'name':'Square Root','slug':'square-root','difficulty':'Easy','problem_question':'<p>Square root</p>', 'submission':{'submission_id':'a','code':'return 1;','language':'cpp','status':'Correct'}}
    assert upload(client,data).json()['created']==1
    assert upload(client,data).json()['skipped']==1
    data['submission']['submission_id']='b'
    assert upload(client,data).json()['updated']==1
    assert client.get('/api/v1/stats').json()['versions']==2
    universal={'platform':'gfg','slug':'another-problem','name':'Another problem','difficulty':1,'userCode':'return 2;','language':'C++','problem_html':'<p>Test</p>'}
    assert upload(client,[universal]).json()['created']==1


def test_invalid_records_and_html(client):
    raw=submission(problem_html='<script>alert(1)</script><p onclick="alert(2)">Safe <a href="javascript:alert(3)">link</a><img src="x" onerror="alert(4)"></p>')
    report=upload(client,[raw,{'name':'broken'}]).json()
    assert report['created']==report['invalid']==1
    p=client.get('/api/v1/problems').json()[0]
    assert 'script' not in p['problem_html'] and 'onclick' not in p['problem_html'] and 'javascript:' not in p['problem_html'] and 'onerror' not in p['problem_html']
    response=client.post('/api/v1/sync/upload',files={'file':('bad.json','{broken','application/json')})
    assert response.status_code==400


def test_review_cycle_and_replay(client):
    upload(client,submission())
    pid=client.get('/api/v1/problems').json()[0]['id']
    assert client.post(f'/api/v1/problems/{pid}/review',json={'expected_stage':0}).status_code==409
    for stage,interval in [(0,7),(1,30),(2,180),(3,None)]:
        with connection(write=True) as db: db.execute('UPDATE problems SET next_review_date=? WHERE id=?',(after(today(),-1),pid))
        response=client.post(f'/api/v1/problems/{pid}/review',json={'expected_stage':stage})
        assert response.status_code==200
        assert response.json()['stage']==stage+1
        assert response.json()['next_review_date']==(after(today(),interval) if interval else None)
        assert client.post(f'/api/v1/problems/{pid}/review',json={'expected_stage':stage}).status_code==409
    item=client.get(f'/api/v1/problems/{pid}').json()
    assert item['status']=='mastered' and len(item['history'])==4


def test_concurrent_review_only_advances_once(client):
    upload(client,submission())
    with connection(write=True) as db: db.execute('UPDATE problems SET next_review_date=?',(after(today(),-1),))
    from backend.services import complete_review
    def review():
        try: complete_review('problems','problem',1,0);return 200
        except Exception as e: return e.status_code
    with ThreadPoolExecutor(max_workers=2) as pool: statuses=list(pool.map(lambda _:review(),range(2)))
    assert sorted(statuses)==[200,409]
    assert len(client.get('/api/v1/problems/1').json()['history'])==1


def test_version_persists_without_review(client):
    upload(client,submission())
    old=client.get('/api/v1/problems/1').json()
    response=client.post('/api/v1/problems/1/versions',json={'code':'select * from answers;','language':'mysql','commit_message':'SQL experiment','what_is_good':'Readable','what_is_bad':'Needs an index'})
    assert response.status_code==201 and response.json()['accepted']==0
    with TestClient(app) as restarted:
        new=restarted.get('/api/v1/problems/1').json()
        assert len(new['versions'])==2 and new['versions'][0]['code']=='select * from answers;'
        assert new['next_review_date']==old['next_review_date'] and new['history']==[]


def test_backup_roundtrip_and_id_remapping(client,tmp_path,monkeypatch):
    upload(client,submission())
    client.post('/api/v1/topics',json={'name':'Sliding Window','notes':'Expand and shrink'})
    with connection(write=True) as db:
        db.execute('UPDATE problems SET next_review_date=?',(after(today(),-1),))
        db.execute('UPDATE topics SET next_review_date=?',(after(today(),-1),))
    client.post('/api/v1/problems/1/review',json={'expected_stage':0})
    client.post('/api/v1/topics/1/review',json={'expected_stage':0})
    client.post('/api/v1/problems/1/versions',json={'code':'return true;','language':'cpp','commit_message':'Better approach'})
    backup=client.get('/api/v1/backup/export').json()
    monkeypatch.setenv('ALGOFLOW_DB',str(tmp_path/'restored.db')); migrate()
    upload(client,submission(slug='unrelated',name='Unrelated'))
    result=upload(client,backup,'/backup/restore')
    assert result.status_code==200
    data=client.get('/api/v1/problems').json()
    p=next(p for p in data if p['slug']=='valid-parentheses')
    assert p['id']!=1 and p['stage']==1
    full=client.get(f'/api/v1/problems/{p["id"]}').json()
    assert len(full['versions'])==2 and len(full['history'])==1
    assert client.get('/api/v1/topics/1').json()['history'][0]['stage_completed']==1
    again=upload(client,backup,'/backup/restore').json()
    assert again['created']==again['updated']==0


def test_bad_backup_rolls_back(client):
    upload(client,submission())
    backup=client.get('/api/v1/backup/export').json()
    backup['problem_versions'][0]['problem_id']=999
    assert upload(client,backup,'/backup/restore').status_code==400
    assert client.get('/api/v1/stats').json()['totalProblems']==1


def test_unexpected_import_write_failure_is_atomic(client,monkeypatch):
    from backend import services
    save=services.save_version
    attempts=0
    def fail_second(*args,**kwargs):
        nonlocal attempts
        attempts+=1
        if attempts==2: raise sqlite3.OperationalError('Simulated failure')
        return save(*args,**kwargs)
    monkeypatch.setattr(services,'save_version',fail_second)
    result=upload(client,[submission(),submission(slug='two-sum',name='Two Sum')])
    assert result.status_code==500
    assert client.get('/api/v1/stats').json()['totalProblems']==0


def test_manual_entries_topics_and_validation(client):
    assert client.post('/api/v1/problems',json={'name':' ','difficulty':'Easy','link':'https://example.com'}).status_code==422
    response=client.post('/api/v1/problems',json={'name':'Manual exercise','difficulty':'Easy','link':'https://example.com/question'})
    assert response.status_code==201 and response.json()['solve_state']=='unverified'
    topic=client.post('/api/v1/topics',json={'name':'DP','notes':'States and transitions'}).json()
    assert client.get(f'/api/v1/topics/{topic["id"]}').status_code==200
    assert client.post(f'/api/v1/topics/{topic["id"]}/review',json={'expected_stage':0}).status_code==409


def test_live_record_identity_mismatch_and_manual_link_validation(client):
    result=upload(client,submission(url='https://www.geeksforgeeks.org/problems/valid-parentheses/1'))
    assert result.json()['invalid']==1 and result.json()['created']==0
    response=client.post('/api/v1/problems',json={'name':'Test','difficulty':'Easy','link':'javascript:alert(1)'})
    assert response.status_code==422


def test_import_enrichment_preserves_existing_manual_activity(client):
    client.post('/api/v1/problems',json={'name':'My original title','difficulty':'Easy','link':'https://leetcode.com/problems/valid-parentheses/'})
    before=client.get('/api/v1/stats').json()['heatmap']
    assert before[today()]==1
    assert upload(client,submission()).json()['updated']==1
    assert client.get('/api/v1/stats').json()['heatmap']==before
    assert client.get('/api/v1/problems/1').json()['name']=='My original title'
