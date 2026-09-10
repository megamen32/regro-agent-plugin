# regro — REG.RU Agent Plugin

Operate [REG.RU](https://reg.ru) DNS from a coding agent. The scripts here are
the proven extraction of the `bezrabotnyi.com` WANB updater and certbot DNS-01
hooks that ran in production for months — preserved as a portable toolkit when
that zone moved to SpaceWeb (see the companion `swap-agent-plugin`).

## What is inside

| Piece | Purpose |
| --- | --- |
| `scripts/regru_wanb_ddns.py` | DDNS updater: refreshes backup-WAN A records via REG.API v2; dual-uplink aware (primary + policy-routed secondary, secondary IP wins when it differs). |
| `scripts/regru_dns01.py` | certbot DNS-01 auth/cleanup: `auth` adds `_acme-challenge` TXT, `cleanup` removes it. |
| `templates/` | systemd service/timer + env example for the updater. |

## Credentials

Nothing is embedded. Provide an env file (default `/etc/default/regru-wanb-ddns`
for the updater; `REGRU_USERNAME` / `REGRU_PASSWORD` for the DNS-01 helper):

```
REGRU_USERNAME=you@example.com
REGRU_PASSWORD='secret'
REGRU_ZONE_DOMAIN=bezrabotnyi.com
REGRU_RECORD_NAMES=router-b,home-b   # comma-separated
```

REG.API access may additionally be IP-restricted in the reg.ru panel — allow
the calling host's address.

## Status note (2026-09-10)

The `bezrabotnyi.com` zone was delegated away from REG.RU; the REG.API now
answers `DOMAIN_NOT_FOUND` for it. The updater here is the battle-tested
reference implementation (it served that zone from 2026-05 to 2026-09), kept
for zones still hosted at REG.RU. Verify `get_resource_records` answers for
your zone before relying on either script.

## License

MIT.
