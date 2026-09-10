#!/usr/bin/env python3
"""certbot DNS-01 auth/cleanup hook for REG.RU zones (REG.API v2).

auth    add _acme-challenge.<CERTBOT_DOMAIN> TXT with CERTBOT_VALIDATION
cleanup remove that TXT

Credentials come from the environment (REGRU_USERNAME / REGRU_PASSWORD), the
zone defaults to bezrabotnyi.com and can be overridden with REGRU_ZONE_DOMAIN.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request

API_URL = "https://api.reg.ru/api/regru2"


class RegRuError(RuntimeError):
    pass


def api_post(path: str, payload: dict) -> dict:
    encoded = urllib.parse.urlencode(
        {"input_format": "json", "input_data": json.dumps(payload)}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{API_URL}/{path}",
        data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def ensure_success(response: dict, action: str) -> None:
    if response.get("result") != "success":
        raise RegRuError(f"{action} failed: {json.dumps(response, ensure_ascii=False)[:300]}")


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    domain = os.environ.get("CERTBOT_DOMAIN", "")
    validation = os.environ.get("CERTBOT_VALIDATION", "")
    username = os.environ.get("REGRU_USERNAME", "").strip()
    password = os.environ.get("REGRU_PASSWORD", "").strip()
    zone = os.environ.get("REGRU_ZONE_DOMAIN", "bezrabotnyi.com").strip()

    if mode not in {"auth", "cleanup"}:
        print("usage: regru_dns01.py auth|cleanup", file=sys.stderr)
        return 2
    if not domain or not username or not password:
        print("missing CERTBOT_DOMAIN or REGRU credentials", file=sys.stderr)
        return 1

    base = {"username": username, "password": password,
            "domains": [{"dname": zone}], "output_content_type": "plain"}
    subdomain = "_acme-challenge"
    if domain != zone and domain.endswith(f".{zone}"):
        subdomain = f"_acme-challenge.{domain[: -len(zone) - 1]}"

    if mode == "auth":
        ensure_success(api_post("zone/add_txt", {**base, "subdomain": subdomain, "text": validation}),
                       "add_txt")
        time.sleep(5)
    else:
        response = api_post("zone/remove_record",
                            {**base, "subdomain": subdomain, "record_type": "TXT",
                             "content": validation})
        # RR_NOT_FOUND is a fine cleanup outcome.
        if response.get("result") != "success":
            error_codes = {item.get("error_code") for item in response.get("answer", {}).get("domains", [])}
            if error_codes - {"RR_NOT_FOUND"}:
                raise RegRuError(f"remove_record failed: {json.dumps(response, ensure_ascii=False)[:300]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
