"""Domain rules: imports, immutable snapshots, explicit reviews, and activity."""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import bleach
from fastapi import HTTPException
from .database import connection, identity_from_link

LOCAL_ZONE = ZoneInfo('Asia/Kolkata')


def today():
    return datetime.now(LOCAL_ZONE).date().isoformat()


def now():
    return datetime.now(timezone.utc).isoformat()


def after(day, days):
    return (datetime.fromisoformat(day).date() + timedelta(days=days)).isoformat()


def clean_html(value):
    value = re.sub(r'<(script|style)\b[^>]*>.*?</\1\s*>', '', value or '', flags=re.I | re.S)
    return bleach.clean(value, tags=['p','br','div','span','b','strong','i','em','u','pre','code','ul','ol','li','blockquote','h1','h2','h3','h4','table','thead','tbody','tr','td','th','sup','sub','a'], attributes={'a':['href','title']}, protocols=['http','https'], strip=True)


def serialize(row):
    item = dict(row)
    for key in ('topic_tags', 'company_tags'):
        if key in item:
            item[key] = json.loads(item[key] or '[]')
    if 'problem_html' in item:
        item['problem_html'] = clean_html(item['problem_html'])
    return item


def get_problem(db, problem_id):
    row = db.execute('SELECT * FROM problems WHERE id=?', (problem_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Problem not found')
    item = serialize(row)
    item['history'] = [dict(r) for r in db.execute('SELECT * FROM review_history WHERE problem_id=? ORDER BY id', (problem_id,))]
    item['versions'] = [dict(r) for r in db.execute('SELECT * FROM problem_versions WHERE problem_id=? ORDER BY version_number DESC', (problem_id,))]
    return item


def fingerprint(language, code):
    return hashlib.sha256((language + '\0' + code).encode()).hexdigest()


def save_version(db, problem_id, values, source='manual', accepted=0, submission_id=None, created_at=None):
    digest = fingerprint(values['language'], values['code'])
    key = 'submission:' + str(submission_id) if submission_id else 'code:' + digest
    if source == 'manual':
        # Every deliberate commit may include a different assessment of identical code.
        key = 'manual:' + hashlib.sha256((now() + values['commit_message']).encode()).hexdigest()
    if db.execute('SELECT id FROM problem_versions WHERE problem_id=? AND delivery_key=?', (problem_id, key)).fetchone():
        return False
    number = db.execute('SELECT COALESCE(MAX(version_number),0)+1 FROM problem_versions WHERE problem_id=?', (problem_id,)).fetchone()[0]
    db.execute('''INSERT INTO problem_versions
        (problem_id,version_number,commit_message,code,language,what_is_good,what_is_bad,time_complexity,space_complexity,created_at,accepted,source,submission_id,fingerprint,delivery_key)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (problem_id, number, values['commit_message'], values['code'], values['language'], values.get('what_is_good',''), values.get('what_is_bad',''), values.get('time_complexity',''), values.get('space_complexity',''), created_at or now(), accepted, source, submission_id, digest, key))
    return True


def normalize(raw):
    if not isinstance(raw, dict):
        raise ValueError('Each submission must be an object')
    nested = raw.get('submission') or {}
    if not isinstance(nested, dict):
        raise ValueError('submission must be an object')
    link = raw.get('url') or raw.get('link') or ''
    inferred, linked_slug = identity_from_link(link)
    platform = raw.get('platform') or (inferred if inferred != 'manual' else 'gfg' if 'submission' in raw and 'problem_question' in raw else None)
    if platform not in ('leetcode', 'gfg'):
        raise ValueError('Cannot determine platform: provide leetcode or gfg')
    if inferred != 'manual' and inferred != platform:
        raise ValueError('Platform does not match problem URL')
    slug = raw.get('slug') or raw.get('problem_slug') or linked_slug
    name = raw.get('name') or raw.get('title')
    if not isinstance(slug, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', slug):
        raise ValueError('Missing or invalid problem slug')
    if not isinstance(name, str) or not name.strip():
        raise ValueError('Missing problem name')
    code = raw.get('userCode') or raw.get('code') or nested.get('code')
    language = raw.get('language') or nested.get('language')
    if not isinstance(code, str) or not code.strip() or not isinstance(language, str) or not language.strip():
        raise ValueError('Missing solution code or language')
    verdict = nested.get('status') or raw.get('status')
    if verdict is not None and str(verdict).lower() not in ('correct','accepted','ac','10','success'):
        raise ValueError('Submission is not accepted')
    difficulty = raw.get('difficulty')
    difficulty = {'0':'Easy','1':'Medium','2':'Hard', 'basic':'Easy','school':'Easy','easy':'Easy','medium':'Medium','hard':'Hard'}.get(str(difficulty).lower())
    if difficulty is None:
        raise ValueError('Unsupported or missing difficulty')
    language = {'c++':'cpp','cpp17':'cpp','cpp20':'cpp','c++17':'cpp','c++20':'cpp','sql':'mysql'}.get(language.lower(), language.lower())
    def tags(key):
        value = raw.get(key) or []
        if not isinstance(value, list) or any(not isinstance(tag, str) for tag in value):
            raise ValueError(key + ' must be a list of strings')
        return value
    return {'platform': platform, 'slug': slug, 'name': name.strip(), 'difficulty': difficulty,
            'link': f'https://leetcode.com/problems/{slug}/' if platform == 'leetcode' else f'https://www.geeksforgeeks.org/problems/{slug}/1',
            'platform_id': str(raw['id']) if raw.get('id') is not None else None,
            'topic_tags': tags('topic_tags'), 'company_tags': tags('company_tags'),
            'problem_html': clean_html(raw.get('problem_html') or raw.get('problem_question') or ''),
            'code': code, 'language': language, 'submission_id': nested.get('submission_id') or raw.get('submission_id')}


def ingest(data):
    rows = data if isinstance(data, list) else [data]
    if len(rows) > 10000:
        raise HTTPException(400, 'Maximum 10,000 records per import')
    report = {'created':0,'updated':0,'skipped':0,'invalid':0,'errors':[]}
    normalized = []
    for i, raw in enumerate(rows):
        try:
            normalized.append(normalize(raw))
        except (ValueError, TypeError, AttributeError) as exc:
            report['invalid'] += 1
            report['errors'].append({'record':i+1,'reason':str(exc)})
    # The complete valid portion is atomic: an unexpected write failure rolls it all back.
    with connection(write=True) as db:
        for p in normalized:
            old = db.execute('SELECT * FROM problems WHERE platform=? AND slug=? ORDER BY id LIMIT 1', (p['platform'], p['slug'])).fetchone()
            created = old is None
            if created:
                cursor = db.execute('''INSERT INTO problems
                    (name,difficulty,link,date_added,stage,next_review_date,status,platform,slug,platform_id,topic_tags,company_tags,problem_html,imported_at,historical_import,solve_state)
                    VALUES (?,?,?,?,0,?,'pending',?,?,?,?,?,?,?,1,'accepted')''',
                    (p['name'],p['difficulty'],p['link'],today(),after(today(),1),p['platform'],p['slug'],p['platform_id'],json.dumps(p['topic_tags']),json.dumps(p['company_tags']),p['problem_html'],now()))
                problem_id = cursor.lastrowid
                metadata_changed = False
            else:
                problem_id = old['id']
                metadata = {'platform_id':p['platform_id'] or old['platform_id'],
                            'topic_tags':json.dumps(p['topic_tags']) if p['topic_tags'] else old['topic_tags'],
                            'company_tags':json.dumps(p['company_tags']) if p['company_tags'] else old['company_tags'],
                            'problem_html':p['problem_html'] or old['problem_html'], 'solve_state':'accepted'}
                metadata_changed = any(old[k] != v for k,v in metadata.items())
                if metadata_changed:
                    db.execute('UPDATE problems SET platform_id=?,topic_tags=?,company_tags=?,problem_html=?,solve_state=?,imported_at=COALESCE(imported_at,?) WHERE id=?', (*metadata.values(),now(),problem_id))
            saved = save_version(db, problem_id, {**p,'commit_message':'Imported accepted submission'}, source='import', accepted=1, submission_id=p['submission_id'])
            report['created' if created else 'updated' if saved or metadata_changed else 'skipped'] += 1
    return report


def complete_review(table, parent, item_id, expected_stage):
    with connection(write=True) as db:
        row = db.execute(f'SELECT * FROM {table} WHERE id=?', (item_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Item not found')
        if row['stage'] != expected_stage or row['status'] == 'mastered':
            raise HTTPException(409, 'This review was already completed. Refresh the queue.')
        if not row['next_review_date'] or row['next_review_date'] > today():
            raise HTTPException(409, 'This item is not due yet')
        stage = row['stage'] + 1
        next_date = after(today(), {1:7,2:30,3:180}[stage]) if stage < 4 else None
        history = 'review_history' if table == 'problems' else 'topic_review_history'
        db.execute(f'INSERT INTO {history} ({parent}_id,review_date,stage_completed,was_on_time) VALUES (?,?,?,?)', (item_id,today(),stage,int(today() == row['next_review_date'])))
        db.execute(f'UPDATE {table} SET stage=?,next_review_date=?,status=? WHERE id=?', (stage,next_date,'mastered' if stage==4 else 'pending',item_id))
        return serialize(db.execute(f'SELECT * FROM {table} WHERE id=?', (item_id,)).fetchone())


def stats(db):
    activity = {}
    # Historical import dates are administrative, not dates on which problems were solved.
    queries = [('SELECT date_added AS day FROM problems WHERE historical_import=0','addition'),
               ('SELECT date_added AS day FROM topics','addition'),
               ('SELECT review_date AS day FROM review_history','review'),
               ('SELECT review_date AS day FROM topic_review_history','review')]
    for query, kind in queries:
        for row in db.execute(query):
            day = row['day']
            activity[day] = activity.get(day,0)+1
    days = sorted(activity)
    best = current = 0
    previous = None
    for day in days:
        current = current + 1 if previous and after(previous,1)==day else 1
        best = max(best,current)
        previous = day
    streak = 0
    day = today() if today() in activity else after(today(),-1)
    while day in activity:
        streak += 1
        day = after(day,-1)
    count = lambda sql: db.execute(sql).fetchone()[0]
    done = db.execute('SELECT (SELECT COUNT(*) FROM review_history WHERE review_date=?) + (SELECT COUNT(*) FROM topic_review_history WHERE review_date=?)', (today(),today())).fetchone()[0]
    return {'totalProblems':count('SELECT COUNT(*) FROM problems'), 'acceptedProblems':count("SELECT COUNT(*) FROM problems WHERE solve_state='accepted'"),
            'totalTopics':count('SELECT COUNT(*) FROM topics'), 'versions':count('SELECT COUNT(*) FROM problem_versions'),
            'mastered':count("SELECT COUNT(*) FROM problems WHERE status='mastered'"),
            'due':db.execute("SELECT COUNT(*) FROM problems WHERE next_review_date<=? AND status!='mastered'",(today(),)).fetchone()[0],
            'doneToday':done, 'streak':streak,'bestStreak':best,'heatmap':activity,
            'difficulty':{r['difficulty']:r['n'] for r in db.execute('SELECT difficulty,COUNT(*) n FROM problems GROUP BY difficulty')},
            'topics':{r['name']:r['n'] for r in db.execute("SELECT j.value name,COUNT(*) n FROM problems,json_each(topic_tags) j GROUP BY j.value ORDER BY n DESC LIMIT 12")},
            'today':today()}
