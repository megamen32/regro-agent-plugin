#!/usr/bin/env python3

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import shlex
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


API_URL = "https://api.reg.ru/api/regru2"
PUBLIC_IP_PROVIDERS = (
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
)
DEFAULT_RECORDS = (
    "router-b",
    "home-b",
    "remote100-b",
    "remote88-b",
    "remote44-b",
    "88-b",
    "cockpit-b",
    "44-b",
)


@dataclass(frozen=True)
class RouteOverride:
    interface: str
    source_ip: str
    gateway: str
    table_id: int
    priority: int

    @property
    def source_network(self) -> str:
        return str(ipaddress.ip_network(f"{self.source_ip}/24", strict=False))


@dataclass(frozen=True)
class Config:
    username: str
    password: str
    zone_domain: str
    record_names: tuple[str, ...]
    primary_source_ip: str
    secondary_route: RouteOverride
    dry_run: bool


class RegRuError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update backup bezrabotnyi.com A records for the current WANB public IP."
    )
    parser.add_argument("--env-file", default="/etc/default/regru-wanb-ddns")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_env_file(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    if not os.path.exists(path):
        return values

    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            parsed = shlex.split(value.strip())
            values[key.strip()] = parsed[0] if parsed else ""
    return values


def merge_env(env_file: str) -> dict[str, str]:
    merged = dict(os.environ)
    merged.update(load_env_file(env_file))
    return merged


def parse_record_names(raw_value: str | None) -> tuple[str, ...]:
    if not raw_value:
        return DEFAULT_RECORDS
    return tuple(item.strip() for item in raw_value.split(",") if item.strip())


def load_config(env: dict[str, str], dry_run: bool) -> Config | None:
    username = env.get("REGRU_USERNAME", "").strip()
    password = env.get("REGRU_PASSWORD", "").strip()
    if username in {"", "replace-me"} or password in {"", "replace-me"}:
        return None

    return Config(
        username=username,
        password=password,
        zone_domain=env.get("REGRU_ZONE_DOMAIN", "bezrabotnyi.com").strip(),
        record_names=parse_record_names(env.get("REGRU_RECORD_NAMES")),
        primary_source_ip=env.get("PRIMARY_SOURCE_IP", "192.168.2.100").strip(),
        secondary_route=RouteOverride(
            interface=env.get("SECONDARY_INTERFACE", "enp28s0f2np2").strip(),
            source_ip=env.get("SECONDARY_SOURCE_IP", "192.168.1.100").strip(),
            gateway=env.get("SECONDARY_GATEWAY", "192.168.1.1").strip(),
            table_id=int(env.get("SECONDARY_TABLE_ID", "101")),
            priority=int(env.get("SECONDARY_RULE_PRIORITY", "100")),
        ),
        dry_run=dry_run,
    )


def fetch_public_ip(source_ip: str | None = None) -> str:
    for provider in PUBLIC_IP_PROVIDERS:
        command = ["curl", "-fsS", "-m", "8"]
        if source_ip:
            command.extend(["--interface", source_ip])
        command.append(provider)
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode == 0:
            value = result.stdout.strip()
            if value:
                ipaddress.ip_address(value)
                return value
    raise RuntimeError(f"Unable to detect public IP for source {source_ip or 'default'}")


def write_temp_script(route: RouteOverride) -> str:
    fd, path = tempfile.mkstemp(prefix="regru-wanb-", suffix=".sh")
    os.close(fd)
    script = f"""#!/usr/bin/env bash
set -euo pipefail
cleanup() {{
  ip rule del pref {route.priority} from {route.source_ip}/32 table {route.table_id} 2>/dev/null || true
  ip route flush table {route.table_id} 2>/dev/null || true
}}
trap cleanup EXIT
ip route replace table {route.table_id} {route.source_network} dev {route.interface} src {route.source_ip}
ip route replace table {route.table_id} default via {route.gateway} dev {route.interface} src {route.source_ip}
ip rule add pref {route.priority} from {route.source_ip}/32 table {route.table_id}
exec "$@"
"""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(script)
    os.chmod(path, 0o700)
    return path


def fetch_secondary_public_ip(route: RouteOverride) -> str:
    helper_path = write_temp_script(route)
    try:
        for provider in PUBLIC_IP_PROVIDERS:
            command = [
                "sudo",
                helper_path,
                "curl",
                "-fsS",
                "-m",
                "8",
                "--interface",
                route.source_ip,
                provider,
            ]
            result = subprocess.run(command, text=True, capture_output=True)
            if result.returncode == 0:
                value = result.stdout.strip()
                if value:
                    ipaddress.ip_address(value)
                    return value
        raise RuntimeError(f"Unable to detect WANB public IP through {route.gateway}")
    finally:
        try:
            os.remove(helper_path)
        except FileNotFoundError:
            pass


def choose_backup_ip(primary_ip: str, secondary_ip: str | None) -> str:
    if secondary_ip and secondary_ip != primary_ip:
        return secondary_ip
    return primary_ip


def api_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    encoded = urllib.parse.urlencode(
        {
            "input_format": "json",
            "input_data": json.dumps(payload),
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{API_URL}/{path}",
        data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def ensure_success(
    response: dict[str, Any],
    action: str,
    *,
    allowed_error_codes: set[str] | None = None,
) -> None:
    allowed_error_codes = allowed_error_codes or set()
    if response.get("result") == "success":
        domains = response.get("answer", {}).get("domains", [])
        if all(
            item.get("result") == "success"
            or item.get("error_code") in allowed_error_codes
            for item in domains
        ):
            return
    raise RegRuError(f"{action} failed: {json.dumps(response, ensure_ascii=False, sort_keys=True)}")


def zone_payload(config: Config, extra: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "username": config.username,
        "password": config.password,
        "domains": [{"dname": config.zone_domain}],
        "output_content_type": "plain",
    }
    payload.update(extra)
    return payload


def remove_a_record(config: Config, subdomain: str) -> None:
    response = api_post(
        "zone/remove_record",
        zone_payload(
            config,
            {
                "subdomain": subdomain,
                "record_type": "A",
            },
        ),
    )
    ensure_success(response, f"remove_record:{subdomain}", allowed_error_codes={"RR_NOT_FOUND"})


def add_a_record(config: Config, subdomain: str, ipaddr: str) -> None:
    response = api_post(
        "zone/add_alias",
        zone_payload(
            config,
            {
                "subdomain": subdomain,
                "ipaddr": ipaddr,
            },
        ),
    )
    ensure_success(response, f"add_alias:{subdomain}")


def update_records(config: Config, target_ip: str) -> None:
    for subdomain in config.record_names:
        remove_a_record(config, subdomain)
        add_a_record(config, subdomain, target_ip)


def main() -> int:
    args = parse_args()
    config = load_config(merge_env(args.env_file), args.dry_run)
    if config is None:
        print(f"SKIP: missing reg.ru credentials in {args.env_file}", file=sys.stderr)
        return 0

    primary_ip = fetch_public_ip(config.primary_source_ip)
    secondary_ip: str | None = None
    secondary_error: str | None = None

    try:
        secondary_ip = fetch_secondary_public_ip(config.secondary_route)
    except RuntimeError as exc:
        secondary_error = str(exc)

    target_ip = choose_backup_ip(primary_ip, secondary_ip)
    print(
        json.dumps(
            {
                "dry_run": config.dry_run,
                "primary_ip": primary_ip,
                "records": config.record_names,
                "secondary_error": secondary_error,
                "secondary_ip": secondary_ip,
                "target_ip": target_ip,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )

    if config.dry_run:
        return 0

    update_records(config, target_ip)
    return 0


if __name__ == "__main__":
    sys.exit(main())
