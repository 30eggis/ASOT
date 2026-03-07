#!/bin/bash
# Show telegram conversation history for the current or specified session.
# Usage:
#   telegram-history.sh                    # auto-detect latest session in current project
#   telegram-history.sh <session_id>       # specific session
#   telegram-history.sh --project <path>   # specific project path

PROJECT_DIR="${PWD}"
SESSION_ID=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --project)
      PROJECT_DIR="$2"
      shift 2
      ;;
    *)
      SESSION_ID="$1"
      shift
      ;;
  esac
done

# Convert project path to Claude's storage path
ENCODED_PATH=$(echo "$PROJECT_DIR" | sed 's|/|-|g')
CLAUDE_PROJECT_DIR="$HOME/.claude/projects/${ENCODED_PATH}"

if [ ! -d "$CLAUDE_PROJECT_DIR" ]; then
  echo "No Claude project found for: $PROJECT_DIR"
  echo "Looked in: $CLAUDE_PROJECT_DIR"
  exit 1
fi

# Find session file
if [ -z "$SESSION_ID" ]; then
  SESSION_FILE=$(ls -t "$CLAUDE_PROJECT_DIR"/*.jsonl 2>/dev/null | head -1)
else
  SESSION_FILE="$CLAUDE_PROJECT_DIR/${SESSION_ID}.jsonl"
fi

if [ ! -f "$SESSION_FILE" ]; then
  echo "No session file found."
  exit 1
fi

SESSION_NAME=$(basename "$SESSION_FILE" .jsonl)
SESSION_SHORT="${SESSION_NAME:0:8}"

python3 - "$SESSION_FILE" "$SESSION_SHORT" <<'PYEOF'
import json, sys

session_file = sys.argv[1]
session_short = sys.argv[2]
found = []

with open(session_file) as f:
    lines = f.readlines()

# Find all telegram-related messages and their responses
i = 0
while i < len(lines):
    obj = json.loads(lines[i])
    t = obj.get('type', '')
    msg = obj.get('message', {})
    content = msg.get('content', '')

    # Detect telegram user message
    if t == 'user' and isinstance(content, str) and '[recv_msg_tg]' in content:
        ts = obj.get('timestamp', '')
        text = content.replace('[recv_msg_tg] ', '').strip()
        found.append(('user', ts, text))

        # Follow the parentUuid chain to find assistant text response
        parent = obj.get('uuid', '')
        collected_text = []
        for j in range(i+1, min(i+50, len(lines))):
            next_obj = json.loads(lines[j])
            nt = next_obj.get('type', '')
            # Follow chain: assistant or user (tool_result) with matching parent
            if next_obj.get('parentUuid') == parent or (nt == 'assistant' and next_obj.get('parentUuid') == parent):
                next_msg = next_obj.get('message', {})
                next_content = next_msg.get('content', '')
                if isinstance(next_content, list):
                    texts = [c.get('text','') for c in next_content if isinstance(c, dict) and c.get('type') == 'text']
                    if texts:
                        collected_text.extend(texts)
                elif isinstance(next_content, str) and next_content.strip() and nt == 'assistant':
                    collected_text.append(next_content.strip())
                parent = next_obj.get('uuid', '')
            # Stop if we hit a new user message that's not tool_result
            elif nt == 'user':
                um = next_obj.get('message', {}).get('content', '')
                if isinstance(um, str) and '[recv_msg_tg]' not in um and not um.startswith('<'):
                    break
        if collected_text:
            found.append(('assistant', '', '\n'.join(collected_text).strip()))
    i += 1

if not found:
    print('No telegram conversations found in this session.')
    sys.exit(0)

print(f'--- Telegram History (session: {session_short}...) ---')
print()
for role, ts, text in found:
    time_str = ts[11:19] if len(ts) > 19 else ts
    if role == 'user':
        print(f'  [TG User] ({time_str})')
        print(f'  > {text}')
    else:
        print(f'  [Claude]  ({time_str})')
        for line in text.split('\n')[:20]:
            print(f'    {line}')
        if len(text.split('\n')) > 20:
            print(f'    ... ({len(text.split(chr(10)))} lines total)')
    print()
print('--- End ---')
PYEOF
