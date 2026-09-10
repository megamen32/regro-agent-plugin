---
name: regru-dns
description: Operate REG.RU DNS from an agent — refresh backup-WAN A records via the self-contained WANB DDNS updater and wire certbot DNS-01 renewals onto REG.API TXT records. Use when a task needs to change, verify, or automate DNS in a zone still hosted at REG.RU.
---

# REG.RU DNS operations

## Prerequisites

1. Env file with `REGRU_USERNAME` / `REGRU_PASSWORD` (and optionally
   `REGRU_ZONE_DOMAIN`, `REGRU_RECORD_NAMES`). Root-owned, mode 0600.
2. REG.API may be IP-restricted per account — allow the calling host in the
   reg.ru panel before the first call.
3. Confirm the zone is actually served by REG.RU: the API answers
   `DOMAIN_NOT_FOUND` once a zone is delegated away (that is what retired this
   provider for `bezrabotnyi.com`).

## WANB DDNS updater

```bash
python3 scripts/regru_wanb_ddns.py --env-file /etc/default/regru-wanb-ddns --dry-run
python3 scripts/regru_wanb_ddns.py --env-file /etc/default/regru-wanb-ddns
```

- Detects the primary public IP, then the secondary (backup) uplink through a
  temporary policy-routing helper (`SECONDARY_*` env); the secondary IP wins
  when it differs.
- Updates every name in `REGRU_RECORD_NAMES` to the chosen target IP.

## certbot DNS-01

```bash
manual_auth_hook = /path/to/regru_dns01.py auth
manual_cleanup_hook = /path/to/regru_dns01.py cleanup
```

The helper reads `CERTBOT_DOMAIN` / `CERTBOT_VALIDATION` from certbot and
`REGRU_USERNAME` / `REGRU_PASSWORD` / `REGRU_ZONE_DOMAIN` from the environment.
Always prove a migrated renewal with
`certbot renew --dry-run --cert-name <name>` before declaring it done.

## Safety rules

- Point of no return: once a zone's delegation leaves REG.RU, no REG.API call
  can manage it. Migrate the consumers (DDNS, DNS-01 hooks) to the new
  provider in the same cycle — dead credentials and hooks must not linger.
- Verify every mutation against the authoritative NS with `dig` before
  declaring success.
