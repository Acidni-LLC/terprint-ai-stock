# Terprint AI Stock Service

Real-time cannabis product inventory tracking service for the Terprint platform.

## Overview

The Terprint AI Stock Service provides a queryable API for real-time product availability across all Florida dispensaries. Updated automatically after each menu download, it enables:

- **Stock availability queries** by strain, product type, location, or price
- **Deep linking** to batch details, strain profiles, and dispensary info on terprint.web
- **Multi-app integration** for Terprint.Web, mobile apps, and third-party services

## Features

- **Real-time inventory** - Updated automatically from menu downloads
- **Flexible querying** - Search by strain, type, location, dispensary, or price
- **Deep linking** - Generate URLs to Terprint.Web for detailed views
- **Fast Cosmos DB queries** - Partition key optimization for store-level queries
- **Auto-documented API** - OpenAPI/Swagger at `/docs`
- **Health monitoring** - Built-in health checks

## API Endpoints

### Health Check
```
GET /health
```

### Search Stock
```
GET /api/stock/search?strain={name}&product_type={type}&dispensary={name}&store_id={id}&min_price={price}&max_price={price}
```

### By Strain
```
GET /api/stock/by-strain/{strain_name}
```

### By Store
```
GET /api/stock/by-store/{store_id}
```

### By Dispensary
```
GET /api/stock/by-dispensary/{dispensary_id}
```

## Data Model

Each stock item contains:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier |
| `strain_name` | string | Product/strain name |
| `product_type` | string | Category (flower, vape, etc) |
| `store_id` | string | Store identifier |
| `store_name` | string | Store name |
| `dispensary_id` | int | Grower ID (1=Cookies, 2=MUV, etc) |
| `dispensary_name` | string | Dispensary name |
| `batch_id` | string | Batch number (if available) |
| `price` | float | Current price |
| `size` | string | Product size |
| `menu_file` | string | Source menu file path |
| `last_seen` | string | ISO timestamp |
| `product_url` | string | Link to product details |
| `batch_url` | string | Link to batch details |
| `strain_url` | string | Link to strain profile |
| `dispensary_url` | string | Link to dispensary page |

## Cosmos DB Structure

**Database:** `TerprintAI`  
**Container:** `stock`  
**Partition Key:** `/store_id` (optimized for store-level queries)

## Local Development

### Prerequisites
- Python 3.12+
- Poetry
- Azure CLI (logged in)

### Setup

```bash
# Clone repository
git clone https://github.com/Acidni-LLC/terprint-ai-stock.git
cd terprint-ai-stock

# Install dependencies
poetry install

# Run locally
poetry run uvicorn app:app --reload --port 8000
```

### Test Endpoints

```powershell
# Health check
Invoke-RestMethod -Uri "http://localhost:8000/health"

# Search stock
Invoke-RestMethod -Uri "http://localhost:8000/api/stock/search?strain=Blue%20Dream"

# API documentation
Start-Process "http://localhost:8000/docs"
```

## Deployment

### Container App

**Production:**
- **Name:** `ca-terprint-stock`
- **Resource Group:** `rg-dev-terprint-ca`
- **Environment:** `kindmoss-c6723cbe`
- **FQDN:** `ca-terprint-stock.kindmoss-c6723cbe.eastus2.azurecontainerapps.io`

### CI/CD

Push to `main` branch triggers automatic deployment via GitHub Actions.

```bash
git add .
git commit -m "feat: stock tracking updates"
git push
```

## APIM Integration

**Path:** `/stock`

### Example Routes
```
https://apim-terprint-dev.azure-api.net/stock/health
https://apim-terprint-dev.azure-api.net/stock/api/stock/search?strain=Blue%20Dream
https://apim-terprint-dev.azure-api.net/stock/api/stock/by-store/muv-orlando
```

### Required Headers
```
Ocp-Apim-Subscription-Key: {key}
```

## Integration with Menu Pipeline

The stock service is updated by the menu download pipeline:

1. **Menu Downloader** fetches dispensary menus every 2 hours
2. **Stock Updater** (new) processes downloaded menus and updates Cosmos DB
3. **Batch Processor** enriches stock data with batch information
4. **Stock API** provides real-time query access

## Usage Examples

### Terprint.Web Integration

```csharp
// Find all locations with a specific strain in stock
var response = await _httpClient.GetAsync(
    "https://apim-terprint-dev.azure-api.net/stock/api/stock/by-strain/Blue%20Dream"
);
var stockData = await response.Content.ReadFromJsonAsync<StockQueryResponse>();

foreach (var item in stockData.Items)
{
    Console.WriteLine($"{item.StrainName} at {item.StoreName}: ${item.Price}");
    // Display link to batch: item.BatchUrl
}
```

### Python Integration

```python
import httpx

async with httpx.AsyncClient() as client:
    response = await client.get(
        "https://apim-terprint-dev.azure-api.net/stock/api/stock/search",
        params={"product_type": "flower", "max_price": 50},
        headers={"Ocp-Apim-Subscription-Key": api_key}
    )
    stock = response.json()
    
    for item in stock["items"]:
        print(f"{item['strain_name']} - ${item['price']}")
```

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ Menu Downloader │────▶│ Stock Updater    │────▶│ Cosmos DB       │
│ (every 2 hrs)   │     │ (new component)  │     │ TerprintAI/stock│
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                                           │
                                                           │ Query
                                                           │
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ Client Apps     │────▶│ APIM Gateway     │────▶│ Stock API       │
│ (Web, Mobile)   │     │ /stock/*         │     │ (FastAPI)       │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

## Monitoring

- **Health Check:** `GET /health`
- **Application Insights:** `terprintai-insights`
- **Container App Logs:** `az containerapp logs show --name ca-terprint-stock --resource-group rg-dev-terprint-ca`

## Security

- **Managed Identity** - No connection strings in code
- **APIM Gateway** - All traffic through API Management
- **CORS** - Configured for allowed origins
- **HTTPS** - Enforced by Container Apps

## Contributing

1. Create feature branch from `main`
2. Make changes and test locally
3. Submit PR with conventional commit messages
4. Ensure CI/CD passes

## License

Copyright (c) 2026 Acidni LLC. All rights reserved.

## Support

- **Technical Issues:** jamieson@acidni.net
- **Documentation:** https://terprint.acidni.net/docs
- **Status:** https://status.acidni.net
