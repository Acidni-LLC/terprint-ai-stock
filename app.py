"""
Terprint AI Stock Service
FastAPI application for real-time cannabis product inventory tracking

Provides stock availability data from menu downloads with links to batch,
strain, and dispensary details on terprint.web
"""

import logging
from datetime import datetime
from typing import List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from azure.cosmos.aio import CosmosClient
from azure.identity.aio import DefaultAzureCredential

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("terprint-ai-stock")

# Cosmos DB configuration
COSMOS_ENDPOINT = "https://cosmos-terprint-dev.documents.azure.com:443/"
DATABASE_NAME = "TerprintAI"
CONTAINER_NAME = "stock"
APP_VERSION = "20260214-001"

# Global clients
cosmos_client: Optional[CosmosClient] = None
container = None


# Pydantic Models
class StockItem(BaseModel):
    """Stock item representing a product available at a dispensary"""
    id: str = Field(..., description="Unique identifier (hash of key fields)")
    strain_name: str = Field(..., description="Product/strain name")
    product_type: str = Field(..., description="Product category (flower, vape, etc)")
    store_id: str = Field(..., description="Store/location identifier")
    store_name: str = Field(..., description="Store name")
    dispensary_id: int = Field(..., description="Dispensary/grower ID")
    dispensary_name: str = Field(..., description="Dispensary name")
    batch_id: Optional[str] = Field(None, description="Batch number if available")
    price: float = Field(..., description="Current price")
    size: Optional[str] = Field(None, description="Product size (3.5g, 1g, etc)")
    menu_file: str = Field(..., description="Source menu file path")
    last_seen: str = Field(..., description="ISO timestamp of last menu download")
    product_url: Optional[str] = Field(None, description="Link to product on terprint.web")
    batch_url: Optional[str] = Field(None, description="Link to batch details")
    strain_url: Optional[str] = Field(None, description="Link to strain details")
    dispensary_url: Optional[str] = Field(None, description="Link to dispensary details")


class StockQueryResponse(BaseModel):
    """Response for stock queries"""
    total: int
    items: List[StockItem]
    timestamp: str


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    service: str
    version: str
    timestamp: str
    cosmos_connected: bool


# Lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup resources"""
    global cosmos_client, container
    
    logger.info("Initializing Terprint AI Stock Service...")
    
    try:
        # Initialize Cosmos DB client with managed identity
        credential = DefaultAzureCredential()
        cosmos_client = CosmosClient(COSMOS_ENDPOINT, credential)
        database = cosmos_client.get_database_client(DATABASE_NAME)
        container = database.get_container_client(CONTAINER_NAME)
        logger.info("OK Cosmos DB connection established")
    except Exception as e:
        logger.error(f"ERROR Failed to connect to Cosmos DB: {e}")
        # Service will still start but will fail on requests
    
    yield
    
    logger.info("Shutting down Terprint AI Stock Service...")
    if cosmos_client:
        await cosmos_client.close()


# FastAPI app
app = FastAPI(
    title="Terprint AI Stock Service",
    description="Real-time cannabis product inventory tracking",
    version=APP_VERSION,
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # APIM will handle actual CORS
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_version_header(request, call_next):
    """Add version tag to all responses."""
    response = await call_next(request)
    response.headers["X-App-Version"] = APP_VERSION
    return response


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    cosmos_connected = container is not None
    
    return HealthResponse(
        status="healthy" if cosmos_connected else "degraded",
        service="terprint-ai-stock",
        version=APP_VERSION,
        timestamp=datetime.utcnow().isoformat(),
        cosmos_connected=cosmos_connected
    )


@app.get("/api/stock/search", response_model=StockQueryResponse)
async def search_stock(
    strain: Optional[str] = Query(None, description="Strain name (partial match)"),
    strain_names: Optional[str] = Query(
        None,
        description="Comma-separated strain names to filter (e.g. favorites list)",
        alias="strain_names",
    ),
    product_type: Optional[str] = Query(None, description="Product type filter"),
    dispensary: Optional[str] = Query(None, description="Dispensary name"),
    store_id: Optional[str] = Query(None, description="Store ID"),
    min_price: Optional[float] = Query(None, description="Minimum price"),
    max_price: Optional[float] = Query(None, description="Maximum price"),
    limit: int = Query(100, le=1000, description="Max results to return")
):
    """
    Search stock inventory with flexible filters
    
    Examples:
    - /api/stock/search?strain=Blue%20Dream
    - /api/stock/search?strain_names=Blue%20Dream,OG%20Kush,Gelato
    - /api/stock/search?product_type=flower&dispensary=MUV
    - /api/stock/search?store_id=muv-orlando
    - /api/stock/search?max_price=50
    """
    if not container:
        raise HTTPException(status_code=503, detail="Database connection not available")
    
    # Build query
    query_parts = ["SELECT * FROM c WHERE 1=1"]
    parameters = []
    
    if strain:
        query_parts.append("AND CONTAINS(LOWER(c.strain_name), @strain)")
        parameters.append({"name": "@strain", "value": strain.lower()})
    
    if strain_names:
        names = [n.strip() for n in strain_names.split(",") if n.strip()]
        if names:
            or_clauses = []
            for i, name in enumerate(names):
                param = f"@sn{i}"
                or_clauses.append(f"CONTAINS(LOWER(c.strain_name), {param})")
                parameters.append({"name": param, "value": name.lower()})
            query_parts.append(f"AND ({' OR '.join(or_clauses)})")
    
    if product_type:
        query_parts.append("AND LOWER(c.product_type) = @product_type")
        parameters.append({"name": "@product_type", "value": product_type.lower()})
    
    if dispensary:
        query_parts.append("AND CONTAINS(LOWER(c.dispensary_name), @dispensary)")
        parameters.append({"name": "@dispensary", "value": dispensary.lower()})
    
    if store_id:
        query_parts.append("AND c.store_id = @store_id")
        parameters.append({"name": "@store_id", "value": store_id})
    
    if min_price is not None:
        query_parts.append("AND c.price >= @min_price")
        parameters.append({"name": "@min_price", "value": min_price})
    
    if max_price is not None:
        query_parts.append("AND c.price <= @max_price")
        parameters.append({"name": "@max_price", "value": max_price})
    
    query_parts.append(f"ORDER BY c.last_seen DESC OFFSET 0 LIMIT {limit}")
    query = " ".join(query_parts)
    
    try:
        items = []
        query_iterator = container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        )
        
        async for item in query_iterator:
            items.append(StockItem(**item))
        
        return StockQueryResponse(
            total=len(items),
            items=items,
            timestamp=datetime.utcnow().isoformat()
        )
    
    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(status_code=500, detail=f"Query error: {str(e)}")


@app.get("/api/stock/by-strain/{strain_name}", response_model=StockQueryResponse)
async def get_stock_by_strain(strain_name: str):
    """Get all stock for a specific strain across all locations"""
    if not container:
        raise HTTPException(status_code=503, detail="Database connection not available")
    
    query = "SELECT * FROM c WHERE LOWER(c.strain_name) = @strain ORDER BY c.dispensary_name, c.store_name"
    parameters = [{"name": "@strain", "value": strain_name.lower()}]
    
    try:
        items = []
        query_iterator = container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        )
        
        async for item in query_iterator:
            items.append(StockItem(**item))
        
        return StockQueryResponse(
            total=len(items),
            items=items,
            timestamp=datetime.utcnow().isoformat()
        )
    
    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(status_code=500, detail=f"Query error: {str(e)}")


@app.get("/api/stock/by-store/{store_id}", response_model=StockQueryResponse)
async def get_stock_by_store(store_id: str):
    """Get all stock at a specific store location"""
    if not container:
        raise HTTPException(status_code=503, detail="Database connection not available")
    
    query = "SELECT * FROM c WHERE c.store_id = @store_id ORDER BY c.product_type, c.strain_name"
    parameters = [{"name": "@store_id", "value": store_id}]
    
    try:
        items = []
        query_iterator = container.query_items(
            query=query,
            parameters=parameters,
            partition_key=store_id  # Optimized query
        )
        
        async for item in query_iterator:
            items.append(StockItem(**item))
        
        return StockQueryResponse(
            total=len(items),
            items=items,
            timestamp=datetime.utcnow().isoformat()
        )
    
    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(status_code=500, detail=f"Query error: {str(e)}")


@app.get("/api/stock/by-dispensary/{dispensary_id}", response_model=StockQueryResponse)
async def get_stock_by_dispensary(dispensary_id: int):
    """Get all stock for a dispensary across all locations"""
    if not container:
        raise HTTPException(status_code=503, detail="Database connection not available")
    
    query = "SELECT * FROM c WHERE c.dispensary_id = @dispensary_id ORDER BY c.store_name, c.product_type"
    parameters = [{"name": "@dispensary_id", "value": dispensary_id}]
    
    try:
        items = []
        query_iterator = container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        )
        
        async for item in query_iterator:
            items.append(StockItem(**item))
        
        return StockQueryResponse(
            total=len(items),
            items=items,
            timestamp=datetime.utcnow().isoformat()
        )
    
    except Exception as e:
        logger.error(f"Query failed: {e}")
        raise HTTPException(status_code=500, detail=f"Query error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
