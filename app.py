"""
Terprint AI Stock Service
FastAPI application for real-time cannabis product inventory tracking

Provides stock availability data from menu downloads with links to batch,
strain, and dispensary details on terprint.web
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from azure.cosmos.aio import CosmosClient
from azure.identity.aio import DefaultAzureCredential

from problem_details import register_problem_handlers

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
LEDGER_CONTAINER_NAME = "stock-ledger"
APP_VERSION = "20260307-001"

# Global clients
cosmos_client: Optional[CosmosClient] = None
container = None
ledger_container = None


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


# ─── Browse / Status response models (match Teams frontend contract) ───

def _slugify(text: str) -> str:
    """Convert a string to a URL-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return re.sub(r"-+", "-", slug).strip("-")


class BrowseStockItem(BaseModel):
    id: str
    dispensary: str
    dispensary_slug: str
    store: str
    store_city: str = ""
    product_name: str
    strain: str
    strain_slug: str
    product_type: str
    product_sub_type: str = ""
    size_uom: str = ""
    price: float
    price_per_gram: Optional[float] = None
    time_in_stock_hours: float = 0
    last_seen: str
    batch_id: str = ""
    batch_name: str = ""
    product_url: Optional[str] = None
    teams_strain_url: str = ""
    teams_batch_url: str = ""
    web_strain_url: str = ""
    web_batch_url: str = ""
    portal_strain_url: str = ""
    top_terpenes: List[Dict[str, Any]] = []
    store_lat: Optional[float] = None
    store_lng: Optional[float] = None
    store_address: str = ""


class FiltersApplied(BaseModel):
    dispensary: Optional[str] = None
    store: Optional[str] = None
    strain: Optional[str] = None
    product_type: Optional[str] = None
    product_sub_type: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    in_stock_hours: Optional[float] = None


class SortInfo(BaseModel):
    by: str = "time_in_stock"
    order: str = "asc"


class BrowseResponse(BaseModel):
    items: List[BrowseStockItem]
    total: int
    total_all: int
    limit: int
    offset: int
    has_more: bool
    filters_applied: FiltersApplied
    sort: SortInfo


class DispensaryDetail(BaseModel):
    count: int
    stores: int
    freshest_hours: float


class CategoryStat(BaseModel):
    category: str
    count: int


class IndexMetadata(BaseModel):
    version: str
    build_date: str
    total_items: int
    dispensaries: Dict[str, DispensaryDetail]
    unique_strains: int
    categories: List[CategoryStat] = []
    stores: int = 0
    source_date_range: Optional[str] = None


class StockStatusData(BaseModel):
    status: str
    service: str
    index_available: bool
    index_metadata: IndexMetadata
    timestamp: str


# Lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup resources"""
    global cosmos_client, container, ledger_container
    
    logger.info("Initializing Terprint AI Stock Service...")
    
    try:
        # Initialize Cosmos DB client with managed identity
        credential = DefaultAzureCredential()
        cosmos_client = CosmosClient(COSMOS_ENDPOINT, credential)
        database = cosmos_client.get_database_client(DATABASE_NAME)
        container = database.get_container_client(CONTAINER_NAME)
        ledger_container = database.get_container_client(LEDGER_CONTAINER_NAME)
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

# RFC 7807 Problem Details error handlers
register_problem_handlers(app, app_name="terprint-ai-stock")


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
            parameters=parameters
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
            parameters=parameters
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
            parameters=parameters
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


# ─── Helper: map Cosmos document → BrowseStockItem ───────────

def _map_to_browse_item(doc: dict) -> BrowseStockItem:
    """Map a Cosmos stock document to the frontend BrowseStockItem contract."""
    strain = doc.get("strain_name", "")
    strain_slug = _slugify(strain) if strain else ""
    dispensary = doc.get("dispensary_name", "")
    dispensary_slug = _slugify(dispensary) if dispensary else ""
    store = doc.get("store_name", "")
    batch_id = doc.get("batch_id", "") or ""
    batch_name = doc.get("batch_name", "") or batch_id

    # Calculate hours since last seen
    time_in_stock_hours = 0.0
    last_seen = doc.get("last_seen", "")
    if last_seen:
        try:
            seen_dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
            delta = datetime.now(timezone.utc) - seen_dt
            time_in_stock_hours = round(delta.total_seconds() / 3600, 1)
        except (ValueError, TypeError):
            pass

    # Generate URLs
    web_base = "https://terprint.net"
    teams_strain_url = ""
    teams_batch_url = ""
    if strain_slug:
        teams_strain_url = f"{web_base}/strains/{strain_slug}"
        web_strain_url = f"{web_base}/strains/{strain_slug}"
        portal_strain_url = f"{web_base}/strains/{strain_slug}"
    else:
        web_strain_url = ""
        portal_strain_url = ""

    if batch_id:
        teams_batch_url = f"{web_base}/batches/{batch_id}"
        web_batch_url = f"{web_base}/batches/{batch_id}"
    else:
        web_batch_url = ""

    return BrowseStockItem(
        id=doc.get("id", ""),
        dispensary=dispensary,
        dispensary_slug=dispensary_slug,
        store=store,
        store_city=doc.get("store_city", ""),
        product_name=doc.get("product_name", strain),
        strain=strain,
        strain_slug=strain_slug,
        product_type=doc.get("product_type", ""),
        product_sub_type=doc.get("product_sub_type", ""),
        size_uom=doc.get("size", "") or doc.get("size_uom", "") or "",
        price=doc.get("price", 0),
        price_per_gram=doc.get("price_per_gram"),
        time_in_stock_hours=time_in_stock_hours,
        last_seen=last_seen,
        batch_id=batch_id,
        batch_name=batch_name,
        product_url=doc.get("product_url"),
        teams_strain_url=teams_strain_url,
        teams_batch_url=teams_batch_url,
        web_strain_url=web_strain_url,
        web_batch_url=web_batch_url,
        portal_strain_url=portal_strain_url,
        top_terpenes=doc.get("top_terpenes", []),
        store_lat=doc.get("store_lat"),
        store_lng=doc.get("store_lng"),
        store_address=doc.get("store_address", ""),
    )


# ─── /api/stock/status — aggregate index metadata ────────────

@app.get("/api/stock/status", response_model=StockStatusData)
async def stock_status():
    """Return aggregate stats about the stock index."""
    if not container:
        return StockStatusData(
            status="degraded",
            service="terprint-ai-stock",
            index_available=False,
            index_metadata=IndexMetadata(
                version=APP_VERSION,
                build_date=datetime.now(timezone.utc).isoformat(),
                total_items=0,
                dispensaries={},
                unique_strains=0,
                categories=[],
                stores=0,
            ),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    try:
        # Total items
        count_q = "SELECT VALUE COUNT(1) FROM c"
        total_items = 0
        async for row in container.query_items(count_q):
            total_items = row

        # Unique strains (Cosmos DB doesn't support COUNT(DISTINCT) or subqueries in FROM)
        strain_set: set[str] = set()
        async for row in container.query_items("SELECT DISTINCT VALUE c.strain_name FROM c"):
            strain_set.add(row)
        unique_strains = len(strain_set)

        # By dispensary
        disp_q = (
            "SELECT c.dispensary_name, c.store_id, COUNT(1) AS cnt "
            "FROM c GROUP BY c.dispensary_name, c.store_id"
        )
        disp_agg: Dict[str, dict] = {}
        async for row in container.query_items(disp_q):
            name = row.get("dispensary_name", "Unknown")
            if name not in disp_agg:
                disp_agg[name] = {"count": 0, "stores": set()}
            disp_agg[name]["count"] += row.get("cnt", 0)
            disp_agg[name]["stores"].add(row.get("store_id"))
        dispensaries: Dict[str, DispensaryDetail] = {}
        for name, agg in disp_agg.items():
            dispensaries[name] = DispensaryDetail(
                count=agg["count"],
                stores=len(agg["stores"]),
                freshest_hours=0,
            )

        # By category
        cat_q = "SELECT c.product_type, COUNT(1) AS cnt FROM c GROUP BY c.product_type"
        categories: List[CategoryStat] = []
        async for row in container.query_items(cat_q):
            categories.append(CategoryStat(
                category=row.get("product_type", "unknown"),
                count=row.get("cnt", 0),
            ))

        # Unique stores
        store_set: set[str] = set()
        async for row in container.query_items("SELECT DISTINCT VALUE c.store_id FROM c"):
            store_set.add(row)
        store_count = len(store_set)

        index_available = total_items > 0

        return StockStatusData(
            status="healthy",
            service="terprint-ai-stock",
            index_available=index_available,
            index_metadata=IndexMetadata(
                version=APP_VERSION,
                build_date=datetime.now(timezone.utc).isoformat(),
                total_items=total_items,
                dispensaries=dispensaries,
                unique_strains=unique_strains,
                categories=categories,
                stores=store_count,
            ),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as e:
        logger.error(f"Stock status aggregation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Aggregation error: {str(e)}")


# ─── /api/stock/browse — paginated, filterable browse ─────────

SORT_COLUMN_MAP = {
    "dispensary": "c.dispensary_name",
    "store": "c.store_name",
    "product_name": "c.strain_name",
    "strain": "c.strain_name",
    "product_type": "c.product_type",
    "size_uom": "c.size",
    "price": "c.price",
    "time_in_stock": "c.last_seen",
}


@app.get("/api/stock/browse", response_model=BrowseResponse)
async def browse_stock(
    limit: int = Query(100, le=2000),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("time_in_stock"),
    sort_order: str = Query("asc"),
    dispensary: Optional[str] = Query(None),
    store: Optional[str] = Query(None),
    strain: Optional[str] = Query(None),
    product_type: Optional[str] = Query(None),
    product_sub_type: Optional[str] = Query(None),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    in_stock_hours: Optional[float] = Query(None),
):
    """Paginated browse of stock items with filters and sorting."""
    if not container:
        raise HTTPException(status_code=503, detail="Database connection not available")

    try:
        where_clauses = ["1=1"]
        parameters: List[Dict[str, Any]] = []

        if dispensary:
            where_clauses.append("CONTAINS(LOWER(c.dispensary_name), @dispensary)")
            parameters.append({"name": "@dispensary", "value": dispensary.lower()})
        if store:
            where_clauses.append("CONTAINS(LOWER(c.store_name), @store)")
            parameters.append({"name": "@store", "value": store.lower()})
        if strain:
            where_clauses.append("CONTAINS(LOWER(c.strain_name), @strain)")
            parameters.append({"name": "@strain", "value": strain.lower()})
        if product_type:
            where_clauses.append("LOWER(c.product_type) = @product_type")
            parameters.append({"name": "@product_type", "value": product_type.lower()})
        if product_sub_type:
            where_clauses.append("LOWER(c.product_sub_type) = @product_sub_type")
            parameters.append({"name": "@product_sub_type", "value": product_sub_type.lower()})
        if min_price is not None:
            where_clauses.append("c.price >= @min_price")
            parameters.append({"name": "@min_price", "value": min_price})
        if max_price is not None:
            where_clauses.append("c.price <= @max_price")
            parameters.append({"name": "@max_price", "value": max_price})

        where = " AND ".join(where_clauses)

        # Total without pagination (filtered)
        count_query = f"SELECT VALUE COUNT(1) FROM c WHERE {where}"
        total = 0
        async for row in container.query_items(count_query, parameters=parameters):
            total = row

        # Total unfiltered
        total_all = 0
        async for row in container.query_items("SELECT VALUE COUNT(1) FROM c"):
            total_all = row

        # Sort
        cosmos_sort = SORT_COLUMN_MAP.get(sort_by, "c.last_seen")
        order = "DESC" if sort_order.lower() == "desc" else "ASC"
        # For time_in_stock, we sort by last_seen inversely
        if sort_by == "time_in_stock":
            order = "ASC" if sort_order.lower() == "asc" else "DESC"

        data_query = (
            f"SELECT * FROM c WHERE {where} "
            f"ORDER BY {cosmos_sort} {order} "
            f"OFFSET {offset} LIMIT {limit}"
        )

        items: List[BrowseStockItem] = []
        async for doc in container.query_items(data_query, parameters=parameters):
            item = _map_to_browse_item(doc)
            # Apply in_stock_hours filter client-side (Cosmos can't compute this)
            if in_stock_hours is not None and item.time_in_stock_hours > in_stock_hours:
                continue
            items.append(item)

        return BrowseResponse(
            items=items,
            total=total,
            total_all=total_all,
            limit=limit,
            offset=offset,
            has_more=(offset + limit) < total,
            filters_applied=FiltersApplied(
                dispensary=dispensary,
                store=store,
                strain=strain,
                product_type=product_type,
                product_sub_type=product_sub_type,
                min_price=min_price,
                max_price=max_price,
                in_stock_hours=in_stock_hours,
            ),
            sort=SortInfo(by=sort_by, order=sort_order),
        )

    except Exception as e:
        logger.error(f"Browse query failed: {e}")
        raise HTTPException(status_code=500, detail=f"Browse error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
