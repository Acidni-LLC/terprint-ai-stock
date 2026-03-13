"""
Stock Updater - Menu Download to Cosmos DB Stock Processor
Processes downloaded menu files and updates the stock inventory in Cosmos DB
"""

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from azure.cosmos.aio import CosmosClient
from azure.identity.aio import DefaultAzureCredential
import os
from azure.storage.blob.aio import BlobServiceClient
from azure.identity import DefaultAzureCredential as SyncDefaultAzureCredential
from azure.keyvault.secrets import SecretClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Runtime Key Vault secret loading (ADR-008)
# ---------------------------------------------------------------------------
_kv_client: Optional[SecretClient] = None
_kv_cache: dict = {}
_kv_expiry: dict = {}
_KV_TTL_MINUTES = 5


def _get_kv_secret(name: str) -> str:
    """Fetch a secret from Azure Key Vault with 5-minute TTL cache."""
    global _kv_client
    now = datetime.utcnow()
    if name in _kv_cache and now < _kv_expiry[name]:
        return _kv_cache[name]
    if _kv_client is None:
        vault_name = os.environ.get("KEYVAULT_NAME", "kv-terprint-dev")
        _kv_client = SecretClient(
            vault_url=f"https://{vault_name}.vault.azure.net/",
            credential=SyncDefaultAzureCredential(),
        )
    value = _kv_client.get_secret(name).value
    _kv_cache[name] = value
    _kv_expiry[name] = now + timedelta(minutes=_KV_TTL_MINUTES)
    return value


# Configuration
DATABASE_NAME = "TerprintAI"
CONTAINER_NAME = "stock"

STORAGE_ACCOUNT = "stterprintsharedgen2"
STORAGE_CONTAINER = "jsonfiles"
STORAGE_URL = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net"

# Dispensary mapping
DISPENSARY_MAP = {
    1: "Cookies",
    2: "MUV",
    3: "Flowery",
    4: "Trulieve",
    10: "Curaleaf"
}


class StockUpdater:
    """Updates stock inventory from menu downloads"""
    
    def __init__(self):
        self.credential = None
        self.cosmos_client = None
        self.blob_client = None
        self.container = None
    
    async def initialize(self):
        """Initialize Azure clients"""
        logger.info("Initializing Stock Updater...")
        
        self.credential = DefaultAzureCredential()

        # Load Cosmos endpoint from Key Vault at runtime (ADR-008)
        cosmos_endpoint = _get_kv_secret("terprint--cosmos-endpoint")
        
        # Cosmos DB
        self.cosmos_client = CosmosClient(cosmos_endpoint, self.credential)
        database = self.cosmos_client.get_database_client(DATABASE_NAME)
        self.container = database.get_container_client(CONTAINER_NAME)
        logger.info("OK Cosmos DB connected")
        
        # Blob Storage
        self.blob_client = BlobServiceClient(STORAGE_URL, credential=self.credential)
        logger.info("OK Blob Storage connected")
    
    async def close(self):
        """Close Azure clients"""
        if self.cosmos_client:
            await self.cosmos_client.close()
        if self.blob_client:
            await self.blob_client.close()
        if self.credential:
            await self.credential.close()
    
    def generate_stock_id(self, dispensary_id: int, store_id: str, strain_name: str, 
                         product_type: str, size: str) -> str:
        """Generate unique ID for stock item"""
        key = f"{dispensary_id}:{store_id}:{strain_name}:{product_type}:{size}"
        return hashlib.md5(key.encode()).hexdigest()
    
    def generate_urls(self, dispensary_id: int, strain_name: str, 
                     batch_id: Optional[str]) -> Dict[str, str]:
        """Generate Terprint.Web URLs for links"""
        base_url = "https://terprint.acidni.net"
        
        # URL-safe strain name
        strain_slug = strain_name.lower().replace(" ", "-").replace("'", "")
        
        urls = {
            "product_url": f"{base_url}/strains/{strain_slug}",
            "strain_url": f"{base_url}/strains/{strain_slug}",
            "dispensary_url": f"{base_url}/dispensaries/{dispensary_id}"
        }
        
        if batch_id:
            urls["batch_url"] = f"{base_url}/batches/{batch_id}"
        else:
            urls["batch_url"] = None
        
        return urls
    
    def _extract_product_type(self, menu_item: Dict[str, Any]) -> str:
        """Extract product type/category from dispensary-specific JSON structures.

        Each dispensary uses a different field name and format:
        - Cookies: ``category`` (str)
        - Green Dragon: ``category_name`` (str)
        - MUV: ``category`` as dict ``{"name": "Flower"}``
        - Trulieve: ``categories`` as list of dicts ``[{"name": "Flower"}]``
        - Flowery: ``categories`` as list of strings ``["Flower"]``
        """
        # 1. Simple string: Cookies ("category"), Green Dragon ("category_name")
        raw = menu_item.get("category")
        if isinstance(raw, str) and raw:
            return raw
        raw = menu_item.get("category_name")
        if isinstance(raw, str) and raw:
            return raw
        raw = menu_item.get("type")
        if isinstance(raw, str) and raw:
            return raw

        # 2. Dict: MUV uses category as {"name": "Flower"}
        raw = menu_item.get("category")
        if isinstance(raw, dict):
            name = raw.get("name")
            if name:
                return name

        # 3. Array: Trulieve [{"name":"Flower"}], Flowery ["Flower"]
        categories = menu_item.get("categories")
        if isinstance(categories, list):
            for cat in categories:
                if isinstance(cat, str) and cat:
                    return cat
                if isinstance(cat, dict):
                    name = cat.get("name", "")
                    if name and name.lower() not in ("brands",):
                        return name

        return "unknown"

    def extract_product_info(self, menu_item: Dict[str, Any], dispensary_id: int,
                             store_id: str, store_name: str) -> Optional[Dict[str, Any]]:
        """Extract standardized product info from menu item"""
        try:
            # Extract core fields (dispensary-specific parsing)
            strain_name = menu_item.get("name") or menu_item.get("productName") or menu_item.get("title")
            product_type = self._extract_product_type(menu_item)
            price = float(menu_item.get("price", 0) or menu_item.get("Price", 0))
            
            # Size extraction
            size = menu_item.get("size") or menu_item.get("Size") or menu_item.get("weight")
            
            # Batch ID (if available)
            batch_id = menu_item.get("batchId") or menu_item.get("batch_number")
            
            if not strain_name or price <= 0:
                return None
            
            # Generate IDs and URLs
            stock_id = self.generate_stock_id(dispensary_id, store_id, strain_name, 
                                              product_type, size or "")
            urls = self.generate_urls(dispensary_id, strain_name, batch_id)
            
            return {
                "id": stock_id,
                "strain_name": strain_name,
                "product_type": product_type,
                "store_id": store_id,
                "store_name": store_name,
                "dispensary_id": dispensary_id,
                "dispensary_name": DISPENSARY_MAP.get(dispensary_id, "Unknown"),
                "batch_id": batch_id,
                "price": price,
                "size": size,
                "last_seen": datetime.utcnow().isoformat(),
                **urls
            }
        
        except Exception as e:
            logger.error(f"Error extracting product info: {e}")
            return None
    
    async def process_menu_file(self, blob_path: str) -> List[Dict[str, Any]]:
        """Process a single menu file and extract stock items"""
        try:
            # Download blob
            blob_container = self.blob_client.get_container_client(STORAGE_CONTAINER)
            blob = blob_container.get_blob_client(blob_path)
            
            stream = await blob.download_blob()
            content = await stream.readall()
            menu_data = json.loads(content)
            
            # Parse blob path to get dispensary/store info
            # Format: dispensaries/{dispensary}/{year}/{month}/{day}/{timestamp}.json
            path_parts = blob_path.split("/")
            dispensary_name = path_parts[1]
            
            # Map dispensary name to ID
            dispensary_id = None
            for did, dname in DISPENSARY_MAP.items():
                if dname.lower() == dispensary_name.lower():
                    dispensary_id = did
                    break
            
            if not dispensary_id:
                logger.warning(f"Unknown dispensary: {dispensary_name}")
                return []
            
            # Extract products (dispensary-specific structure)
            products = []
            
            if isinstance(menu_data, dict):
                # Handle different menu structures
                if "products" in menu_data:
                    items = menu_data["products"]
                elif "items" in menu_data:
                    items = menu_data["items"]
                elif "menu" in menu_data:
                    items = menu_data["menu"]
                else:
                    items = [menu_data]  # Single product
            else:
                items = menu_data  # Array of products
            
            # Process each item
            for item in items:
                if isinstance(item, dict):
                    # Extract store info
                    store_id = item.get("storeId") or item.get("location") or "unknown"
                    store_name = item.get("storeName") or item.get("locationName") or "Unknown"
                    
                    product = self.extract_product_info(item, dispensary_id, store_id, store_name)
                    if product:
                        product["menu_file"] = blob_path
                        products.append(product)
            
            logger.info(f"Extracted {len(products)} products from {blob_path}")
            return products
        
        except Exception as e:
            logger.error(f"Error processing menu file {blob_path}: {e}")
            return []
    
    async def update_stock(self, products: List[Dict[str, Any]]):
        """Upsert products to Cosmos DB stock container"""
        if not products:
            logger.info("No products to update")
            return
        
        try:
            # Upsert each product
            for product in products:
                await self.container.upsert_item(product)
            
            logger.info(f"OK Updated {len(products)} stock items in Cosmos DB")
        
        except Exception as e:
            logger.error(f"Error updating stock: {e}")
            raise
    
    async def process_latest_menus(self, hours_ago: int = 2):
        """Process menu files from the last N hours"""
        logger.info(f"Processing menu files from last {hours_ago} hours...")
        
        # List blobs in dispensaries folder
        container = self.blob_client.get_container_client(STORAGE_CONTAINER)
        
        all_products = []
        async for blob in container.list_blobs(name_starts_with="dispensaries/"):
            # Check if blob is recent (simple check - could be improved)
            if blob.last_modified and (datetime.utcnow() - blob.last_modified.replace(tzinfo=None)).total_seconds() < hours_ago * 3600:
                products = await self.process_menu_file(blob.name)
                all_products.extend(products)
        
        # Update stock
        await self.update_stock(all_products)
        
        logger.info(f"OK Processed {len(all_products)} total products")
        return len(all_products)
    
    async def process_all_menus(self):
        """Process all menu files (full refresh)"""
        logger.info("Processing ALL menu files (full refresh)...")
        
        container = self.blob_client.get_container_client(STORAGE_CONTAINER)
        
        all_products = []
        async for blob in container.list_blobs(name_starts_with="dispensaries/"):
            if blob.name.endswith(".json"):
                products = await self.process_menu_file(blob.name)
                all_products.extend(products)
        
        # Update stock
        await self.update_stock(all_products)
        
        logger.info(f"OK Full refresh complete: {len(all_products)} products")
        return len(all_products)


async def main():
    """Main entry point for stock updater"""
    logging.basicConfig(level=logging.INFO)
    
    updater = StockUpdater()
    
    try:
        await updater.initialize()
        
        # Process latest menus (default: last 2 hours)
        count = await updater.process_latest_menus(hours_ago=2)
        
        logger.info(f"OK Stock update complete: {count} products")
    
    finally:
        await updater.close()


if __name__ == "__main__":
    asyncio.run(main())
