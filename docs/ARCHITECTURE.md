# Terprint AI Stock — Architecture Document

**Product Code:** `stock` | **Status:** Development | **Last Updated:** 2026-03-07

---

## Overview

Terprint AI Stock is a real-time cannabis product inventory tracking API for the Terprint platform. It provides queryable stock availability across Florida dispensaries, automatically updated after each menu download cycle.

---

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Language | Python | 3.12+ |
| Web Framework | FastAPI | 0.109.0 |
| ASGI Server | Uvicorn | 0.27.0 |
| Database | Azure Cosmos DB | NoSQL API |
| Storage | Azure Blob Storage | — |
| Authentication | Azure Identity (Managed Identity) | — |
| Validation | Pydantic | 2.9+ |
| Container | Docker (python:3.12-slim) | — |
| CI/CD | GitHub Actions | — |
| Package Manager | Poetry | 1.8.3 |

---

## System Architecture

```
┌──────────────────────────────────────────────┐
│            Consumer Applications              │
│   (Terprint AI Teams, Web App, Power BI)     │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
          ┌────────────────────────┐
          │  Azure API Management  │
          │   /api/stock           │
          │  • Subscription keys   │
          │  • Rate limiting       │
          └────────────┬───────────┘
                       │
                       ▼
          ┌────────────────────────────────┐
          │  Container App                 │
          │  ca-terprint-stock             │
          │  Port: 8000                    │
          │                                │
          │  FastAPI Application           │
          │  • Multi-parameter search      │
          │  • Deep linking to Terprint    │
          │  • RFC 7807 error responses    │
          │  • Health monitoring           │
          └───────┬────────────┬───────────┘
                  │            │
                  ▼            ▼
    ┌──────────────────┐  ┌──────────────────┐
    │  Cosmos DB        │  │  Blob Storage    │
    │  cosmos-terprint  │  │  stterprintshared│
    │  DB: TerprintAI   │  │  Container:      │
    │                   │  │  jsonfiles       │
    │  Containers:      │  │                  │
    │  • stock          │  │  Source menu     │
    │  • stock-ledger   │  │  files           │
    └──────────────────┘  └──────────────────┘
```

---

## Deployment

| Property | Value |
|----------|-------|
| Container App | `ca-terprint-stock` |
| Resource Group | `rg-dev-acidni-shared` |
| Environment | `cae-acidni-dev` |
| Registry | `cracidnidev.azurecr.io` |
| Image Tag | `dev-{github-sha}` |
| Port | 8000 |
| Ingress | External |
| Replicas | 0–3 (auto-scaling) |
| CPU | 0.5 cores |
| Memory | 1.0 GB |

---

## API Endpoints

### Health & Status

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Health check with Cosmos connection status |
| GET | `/api/stock/status` | Inventory index metadata (counts, categories, dispensaries) |

### Search & Query

| Method | Path | Parameters | Purpose |
|--------|------|-----------|---------|
| GET | `/api/stock/search` | `strain`, `strain_names`, `product_type`, `dispensary`, `store_id`, `min_price`, `max_price`, `limit` | Multi-parameter product search |
| GET | `/api/stock/dispensaries` | — | List all dispensaries with stock |
| GET | `/api/stock/categories` | — | Product type breakdown |
| GET | `/api/stock/store/{store_id}` | — | All products at a specific store |

---

## Database Schema

### Stock Container
Partition key: `/store_id`

```json
{
  "id": "hash-of-key-fields",
  "strain_name": "Blue Dream",
  "product_type": "flower",
  "store_id": "muv-orlando",
  "store_name": "MUV Orlando",
  "dispensary_id": 2,
  "dispensary_name": "MUV",
  "batch_id": "MUV-123456",
  "price": 39.99,
  "size": "3.5g",
  "price_per_gram": 11.43,
  "last_seen": "2026-03-07T14:30:00Z",
  "product_url": "https://terprint.net/...",
  "batch_url": "https://terprint.net/batches/MUV-123456",
  "strain_url": "https://terprint.net/strains/blue-dream",
  "dispensary_url": "https://terprint.net/dispensaries/2",
  "store_lat": 28.5421,
  "store_lng": -81.3723,
  "store_city": "Orlando",
  "top_terpenes": [{"name": "Myrcene", "pct": 1.2}]
}
```

---

## Data Pipeline

Stock data flows from upstream menu downloads:

```
Menu Downloader (scheduled)
        │
        ▼
  Blob Storage (jsonfiles/)
        │
        ▼
  Batch Processor
        │
        ▼
  Cosmos DB (stock container)
        │
        ▼
  Stock API (query layer)
```

---

## Authentication & Security

- APIM subscription key required for external access
- Managed Identity for Cosmos DB and Blob Storage (RBAC)
- CORS middleware enabled for cross-origin requests
- RFC 7807 Problem Details for all error responses

---

## Dependencies

| Service | Purpose |
|---------|---------|
| Azure Cosmos DB (`cosmos-terprint-dev`) | Primary data store |
| Azure Blob Storage (`stterprintsharedgen2`) | Source menu files |
| Azure APIM | API gateway |
| Terprint Menu Downloader | Upstream data source |
| Terprint Batch Processor | Data transformation |
| Application Insights | Observability |
