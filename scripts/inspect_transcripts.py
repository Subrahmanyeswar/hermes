import sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8')
conn = sqlite3.connect('data/hermes.db')
for r in conn.execute("SELECT role, content FROM transcripts WHERE role = 'assistant' ORDER BY sequence DESC LIMIT 5"):
    print('ROLE:', r[0])
    print('CONTENT:', r[1][:400])
    print('-'*50)
