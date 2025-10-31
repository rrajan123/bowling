Bowling Like + Tabs — Quick Start
================================

Files included
--------------
- app.py                : Flask app with Like APIs + auto-migration
- bowling.sqlite3       : Your DB snapshot (optional)
- templates/index.html  : Front page with New Session + Tabs (Sessions/Totals/Honor Roll)
- static/app.js         : Frontend with improved error messages and Like UI
- tools/sql_fix_like_count.sql : Manual SQL to add 'like_count' if needed

Install
-------
1) Unzip into your project folder, e.g.
   C:\sites\bowling\
   or your TrueNAS path.

2) Ensure structure:
   app.py
   bowling.sqlite3
   /templates/index.html
   /static/app.js
   /tools/sql_fix_like_count.sql

3) Run the app:
   python app.py

4) In the UI:
   - New Session on the front page
   - Use tabs to view Sessions, Totals, Honor Roll
   - In Sessions, click a session's "Games" → modal opens → click 👍 Like per game

Troubleshooting Likes
---------------------
- If you click 👍 and see an error mentioning 'like_count':
    sqlite3 bowling.sqlite3 < tools/sql_fix_like_count.sql
  Then restart Flask.

- If you see 'Game not found', refresh the page (Ctrl+F5) to ensure the updated JS is loaded
  and verify /api/session/<id>/games returns 'id' for each game in the response.
