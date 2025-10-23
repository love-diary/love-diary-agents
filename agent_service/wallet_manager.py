"""
Wallet Manager - Character wallet generation and management
Handles Ethereum wallet creation, encryption, and transaction verification
"""

import secrets
from typing import Optional, Dict, Any
from eth_account import Account
from web3 import Web3
from cryptography.fernet import Fernet
import structlog

from .config import settings

logger = structlog.get_logger()


class WalletManager:
    """
    Manages character wallets with encrypted private key storage

    Security model:
    - Generate random private key during character bonding
    - Encrypt with AES-256 using server MASTER_KEY (Fernet)
    - Store encrypted key in database
    - Decrypt only when needed for signing transactions
    """

    def __init__(self):
        # Initialize Fernet cipher with master key
        if not settings.WALLET_ENCRYPTION_KEY:
            raise ValueError("WALLET_ENCRYPTION_KEY must be set in environment")

        self.cipher = Fernet(settings.WALLET_ENCRYPTION_KEY.encode())

        # Initialize Web3 for RPC calls
        self.w3 = Web3(Web3.HTTPProvider(settings.BASE_RPC_URL))

        # LOVE token contract address
        self.love_token_address = Web3.to_checksum_address(settings.LOVE_TOKEN_ADDRESS)

    def generate_wallet(self) -> tuple[str, bytes]:
        """
        Generate new Ethereum wallet with random private key

        Returns:
            tuple: (wallet_address, encrypted_private_key)
        """
        try:
            # Generate cryptographically secure random private key (32 bytes)
            private_key = secrets.token_bytes(32)

            # Derive Ethereum account from private key
            account = Account.from_key(private_key)
            wallet_address = account.address

            # Encrypt private key with master key
            encrypted_key = self.cipher.encrypt(private_key)

            logger.info(
                "wallet_generated",
                address=wallet_address,
                key_size=len(encrypted_key)
            )

            return wallet_address, encrypted_key

        except Exception as e:
            logger.error("wallet_generation_failed", error=str(e))
            raise

    def decrypt_private_key(self, encrypted_key: bytes) -> bytes:
        """
        Decrypt private key from database

        Args:
            encrypted_key: Encrypted private key bytes

        Returns:
            bytes: Decrypted private key (32 bytes)
        """
        try:
            private_key = self.cipher.decrypt(encrypted_key)
            return private_key

        except Exception as e:
            logger.error("key_decryption_failed", error=str(e))
            raise

    def get_account(self, encrypted_key: bytes) -> Account:
        """
        Get Ethereum account from encrypted private key

        Args:
            encrypted_key: Encrypted private key bytes

        Returns:
            Account: eth_account Account object
        """
        private_key = self.decrypt_private_key(encrypted_key)
        return Account.from_key(private_key)

    async def get_love_balance(self, wallet_address: str) -> int:
        """
        Get LOVE token balance for wallet address

        Args:
            wallet_address: Ethereum address

        Returns:
            int: LOVE token balance in wei (18 decimals)
        """
        try:
            # ERC20 balanceOf function signature
            balance_of_sig = Web3.keccak(text="balanceOf(address)")[:4]

            # Encode address parameter (left-pad to 32 bytes)
            address_param = Web3.to_checksum_address(wallet_address)
            address_bytes = bytes.fromhex(address_param[2:])  # Remove 0x
            data = balance_of_sig + address_bytes.rjust(32, b'\x00')

            # Call contract
            result = self.w3.eth.call({
                'to': self.love_token_address,
                'data': data
            })

            # Decode uint256 response
            balance = int.from_bytes(result, byteorder='big')

            logger.info(
                "love_balance_retrieved",
                address=wallet_address,
                balance=balance
            )

            return balance

        except Exception as e:
            logger.error(
                "balance_retrieval_failed",
                address=wallet_address,
                error=str(e)
            )
            return 0

    async def verify_gift_transaction(
        self,
        tx_hash: str,
        expected_recipient: str,
        expected_sender: str,
        min_amount: int
    ) -> Optional[Dict[str, Any]]:
        """
        Verify LOVE token gift transaction on-chain

        Args:
            tx_hash: Transaction hash
            expected_recipient: Character wallet address
            expected_sender: Player wallet address
            min_amount: Minimum expected transfer amount

        Returns:
            dict: {amount, sender, recipient, block_number} or None if invalid
        """
        try:
            # Retry logic for RPC delays (up to 3 attempts)
            import asyncio
            tx_receipt = None
            for attempt in range(3):
                try:
                    tx_receipt = self.w3.eth.get_transaction_receipt(tx_hash)
                    break
                except Exception as e:
                    if attempt < 2:
                        logger.info(
                            "tx_receipt_retry",
                            tx_hash=tx_hash,
                            attempt=attempt + 1,
                            error=str(e)
                        )
                        await asyncio.sleep(1)  # Wait 1 second between retries
                    else:
                        raise

            if not tx_receipt:
                logger.warning(
                    "gift_verification_failed_no_receipt",
                    tx_hash=tx_hash
                )
                return None

            if tx_receipt['status'] != 1:
                logger.warning(
                    "gift_verification_failed_tx_failed",
                    tx_hash=tx_hash,
                    status=tx_receipt['status']
                )
                return None

            # Get transaction details
            tx = self.w3.eth.get_transaction(tx_hash)

            # Verify transaction is to LOVE token contract
            if not tx.get('to'):
                logger.warning(
                    "gift_verification_failed_no_to_address",
                    tx_hash=tx_hash
                )
                return None

            if tx['to'].lower() != self.love_token_address.lower():
                logger.warning(
                    "gift_verification_failed_wrong_contract",
                    tx_hash=tx_hash,
                    to=tx['to'],
                    expected=self.love_token_address
                )
                return None

            # Parse ERC20 Transfer event from logs
            # Transfer(address indexed from, address indexed to, uint256 value)
            transfer_event_sig = Web3.keccak(text="Transfer(address,address,uint256)")

            transfer_log = None
            for log in tx_receipt['logs']:
                if log['topics'][0] == transfer_event_sig:
                    transfer_log = log
                    break

            if not transfer_log:
                logger.warning(
                    "gift_verification_failed_no_transfer_event",
                    tx_hash=tx_hash
                )
                return None

            # Decode Transfer event
            # topics[0] = event signature
            # topics[1] = from address (indexed)
            # topics[2] = to address (indexed)
            # data = amount (not indexed)
            from_address = Web3.to_checksum_address('0x' + transfer_log['topics'][1].hex()[-40:])
            to_address = Web3.to_checksum_address('0x' + transfer_log['topics'][2].hex()[-40:])
            amount = int.from_bytes(transfer_log['data'], byteorder='big')

            # Verify sender and recipient
            if from_address.lower() != expected_sender.lower():
                logger.warning(
                    "gift_verification_failed_wrong_sender",
                    tx_hash=tx_hash,
                    actual=from_address,
                    expected=expected_sender
                )
                return None

            if to_address.lower() != expected_recipient.lower():
                logger.warning(
                    "gift_verification_failed_wrong_recipient",
                    tx_hash=tx_hash,
                    actual=to_address,
                    expected=expected_recipient
                )
                return None

            # Verify minimum amount
            if amount < min_amount:
                logger.warning(
                    "gift_verification_failed_amount_too_small",
                    tx_hash=tx_hash,
                    amount=amount,
                    min_amount=min_amount
                )
                return None

            logger.info(
                "gift_verified",
                tx_hash=tx_hash,
                from_address=from_address,
                to_address=to_address,
                amount=amount,
                block_number=tx_receipt['blockNumber']
            )

            return {
                "amount": amount,
                "sender": from_address,
                "recipient": to_address,
                "block_number": tx_receipt['blockNumber'],
                "tx_hash": tx_hash
            }

        except Exception as e:
            logger.error(
                "gift_verification_error",
                tx_hash=tx_hash,
                error=str(e)
            )
            return None


# Singleton instance
wallet_manager: Optional[WalletManager] = None


def get_wallet_manager() -> WalletManager:
    """Get or create wallet manager singleton"""
    global wallet_manager
    if wallet_manager is None:
        wallet_manager = WalletManager()
    return wallet_manager
