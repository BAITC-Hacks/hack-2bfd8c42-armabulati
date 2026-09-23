"""Local machine-owner recovery; never expose this operation as an HTTP endpoint."""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import auth, store

def main():
    parser=argparse.ArgumentParser(description='Reset a local Dauys Hunt email account password')
    parser.add_argument('email')
    args=parser.parse_args()
    with store.connect() as con:
        user=con.execute("SELECT id FROM users WHERE login=? AND provider='email'",(args.email.strip().lower(),)).fetchone()
    if not user:
        raise SystemExit('Local email account not found.')
    password=getpass.getpass('New password (12-128 characters): ')
    if not 12<=len(password.strip())<=128 or password!=getpass.getpass('Repeat password: '):
        raise SystemExit('Passwords must match and have 12-128 characters.')
    encoded=auth.password_hash(password)
    with store.connect() as con:
        con.execute('UPDATE users SET password_hash=? WHERE id=?',(encoded,user['id']))
        con.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
    print('Password updated. Existing sessions revoked.')

if __name__=='__main__': main()
