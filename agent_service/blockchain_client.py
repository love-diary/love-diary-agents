"""
Blockchain Client
Fetches character data from CharacterNFT contract
"""

from web3 import Web3, AsyncWeb3
from typing import Dict
import structlog
import json

from .config import settings

logger = structlog.get_logger()

# CharacterNFT ABI (minimal, only getCharacter function)
CHARACTER_NFT_ABI = json.loads(
    """
[
  {
    "inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}],
    "name": "getCharacter",
    "outputs": [
      {
        "components": [
          {"internalType": "string", "name": "name", "type": "string"},
          {"internalType": "uint32", "name": "birthTimestamp", "type": "uint32"},
          {"internalType": "enum CharacterNFT.Gender", "name": "gender", "type": "uint8"},
          {"internalType": "enum CharacterNFT.SexualOrientation", "name": "sexualOrientation", "type": "uint8"},
          {"internalType": "uint8", "name": "occupationId", "type": "uint8"},
          {"internalType": "uint8", "name": "personalityId", "type": "uint8"},
          {"internalType": "enum CharacterNFT.Language", "name": "language", "type": "uint8"},
          {"internalType": "uint256", "name": "mintedAt", "type": "uint256"},
          {"internalType": "bool", "name": "isBonded", "type": "bool"},
          {"internalType": "bytes32", "name": "secret", "type": "bytes32"}
        ],
        "internalType": "struct CharacterNFT.Character",
        "name": "",
        "type": "tuple"
      }
    ],
    "stateMutability": "view",
    "type": "function"
  }
]
"""
)


class BlockchainClient:
    """
    Client for interacting with blockchain (Base Sepolia)
    Fetches character NFT data
    """

    def __init__(self):
        self.rpc_url = settings.BASE_RPC_URL
        self.nft_address = settings.CHARACTER_NFT_ADDRESS
        self.w3: Web3 = None
        self.contract = None

    async def initialize(self):
        """Initialize Web3 connection"""
        try:
            self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))

            # Check connection
            if not self.w3.is_connected():
                raise Exception("Failed to connect to blockchain")

            # Initialize contract
            self.contract = self.w3.eth.contract(
                address=Web3.to_checksum_address(self.nft_address),
                abi=CHARACTER_NFT_ABI,
            )

            logger.info("blockchain_client_initialized", rpc=self.rpc_url)

        except Exception as e:
            logger.error("blockchain_init_failed", error=str(e))
            raise

    async def get_character_data(self, token_id: int) -> Dict:
        """
        Fetch character data from NFT contract

        Returns:
            Dict with character attributes
        """
        try:
            # Call getCharacter
            result = self.contract.functions.getCharacter(token_id).call()

            # Parse result tuple (birthTimestamp is uint32, convert to birthYear for agent)
            birth_timestamp = result[1]
            birth_year = 1970 + (birth_timestamp // 31536000)  # Convert Unix timestamp to year

            character_data = {
                "name": result[0],
                "birthYear": birth_year,  # Keep birthYear for agent compatibility
                "birthTimestamp": birth_timestamp,
                "gender": result[2],
                "sexualOrientation": result[3],
                "occupationId": result[4],
                "personalityId": result[5],
                "language": result[6],
                "mintedAt": result[7],
                "isBonded": result[8],
                "secret": result[9].hex() if isinstance(result[9], bytes) else result[9],
            }

            logger.info(
                "character_data_fetched",
                token_id=token_id,
                name=character_data["name"],
            )

            return character_data

        except Exception as e:
            logger.error(
                "character_fetch_failed", token_id=token_id, error=str(e)
            )
            raise Exception(f"Failed to fetch character data: {str(e)}")

    async def verify_ownership(
        self, token_id: int, wallet_address: str
    ) -> bool:
        """Verify NFT ownership (optional, backend already checks)"""
        try:
            owner = self.contract.functions.ownerOf(token_id).call()
            return owner.lower() == wallet_address.lower()
        except Exception:
            return False
