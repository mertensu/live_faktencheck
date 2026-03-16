#!/usr/bin/env bash
set -euo pipefail

if [ $# -eq 0 ]; then
  echo "Usage: ./publish_episode.sh <episode-key>"
  echo ""
  echo "Publishes a new episode: sets publish=True, updates shows.json, builds, commits and pushes."
  echo ""
  echo "Available episodes:"
  grep -oP '^\s+"([^"]+)":\s+Episode\(' config.py | sed 's/.*"\(.*\)".*/  \1/'
  exit 1
fi

EPISODE_KEY="$1"

# Verify the episode exists in config.py
if ! grep -q "\"${EPISODE_KEY}\"" config.py; then
  echo "Error: Episode '${EPISODE_KEY}' not found in config.py"
  exit 1
fi

# Check if already published
if grep -A 20 "\"${EPISODE_KEY}\"" config.py | grep -q "publish=True"; then
  echo "Error: ${EPISODE_KEY} is already published"
  exit 1
fi

# Add publish=True to the episode
python3 -c "
import re

with open('config.py') as f:
    content = f.read()

pattern = r'(\"${EPISODE_KEY}\":\s*Episode\(.*?)(\s*\),)'
match = re.search(pattern, content, re.DOTALL)
if not match:
    print('Error: Could not find episode block')
    exit(1)

before = match.group(1)
closing = match.group(2)
if before.rstrip().endswith(','):
    new = before + '\n        publish=True,'
else:
    new = before + ',\n        publish=True,'
content = content[:match.start()] + new + closing + content[match.end():]

with open('config.py', 'w') as f:
    f.write(content)
print('✓ Set publish=True for ${EPISODE_KEY}')
"

# Update shows.json + create minimal episode JSON (correct title, empty fact-checks)
echo ""
uv run python export_episode.py --update-shows

uv run python -c "
import json
from pathlib import Path
from config import EPISODES, get_show_name

ep = EPISODES['${EPISODE_KEY}']
data = {
    'show_name': get_show_name(ep.show),
    'date': ep.date,
    'speakers': ep.speakers,
    'fact_checks': [],
}
out = Path('frontend/public/data/${EPISODE_KEY}.json')
out.write_text(json.dumps(data, ensure_ascii=False, indent=2))
print(f'✓ Created empty episode JSON → {out}')
"

# Commit and push
echo ""
git add config.py frontend/public/data/
git commit -m "publish ${EPISODE_KEY}"
git push

echo ""
echo "✓ Done! ${EPISODE_KEY} is now live."
