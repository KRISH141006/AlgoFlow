# Faculty walkthrough — 5 minutes

## Before presenting

Run `./start.sh`, open http://127.0.0.1:3000, and confirm the header says **Demo workspace**. Use the demonstration database only.

If you have practiced the review flow already, stop the server and run `.venv/bin/python scripts/prepare_data.py --refresh-demo` before restarting. This preserves a backup of your practice run.

## 1. Explain the problem

“I have solved around 290 DSA problems, but solved once does not mean remembered. This app stores my actual accepted solutions, schedules revision, and lets me record improved versions.”

“The imported snapshot contains 274 accepted problems. The library also preserves one record from my previous tracker.”

## 2. Show real data and safe import

Open Library, search **Valid Parentheses**, and open its description and Solutions tab. Show that this is your saved C++ solution, not generated example data.

Optional: choose Import JSON and upload `sync_at_10_1_2026_6h11_leetcode.json` from Downloads. The result should show **274 skipped, zero created**, demonstrating duplicate protection.

For a GFG example, import `gfg_auto_square-root_1789620725521.json` from Downloads, then filter to GeeksforGeeks. This affects the demo database only.

## 3. Save your reasoning

On Valid Parentheses, choose Save version. Keep the code, add a message such as “Document stack approach,” and write what works well. Save it and select the latest version.

Explain: “Each deliberate commit is a new immutable snapshot. Saving a version does not claim it passed platform tests or complete a revision.”

## 4. Complete a real due review

Return to Today. The preserved tracker problem **leetcode 2312** is overdue. Click Complete once.

The review disappears from the due queue and Reviews today increases. Find the problem in Library and show Stage 1 and the next review seven days later.

Explain the schedule: first recall after one day, second recall after seven days, re-solve after thirty days, then long-term review after 180 days.

## 5. Show persistence and backend

Stop the server with Ctrl+C, run `./start.sh` again, and refresh the page. Show the saved version and completed review still exist.

Open the settings icon → Download complete backup. Show `/docs` to explain the API, validation, and routes.

## If asked about historical dates

“The export includes solutions but not original solve timestamps. We show an import date, leave solved date unavailable, and do not invent activity for the heatmap.”

## If asked about authorship

“This demo was built with AI assistance. My handwritten extension collects the data. My next step is to learn and rebuild the backend in small milestones so I can explain and own the implementation.”

## Architecture to explain

Browser UI → FastAPI validation → ingestion/review service → SQLite transaction.

Problems, versions, and review histories are separate. A review transaction advances exactly one expected stage. Import identity and code fingerprints prevent accidental duplicates. Personal and demonstration databases are separate files.
