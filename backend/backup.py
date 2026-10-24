"""Validated additive backup restore with remapped parent IDs."""
import json
from datetime import date
from fastapi import HTTPException
from .database import connection
from .services import clean_html, fingerprint

TABLES = ['problems','topics','review_history','topic_review_history','problem_versions']


def export_backup():
    with connection() as db:
        return {'format':'algoflow', 'schema_version':2, **{table:[dict(r) for r in db.execute(f'SELECT * FROM {table} ORDER BY id')] for table in TABLES}}


def validate_backup(data):
    if not isinstance(data,dict) or data.get('format') != 'algoflow' or data.get('schema_version') != 2:
        raise ValueError('Expected an AlgoFlow schema version 2 backup')
    for table in TABLES:
        if not isinstance(data.get(table),list):
            raise ValueError('Missing backup table: '+table)
    parents = {}
    for table in ('problems','topics'):
        ids = set()
        for row in data[table]:
            if not isinstance(row,dict) or not isinstance(row.get('id'),int) or row['id'] <= 0 or row['id'] in ids:
                raise ValueError('Invalid or duplicate '+table+' ID')
            ids.add(row['id'])
            if not isinstance(row.get('name'),str) or not row['name'].strip():
                raise ValueError('Missing item name')
            if type(row.get('stage')) is not int or row['stage'] not in range(5):
                raise ValueError('Invalid review stage')
            if row.get('status') != ('mastered' if row['stage']==4 else 'pending'):
                raise ValueError('Review status does not match stage')
            date.fromisoformat(row['date_added'])
            if row['stage']<4:
                date.fromisoformat(row['next_review_date'])
            elif row.get('next_review_date') is not None:
                raise ValueError('Mastered item cannot have a review date')
            if table=='problems':
                if row.get('difficulty') not in ('Easy','Medium','Hard') or row.get('platform') not in ('manual','leetcode','gfg') or row.get('solve_state') not in ('accepted','unverified'):
                    raise ValueError('Invalid problem classification')
                for key in ('topic_tags','company_tags'):
                    tags=json.loads(row[key])
                    if not isinstance(tags,list) or any(not isinstance(t,str) for t in tags):
                        raise ValueError('Invalid tags')
        parents[table]=ids
    for table,key,parent in [('review_history','problem_id','problems'),('topic_review_history','topic_id','topics'),('problem_versions','problem_id','problems')]:
        for row in data[table]:
            if not isinstance(row,dict) or row.get(key) not in parents[parent]:
                raise ValueError('Backup contains an orphan record')
            if table=='problem_versions':
                if not all(isinstance(row.get(k),str) and row[k] for k in ('code','language','commit_message','created_at','delivery_key')) or row.get('accepted') not in (0,1):
                    raise ValueError('Invalid solution version')
                if row.get('fingerprint') != fingerprint(row['language'],row['code']):
                    raise ValueError('Solution fingerprint mismatch')
            else:
                date.fromisoformat(row['review_date'])
                if row.get('stage_completed') not in (1,2,3,4) or row.get('was_on_time') not in (0,1):
                    raise ValueError('Invalid review history')


def restore_backup(data):
    try:
        validate_backup(data)
        report={'created':0,'updated':0,'skipped':0}
        with connection(write=True) as db:
            maps={}
            for table in ('problems','topics'):
                mapping={}
                columns=[r['name'] for r in db.execute(f'PRAGMA table_info({table})') if r['name']!='id']
                for row in data[table]:
                    if table=='problems':
                        old=db.execute('SELECT * FROM problems WHERE platform=? AND slug=? ORDER BY id LIMIT 1',(row['platform'],row.get('slug'))).fetchone() if row.get('slug') else db.execute('SELECT * FROM problems WHERE link=? AND name=?',(row['link'],row['name'])).fetchone()
                    else:
                        old=db.execute('SELECT * FROM topics WHERE name=? AND category=?',(row['name'],row['category'])).fetchone()
                    values=[row.get('historical_import', int(bool(row.get('imported_at')))) if c=='historical_import' else row[c] for c in columns]
                    if table=='problems':
                        values[columns.index('problem_html')]=clean_html(row['problem_html'])
                    if old:
                        mapping[row['id']]=old['id']
                        changed=False
                        if row['stage']>old['stage']:
                            db.execute(f'UPDATE {table} SET stage=?,next_review_date=?,status=? WHERE id=?',(row['stage'],row['next_review_date'],row['status'],old['id']))
                            changed=True
                        if table=='problems':
                            for key in ('platform_id','problem_html','imported_at','solved_at'):
                                if not old[key] and row.get(key):
                                    db.execute(f'UPDATE problems SET {key}=? WHERE id=?',(clean_html(row[key]) if key=='problem_html' else row[key],old['id']))
                                    changed=True
                            if old['solve_state']!='accepted' and row['solve_state']=='accepted':
                                db.execute("UPDATE problems SET solve_state='accepted' WHERE id=?",(old['id'],)); changed=True
                            for key in ('topic_tags','company_tags'):
                                merged=list(dict.fromkeys(json.loads(old[key])+json.loads(row[key])))
                                if merged!=json.loads(old[key]):
                                    db.execute(f'UPDATE problems SET {key}=? WHERE id=?',(json.dumps(merged),old['id'])); changed=True
                        report['updated' if changed else 'skipped']+=1
                    else:
                        cursor=db.execute(f'INSERT INTO {table} ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})',values)
                        mapping[row['id']]=cursor.lastrowid
                        report['created']+=1
                maps[table]=mapping
            for table,parent,key in [('review_history','problems','problem_id'),('topic_review_history','topics','topic_id'),('problem_versions','problems','problem_id')]:
                columns=[r['name'] for r in db.execute(f'PRAGMA table_info({table})') if r['name']!='id']
                for original in data[table]:
                    row=dict(original); row[key]=maps[parent][row[key]]
                    if table=='problem_versions':
                        exists=db.execute('SELECT id FROM problem_versions WHERE problem_id=? AND delivery_key=?',(row[key],row['delivery_key'])).fetchone()
                        row['version_number']=db.execute('SELECT COALESCE(MAX(version_number),0)+1 FROM problem_versions WHERE problem_id=?',(row[key],)).fetchone()[0]
                    else:
                        exists=db.execute(f'SELECT id FROM {table} WHERE {key}=? AND review_date=? AND stage_completed=?',(row[key],row['review_date'],row['stage_completed'])).fetchone()
                    if exists:
                        report['skipped']+=1
                    else:
                        db.execute(f'INSERT INTO {table} ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})',[row[c] for c in columns]); report['created']+=1
        return report
    except (ValueError,KeyError,TypeError) as exc:
        raise HTTPException(400,'Invalid backup: '+str(exc)) from exc
