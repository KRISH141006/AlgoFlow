"""Copy the original tracker, import the real batch, and create an isolated demo."""
import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.database import migrate
from backend.services import ingest
import json


def copy_database(source, destination):
    destination.parent.mkdir(parents=True,exist_ok=True)
    src=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)
    dst=sqlite3.connect(destination)
    try: src.backup(dst)
    finally: src.close(); dst.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,default=ROOT.parent/'dsa_tracker_app/dsa_tracker.db')
    parser.add_argument('--export',type=Path,default=Path.home()/'Downloads/sync_at_10_1_2026_6h11_leetcode.json')
    parser.add_argument('--refresh-demo',action='store_true',help='Replace demo.db with a fresh copy of personal.db; personal data is preserved')
    args=parser.parse_args()
    personal=ROOT/'data/personal.db'
    if not personal.exists():
        if args.source.exists():
            snapshot=ROOT/'data/backups'/f'original-{datetime.now().strftime("%Y%m%d-%H%M%S")}.db'
            copy_database(args.source.resolve(),snapshot)
            copy_database(snapshot,personal)
            print('Original tracker backed up; working copy created.')
        else:
            print('No source tracker found; creating an empty personal database.')
    os.environ['ALGOFLOW_DB']=str(personal)
    migrate()
    if args.export.exists():
        print('Batch import:',json.dumps(ingest(json.loads(args.export.read_text()))))
    else: print('Export not found. Use the interface to import JSON.')
    demo=ROOT/'data/demo.db'
    if not demo.exists() or args.refresh_demo:
        if demo.exists():
            snapshot=ROOT/'data/backups'/f'demo-{datetime.now().strftime("%Y%m%d-%H%M%S")}.db'
            copy_database(demo,snapshot)
        copy_database(personal,demo)
        print('Isolated demo database prepared.')
    print('Ready: data/personal.db and data/demo.db')


if __name__=='__main__': main()
