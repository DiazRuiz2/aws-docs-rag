"""Run the installed local stack without implicit downloads or OneDrive artifacts."""
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
os.chdir(root)
values = {}
config = root / '.env'
if config.exists():
    for line in config.read_text(encoding='utf-8').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('\"\'')
state = Path(os.environ.get('RAG_STATE_DIR', values.get('RAG_STATE_DIR', str(root / '.rag_state')))).resolve()
env = dict(os.environ)
env.update(UV_PROJECT_ENVIRONMENT=str(state / 'venv'), UV_CACHE_DIR=str(state / 'uv-cache'),
           UV_OFFLINE='1', HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
           ANONYMIZED_TELEMETRY='False', TOKENIZERS_PARALLELISM='false')
env.setdefault('OMP_NUM_THREADS', '2')
env.setdefault('MKL_NUM_THREADS', '2')
args = sys.argv[1:]
if not args:
    args = ['--help']
if args[0] == 'sync':
    command = [str(state / 'tools/uv'), 'sync', '--locked', '--offline']
elif args[0] == 'test':
    command = [str(state / 'venv/bin/python'), '-m', 'unittest', 'discover', '-s', 'tests', '-v']
elif args[0] == 'serve':
    env.update(OLLAMA_MODELS=str(state / 'ollama/models'), OLLAMA_HOST='127.0.0.1:11434',
               OLLAMA_NUM_PARALLEL='1', OLLAMA_MAX_LOADED_MODELS='1',
               OLLAMA_NO_CLOUD='1', OLLAMA_NOPRUNE='true')
    command = [str(state / 'tools/ollama/bin/ollama'), 'serve']
elif args[0] == 'demo':
    command = [str(state / 'venv/bin/python'), str(root / 'scripts/demo.py'), *args[1:]]
else:
    command = [str(state / 'venv/bin/python'), '-m', 'aws_rag', *args]
if not Path(command[0]).is_file():
    sys.exit('Local runtime is not installed at ' + str(state))
os.execve(command[0], command, env)
