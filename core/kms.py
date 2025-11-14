"""Google Cloud KMS encryption/decryption utilities for Reddit credentials."""

import base64
import logging
import os
from google.cloud.kms_v1 import KeyManagementServiceClient
from google.api_core import exceptions as gcp_exceptions
from google.oauth2 import service_account

from core.config import settings

logger = logging.getLogger(__name__)


def get_kms_client():
    """
    Get KMS client instance with proper authentication.
    
    Uses service account credentials if GOOGLE_APPLICATION_CREDENTIALS is set,
    otherwise falls back to Application Default Credentials (ADC).
    """
    # Check if explicit credentials path is provided
    creds_path = settings.GOOGLE_APPLICATION_CREDENTIALS or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    
    if creds_path:
        # Expand ~ to home directory and resolve relative paths
        creds_path = os.path.expanduser(creds_path)
        creds_path = os.path.abspath(creds_path)
        
        if os.path.exists(creds_path):
            logger.info(f"✅ Using service account credentials from: {creds_path}")
            credentials = service_account.Credentials.from_service_account_file(creds_path)
            return KeyManagementServiceClient(credentials=credentials)
        else:
            logger.warning(f"⚠️  Service account key file not found: {creds_path}")
            logger.warning("⚠️  Falling back to Application Default Credentials (ADC)")
            logger.warning("⚠️  Run './scripts/setup-local-gcp-auth.sh' to create a service account key")
    else:
        logger.debug("No GOOGLE_APPLICATION_CREDENTIALS set, using Application Default Credentials (ADC)")
    
    # Use Application Default Credentials (ADC)
    # This works automatically on Cloud Run, or with gcloud auth application-default login
    return KeyManagementServiceClient()


def get_key_name():
    """Get the full KMS key resource name."""
    return (
        f"projects/{settings.GOOGLE_PROJECT_ID}/"
        f"locations/{settings.GOOGLE_LOCATION}/"
        f"keyRings/{settings.KMS_KEYRING}/"
        f"cryptoKeys/{settings.KMS_KEY}"
    )


def encrypt(plaintext: str) -> str:
    """
    Encrypt plaintext using Google Cloud KMS.
    
    Args:
        plaintext: The text to encrypt (e.g., Reddit client secret, refresh token)
        
    Returns:
        Base64-encoded ciphertext
        
    Raises:
        Exception: If encryption fails
    """
    if not plaintext:
        raise ValueError("Cannot encrypt empty plaintext")
    
    try:
        client = get_kms_client()
        key_name = get_key_name()
        
        # Convert plaintext to bytes
        plaintext_bytes = plaintext.encode('utf-8')
        
        # Encrypt
        response = client.encrypt(
            request={
                "name": key_name,
                "plaintext": plaintext_bytes
            }
        )
        
        # Encode ciphertext as base64 for storage
        ciphertext_b64 = base64.b64encode(response.ciphertext).decode('utf-8')
        
        logger.info(f"Successfully encrypted data using KMS key: {key_name}")
        
        return ciphertext_b64
        
    except gcp_exceptions.GoogleAPIError as e:
        logger.error(f"KMS encryption failed: {str(e)}")
        raise Exception(f"Failed to encrypt data: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error during encryption: {str(e)}")
        raise Exception(f"Encryption error: {str(e)}")


def decrypt(ciphertext_b64: str) -> str:
    """
    Decrypt ciphertext using Google Cloud KMS.
    
    Args:
        ciphertext_b64: Base64-encoded ciphertext from encrypt()
        
    Returns:
        Decrypted plaintext string
        
    Raises:
        Exception: If decryption fails
    """
    if not ciphertext_b64:
        raise ValueError("Cannot decrypt empty ciphertext")
    
    try:
        client = get_kms_client()
        key_name = get_key_name()
        
        # Decode base64 ciphertext
        ciphertext = base64.b64decode(ciphertext_b64)
        
        # Decrypt
        response = client.decrypt(
            request={
                "name": key_name,
                "ciphertext": ciphertext
            }
        )
        
        # Convert bytes back to string
        plaintext = response.plaintext.decode('utf-8')
        
        # NEVER log the decrypted plaintext!
        logger.info(f"Successfully decrypted data using KMS key: {key_name}")
        
        return plaintext
        
    except gcp_exceptions.GoogleAPIError as e:
        logger.error(f"KMS decryption failed: {str(e)}")
        raise Exception(f"Failed to decrypt data: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error during decryption: {str(e)}")
        raise Exception(f"Decryption error: {str(e)}")


def encrypt_reddit_credentials(client_id: str, client_secret: str, refresh_token: str) -> dict:
    """
    Encrypt Reddit app credentials for storage.
    
    Args:
        client_id: Reddit app client ID (stored as plaintext)
        client_secret: Reddit app client secret (encrypted)
        refresh_token: Reddit OAuth refresh token (encrypted)
        
    Returns:
        Dictionary with encrypted credentials
    """
    return {
        "client_id": client_id,  # Client ID is not sensitive, no encryption needed
        "client_secret_encrypted": encrypt(client_secret),
        "refresh_token_encrypted": encrypt(refresh_token),
    }


def decrypt_reddit_credentials(encrypted_data: dict) -> dict:
    """
    Decrypt Reddit app credentials from storage.
    
    Args:
        encrypted_data: Dictionary with encrypted credentials
        
    Returns:
        Dictionary with decrypted credentials
        
    SECURITY: Never log the returned credentials!
    """
    return {
        "client_id": encrypted_data["client_id"],
        "client_secret": decrypt(encrypted_data["client_secret_encrypted"]),
        "refresh_token": decrypt(encrypted_data["refresh_token_encrypted"]),
    }

