# bearbank-services — tenant `default`

Demo services monitored by AutoSRE. **Code** fixes land here; **config** fixes
land in `opsrabbit/bear-gitops`.

| Path | |
|---|---|
| `services/<name>/handlers.py` | That service's own logic. One copy of each defect, so a fix touches one service. |
| `shared/` | Runtime shared by every service — topology, HTTP fan-out, pool behaviour. |

Services: 

Generated from `demo/bearbank/` in the AutoSRE repo by
`scripts/demo-seed-repos.sh`. Edit there and re-run, or edit here and port back.
