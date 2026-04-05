# network-config-backup
It is a WayBack Machine for your network devices config (or basically anything which can be accessed by ssh or netconf)

## Web UI

A small Flask UI is included to read the existing `output/` folder, detect real snapshot-to-snapshot config changes, show them in a split diff view, and store operator notes in SQLite.

### Run

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

Open `http://127.0.0.1:8080`

Notes:

- The collector still writes raw files exactly as before under `output/<device>/`.
- The UI ignores collector metadata when diffing, so repeated NETCONF `message-id` changes do not show up as fake config changes.
- Notes are stored locally in `webui.db`.

## Contributing

Please use **Conventional Commits** with these types (https://www.conventionalcommits.org/en/v1.0.0/):

**FEAT**: new feature

**FIX**: bug fix

**CHORE**: misc (docs, deps, config)

### Format
\<type>: \<description>
