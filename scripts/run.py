"""Start with environment variables, or prompt without echo/persistence on local Windows/macOS/Linux."""
import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
parser=argparse.ArgumentParser()
parser.add_argument('--prompt-secrets',action='store_true')
parser.add_argument('--reload',action='store_true',help='Local development only; retain environment across code reloads')
parser.add_argument('--port',type=int,default=int(os.getenv('PORT','8000')))
args=parser.parse_args()
if args.prompt_secrets:
    os.environ['EKT_API_USERNAME']=input('EKT username (blank for demo): ').strip()
    if os.environ['EKT_API_USERNAME']:
        os.environ['EKT_API_PASSWORD']=getpass.getpass('EKT password: ')
    os.environ['OPENAI_API_KEY']=getpass.getpass('OpenAI API key (blank for text-only mode): ').strip()

import uvicorn
uvicorn.run('backend.app:app',host=os.getenv('HOST','127.0.0.1'),port=args.port,access_log=False,reload=args.reload)
