"""Find an installed Codex CLI after editor extension updates move its binary."""
import os,shutil
from pathlib import Path

def resolve(cfg):
 candidates=[cfg.get('codex_path',''),shutil.which('codex')]
 extensions=Path.home()/'.vscode/extensions'
 if extensions.exists():
  candidates += [str(p) for p in sorted(extensions.glob('openai.chatgpt-*/bin/macos-aarch64/codex'),key=lambda p:p.stat().st_mtime,reverse=True)]
 candidates += ['/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex']
 for value in candidates:
  if value and Path(value).is_file() and os.access(value,os.X_OK):return str(value)
 raise ValueError('The Mac research CLI is unavailable. Open or update the ChatGPT/Codex app, then retry.')
