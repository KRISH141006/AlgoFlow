import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from .database import connection, database_path, identity_from_link, migrate
from .models import ProblemCreate, TopicCreate, VersionCreate, ReviewRequest
from .services import after, today, now, get_problem, serialize, ingest, save_version, complete_review, stats
from .backup import export_backup, restore_backup


@asynccontextmanager
async def lifespan(app):
    migrate()
    yield


app=FastAPI(title='AlgoFlow',description='Personal DSA revision and solution history',version='1.0.0',lifespan=lifespan)
API='/api/v1'


@app.exception_handler(sqlite3.Error)
async def database_error(request, exc):
    return JSONResponse(status_code=500,content={'detail':'The database operation failed; no partial changes were saved.'})


@app.get(API+'/health')
def health():
    return {'status':'ok','database':database_path().name,'mode':'demo' if database_path().name=='demo.db' else 'personal','today':today()}


@app.get(API+'/problems')
def problems():
    with connection() as db:
        return [serialize(r) for r in db.execute('''SELECT p.*, (SELECT COUNT(*) FROM problem_versions v WHERE v.problem_id=p.id) version_count
            FROM problems p ORDER BY p.id DESC''')]


@app.get(API+'/problems/due')
def due_problems():
    with connection() as db:
        return [serialize(r) for r in db.execute("SELECT * FROM problems WHERE next_review_date<=? AND status!='mastered' ORDER BY next_review_date,id",(today(),))]


@app.post(API+'/problems',status_code=201)
def add_problem(body:ProblemCreate):
    platform,slug=identity_from_link(body.link)
    with connection(write=True) as db:
        if slug and db.execute('SELECT id FROM problems WHERE platform=? AND slug=?',(platform,slug)).fetchone():
            raise HTTPException(409,'This problem is already in your library')
        cursor=db.execute('''INSERT INTO problems (name,difficulty,link,date_added,next_review_date,platform,slug,topic_tags)
            VALUES (?,?,?,?,?,?,?,?)''',(body.name,body.difficulty,body.link,today(),after(today(),1),platform,slug,json.dumps(body.topic_tags)))
        return get_problem(db,cursor.lastrowid)


@app.get(API+'/problems/{problem_id}')
def problem(problem_id:int):
    with connection() as db:
        return get_problem(db,problem_id)


@app.post(API+'/problems/{problem_id}/review')
def review_problem(problem_id:int,body:ReviewRequest):
    return complete_review('problems','problem',problem_id,body.expected_stage)


@app.get(API+'/problems/{problem_id}/versions')
def versions(problem_id:int):
    with connection() as db:
        return get_problem(db,problem_id)['versions']


@app.get(API+'/problems/{problem_id}/versions/{version_id}')
def version(problem_id:int,version_id:int):
    with connection() as db:
        get_problem(db,problem_id)
        row=db.execute('SELECT * FROM problem_versions WHERE id=? AND problem_id=?',(version_id,problem_id)).fetchone()
        if not row: raise HTTPException(404,'Version not found')
        return dict(row)


@app.post(API+'/problems/{problem_id}/versions',status_code=201)
def commit(problem_id:int,body:VersionCreate):
    with connection(write=True) as db:
        get_problem(db,problem_id)
        save_version(db,problem_id,body.model_dump())
        return get_problem(db,problem_id)['versions'][0]


@app.get(API+'/topics')
def topics():
    with connection() as db:
        return [dict(r) for r in db.execute('SELECT * FROM topics ORDER BY id DESC')]


@app.get(API+'/topics/due')
def due_topics():
    with connection() as db:
        return [dict(r) for r in db.execute("SELECT * FROM topics WHERE next_review_date<=? AND status!='mastered' ORDER BY next_review_date",(today(),))]


@app.get(API+'/topics/{topic_id}')
def topic(topic_id:int):
    with connection() as db:
        row=db.execute('SELECT * FROM topics WHERE id=?',(topic_id,)).fetchone()
        if not row: raise HTTPException(404,'Topic not found')
        return {**dict(row),'history':[dict(r) for r in db.execute('SELECT * FROM topic_review_history WHERE topic_id=?',(topic_id,))]}


@app.post(API+'/topics',status_code=201)
def add_topic(body:TopicCreate):
    with connection(write=True) as db:
        cursor=db.execute('INSERT INTO topics (name,category,notes,link,date_added,next_review_date) VALUES (?,?,?,?,?,?)',(body.name,body.category,body.notes,body.link,today(),after(today(),1)))
        return dict(db.execute('SELECT * FROM topics WHERE id=?',(cursor.lastrowid,)).fetchone())


@app.post(API+'/topics/{topic_id}/review')
def review_topic(topic_id:int,body:ReviewRequest):
    return complete_review('topics','topic',topic_id,body.expected_stage)


@app.post(API+'/sync/submission')
def sync_submission(body:dict):
    return ingest(body)


async def read_json(file):
    content=await file.read(25*1024*1024+1)
    if len(content)>25*1024*1024: raise HTTPException(413,'File exceeds 25 MB')
    try: return json.loads(content)
    except (ValueError,UnicodeDecodeError): raise HTTPException(400,'Choose a valid UTF-8 JSON file')


@app.post(API+'/sync/upload')
async def upload(file:UploadFile):
    return ingest(await read_json(file))


@app.get(API+'/stats')
def statistics():
    with connection() as db: return stats(db)


@app.get(API+'/heatmap')
def heatmap():
    with connection() as db: return stats(db)['heatmap']


@app.get(API+'/backup/export')
def export():
    return JSONResponse(export_backup(),headers={'Content-Disposition':'attachment; filename="algoflow_backup.json"'})


@app.post(API+'/backup/restore')
async def restore(file:UploadFile):
    return restore_backup(await read_json(file))


# API routes are registered before the frontend mount.
dist=Path(__file__).resolve().parents[1]/'frontend/dist'
if dist.exists(): app.mount('/',StaticFiles(directory=dist,html=True),name='frontend')
