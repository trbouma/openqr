"""OpenETR identity adapter; no local config files or web-app imports."""

from contextlib import contextmanager

from stroma import Keys
from openetr.config import (
    _async_load_profiles_index,
    _async_load_profile_secret,
    _async_load_profile_record,
    set_runtime_bootstrap_overrides,
    reset_runtime_bootstrap_overrides,
)
from openetr.services.query_etr import fetch_profile


@contextmanager
def root_context(root_nsec: str, home_relays: list[str]):
    # Isolate the component's current async configuration APIs in this adapter.
    token = set_runtime_bootstrap_overrides(root_nsec=root_nsec, home_relays=",".join(home_relays))
    try:
        yield {"root_nsec": root_nsec, "home_relay": ",".join(home_relays)}
    finally:
        reset_runtime_bootstrap_overrides(token)


def normalize_root(nsec: str) -> str:
    if not nsec.strip().startswith("nsec1"):
        raise ValueError("Enter a valid Control Desk nsec.")
    try:
        return Keys(priv_k=nsec.strip()).private_key_bech32()
    except Exception as exc:
        raise ValueError("Enter a valid Control Desk nsec.") from exc


async def list_profiles(root_nsec: str, home_relays: list[str]) -> list[str]:
    with root_context(root_nsec, home_relays) as config:
        index = await _async_load_profiles_index(config)
    if index is None:
        raise ValueError("No Control Desk configuration was found on the configured home relays.")
    return sorted(set(index.profiles))


async def acting_profile(root_nsec: str, name: str, home_relays: list[str]) -> dict:
    if name not in await list_profiles(root_nsec, home_relays):
        raise ValueError("This profile is not managed by the signed-in Control Desk Key.")
    with root_context(root_nsec, home_relays) as config:
        secret = await _async_load_profile_secret(name, config)
        record = await _async_load_profile_record(name, config)
    if not secret:
        raise ValueError("No signing key was found for this profile.")
    keys = Keys(priv_k=secret)
    relays = record.relays if record and record.relays else ",".join(home_relays)
    return {"name": name, "nsec": keys.private_key_bech32(),
            "npub": keys.public_key_bech32(), "relays": relays}


async def profile_details(profile: dict) -> dict:
    return await fetch_profile(
        relays=profile["relays"], pubkey_hex=Keys(priv_k=profile["nsec"]).public_key_hex(),
        timeout=10, ssl_disable_verify=False,
    ) or {}
