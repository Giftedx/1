import os
import hvac
import logging

logger = logging.getLogger(__name__)

def get_vault_client() -> hvac.Client | None:
    vault_addr = os.environ.get("VAULT_ADDR")
    vault_token = os.environ.get("VAULT_TOKEN")
    if not vault_addr or not vault_token:
        logger.warning("Vault credentials not set, falling back to environment variables")
        return None
    client = hvac.Client(url=vault_addr, token=vault_token)
    if not client.is_authenticated():
        raise Exception("Vault authentication failed")
    return client

def get_secret(secret_path: str, secret_key: str) -> str | None:
    client = get_vault_client()
    if client:
        secret_response = client.secrets.kv.v2.read_secret_version(path=secret_path)
        return secret_response["data"]["data"].get(secret_key)
    # Fallback to environment variable if Vault is not configured.
    return os.environ.get(secret_key.upper())
