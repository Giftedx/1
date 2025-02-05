import os
import logging
import hvac

logger = logging.getLogger(__name__)

def get_vault_client() -> hvac.Client | None:
    vault_addr = os.environ.get("VAULT_ADDR")
    vault_token = os.environ.get("VAULT_TOKEN")
    if not vault_addr or not vault_token:
        logger.error("Vault address or token not provided.")
        return None
    client = hvac.Client(url=vault_addr, token=vault_token)
    if not client.is_authenticated():
        logger.error("Vault client authentication failed.")
        return None
    return client

def get_secret(secret_path: str, secret_key: str) -> str | None:
    client = get_vault_client()
    if not client:
        return None
    try:
        secret = client.secrets.kv.read_secret_version(path=secret_path)
        return secret["data"]["data"].get(secret_key)
    except Exception as e:
        logger.error(f"Error retrieving secret '{secret_key}' from '{secret_path}': {e}")
        return None
