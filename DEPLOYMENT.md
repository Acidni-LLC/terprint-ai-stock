# Terprint AI Stock Service - Deployment Guide

## ✅ Completed Steps

1. **Repository Scaffolded** ✅
   - ✅ FastAPI application (`app.py`)
   - ✅ Stock updater component (`stock_updater.py`)
   - ✅ Dockerfile for Container Apps
   - ✅ pyproject.toml with dependencies
   - ✅ GitHub Actions CI/CD workflow
   - ✅ README documentation
   - ✅ .gitignore configured
   - ✅ Local Git repository initialized

2. **CMDB Entry Created** ✅
   - ✅ `products/terprint-ai-stock/product.yaml` in acidni-config

3. **App Registry Registration** ✅
   - ✅ Registered with App ID: `8a304f41-cc18-4c3e-b774-3377f76b143b`
   - ✅ Lifecycle stage: `development`

---

## 🚀 Next Steps (Manual Actions Required)

### 1. Create GitHub Repository

```bash
# Navigate to terprint-ai-stock directory
cd C:\Users\JamiesonGill\Documents\GitHub\Acidni-LLC\terprint-ai-stock

# Create GitHub repository (use GitHub CLI or web UI)
gh repo create Acidni-LLC/terprint-ai-stock --public --source=. --remote=origin

# Push code
git push -u origin main
```

**OR via GitHub Web UI:**
1. Go to https://github.com/organizations/Acidni-LLC/repositories/new
2. Name: `terprint-ai-stock`
3. Public repository
4. **Do NOT initialize** with README (we already have one)
5. Create repository
6. Add remote and push:
   ```bash
   git remote add origin https://github.com/Acidni-LLC/terprint-ai-stock.git
   git push -u origin main
   ```

---

### 2. Create Cosmos DB Container

The `stock` container needs to be created in the `TerprintAI` database:

```bash
# Create stock container with partition key /store_id
az cosmosdb sql container create \
  --account-name cosmos-terprint-dev \
  --database-name TerprintAI \
  --name stock \
  --partition-key-path "/store_id" \
  --resource-group rg-dev-terprint-shared
```

**Verify creation:**
```bash
az cosmosdb sql container show \
  --account-name cosmos-terprint-dev \
  --database-name TerprintAI \
  --name stock \
  --resource-group rg-dev-terprint-shared
```

---

### 3. Configure Azure Credentials Secret

The GitHub Actions workflow needs `AZURE_CREDENTIALS` secret:

1. **Create Service Principal:**
   ```bash
   az ad sp create-for-rbac --name "sp-terprint-ai-stock-github" \
     --role contributor \
     --scopes /subscriptions/bb40fccf-9ffa-4bad-b9c0-ea40e326882c/resourceGroups/rg-dev-terprint-ca \
     --sdk-auth
   ```

2. **Copy the JSON output**

3. **Add to GitHub Secrets:**
   - Go to: `https://github.com/Acidni-LLC/terprint-ai-stock/settings/secrets/actions`
   - Click "New repository secret"
   - Name: `AZURE_CREDENTIALS`
   - Value: Paste the JSON output from step 1
   - Click "Add secret"

---

### 4. Grant Container App Managed Identity Access

Once the Container App is deployed (first CI/CD run), grant it access to Cosmos DB:

```bash
# Get the Container App's managed identity principal ID
IDENTITY_ID=$(az containerapp show \
  --name ca-terprint-stock \
  --resource-group rg-dev-terprint-ca \
  --query "identity.principalId" -o tsv)

# Get Cosmos DB resource ID
COSMOS_ID=$(az cosmosdb show \
  --name cosmos-terprint-dev \
  --resource-group rg-dev-terprint-shared \
  --query id -o tsv)

# Assign Cosmos DB Data Contributor role
az role assignment create \
  --assignee $IDENTITY_ID \
  --role "00000000-0000-0000-0000-000000000002" \
  --scope $COSMOS_ID

echo "✅ Cosmos DB access granted to ca-terprint-stock"
```

Also grant access to Blob Storage:

```bash
# Get Storage Account resource ID
STORAGE_ID=$(az storage account show \
  --name stterprintsharedgen2 \
  --resource-group rg-dev-terprint-shared \  --query id -o tsv)

# Assign Storage Blob Data Reader role
az role assignment create \
  --assignee $IDENTITY_ID \
  --role "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1" \
  --scope $STORAGE_ID

echo "✅ Blob Storage read access granted to ca-terprint-stock"
```

---

### 5. Deploy to Azure (First Deployment)

**Option A: Via GitHub Actions (Recommended)**
1. Push code to GitHub (triggers workflow automatically)
2. Monitor: `https://github.com/Acidni-LLC/terprint-ai-stock/actions`

**Option B: Manual Deployment**
```bash
cd C:\Users\JamiesonGill\Documents\GitHub\Acidni-LLC\terprint-ai-stock

# Login to Azure
az login

# Login to ACR
az acr login --name crterprint

# Build and push image
docker build -t crterprint.azurecr.io/terprint-ai-stock:dev-001 .
docker push crterprint.azurecr.io/terprint-ai-stock:dev-001

# Create Container App
az containerapp create \
  --name ca-terprint-stock \
  --resource-group rg-dev-terprint-ca \
  --environment kindmoss-c6723cbe \
  --image crterprint.azurecr.io/terprint-ai-stock:dev-001 \
  --target-port 8000 \
  --ingress external \
  --min-replicas 1 \
  --max-replicas 3 \
  --cpu 0.5 \
  --memory 1.0Gi \
  --registry-server crterprint.azurecr.io \
  --system-assigned
```

---

### 6. Verify Deployment

```bash
# Get Container App URL
FQDN=$(az containerapp show \
  --name ca-terprint-stock \
  --resource-group rg-dev-terprint-ca \
  --query properties.configuration.ingress.fqdn -o tsv)

echo "Service URL: https://${FQDN}"

# Test health endpoint
Invoke-RestMethod -Uri "https://${FQDN}/health" | ConvertTo-Json

# Open API docs
Start-Process "https://${FQDN}/docs"
```

---

### 7. Configure APIM Routing

**Create API in APIM:**

```bash
# Import OpenAPI spec (auto-generated by FastAPI)
az apim api import \
  --resource-group rg-terprint-apim-dev \
  --service-name apim-terprint-dev \
  --api-id terprint-stock-api \
  --path /stock \
  --specification-format OpenApi \
  --specification-url "https://ca-terprint-stock.kindmoss-c6723cbe.eastus2.azurecontainerapps.io/openapi.json" \
  --display-name "Terprint AI Stock" \
  --protocols https \
  --subscription-required true
```

**OR manually via Azure Portal:**
1. Go to: `https://portal.azure.com/#@acidni.net/resource/subscriptions/bb40fccf-9ffa-4bad-b9c0-ea40e326882c/resourceGroups/rg-terprint-apim-dev/providers/Microsoft.ApiManagement/service/apim-terprint-dev/apis`
2. Click "+ Add API" → "OpenAPI"
3. OpenAPI specification URL: `https://ca-terprint-stock.kindmoss-c6723cbe.eastus2.azurecontainerapps.io/openapi.json`
4. API URL suffix: `stock`
5. Create

**Add Backend:**
1. In APIM, go to APIs → Terprint AI Stock → Settings
2. Backend URL: `https://ca-terprint-stock.kindmoss-c6723cbe.eastus2.azurecontainerapps.io`
3. Save

---

### 8. Test via APIM

```powershell
# Get APIM subscription key
$key = az keyvault secret show --vault-name kv-terprint-dev --name apim-subscription-key --query value -o tsv

# Test health check
Invoke-RestMethod -Uri "https://apim-terprint-dev.azure-api.net/stock/health" `
  -Headers @{"Ocp-Apim-Subscription-Key"=$key} | ConvertTo-Json

# Test search
Invoke-RestMethod -Uri "https://apim-terprint-dev.azure-api.net/stock/api/stock/search?product_type=flower&limit=5" `
  -Headers @{"Ocp-Apim-Subscription-Key"=$key} | ConvertTo-Json -Depth 10
```

---

### 9. Integrate Stock Updater into Menu Pipeline

The `stock_updater.py` needs to be triggered after menu downloads. Two options:

**Option A: Add to Menu Downloader**
Modify `terprint-menudownloader` to call stock updater after downloads complete.

**Option B: Create Scheduled Function**
Create an Azure Function that runs every 2 hours to call the stock updater.

**Recommended: Option B (scheduled trigger)**

```python
# In terprint-menudownloader repository, add new function:
@app.schedule(schedule="0 */2 * * *", arg_name="timer", use_monitor=False)
async def update_stock(timer: func.TimerRequest):
    """Update stock inventory after menu downloads"""
    from stock_updater import StockUpdater
    
    updater = StockUpdater()
    try:
        await updater.initialize()
        count = await updater.process_latest_menus(hours_ago=2)
        logger.info(f"✅ Stock updated: {count} products")
    finally:
        await updater.close()
```

---

### 10. DNS Configuration (Optional - Future)

If you want a custom domain:

```bash
# Use acidni-dns to add CNAME
acidni-dns add acidni.net --type CNAME --name stock.terprint \
  --content ca-terprint-stock.kindmoss-c6723cbe.eastus2.azurecontainerapps.io --ttl 3600

# Add Azure verification TXT
acidni-dns add acidni.net --type TXT --name asuid.stock.terprint \
  --content "{azure_verification_token}" --ttl 3600

# Bind custom domain to Container App
az containerapp hostname add \
  --resource-group rg-dev-terprint-ca \
  --name ca-terprint-stock \
  --hostname stock.terprint.acidni.net

az containerapp hostname bind \
  --resource-group rg-dev-terprint-ca \
  --name ca-terprint-stock \
  --hostname stock.terprint.acidni.net \
  --environment kindmoss-c6723cbe \
  --validation-method CNAME
```

---

## 📊 Testing Checklist

After deployment, verify:

- [ ] Health check returns 200: `GET /health`
- [ ] OpenAPI docs accessible: `GET /docs`
- [ ] Search endpoint works: `GET /api/stock/search?product_type=flower`
- [ ] By-strain endpoint works: `GET /api/stock/by-strain/Blue%20Dream`
- [ ] By-store endpoint works: `GET /api/stock/by-store/{store_id}`
- [ ] By-dispensary endpoint works: `GET /api/stock/by-dispensary/2`
- [ ] APIM routing functional
- [ ] Cosmos DB queries executing
- [ ] Stock updater can process menu files

---

## 🔗 Quick Links

| Resource | URL |
|----------|-----|
| **Local Repo** | `C:\Users\JamiesonGill\Documents\GitHub\Acidni-LLC\terprint-ai-stock` |
| **GitHub** | `https://github.com/Acidni-LLC/terprint-ai-stock` (to be created) |
| **Container App** | `https://ca-terprint-stock.kindmoss-c6723cbe.eastus2.azurecontainerapps.io` |
| **APIM Endpoint** | `https://apim-terprint-dev.azure-api.net/stock` |
| **API Docs** | `https://ca-terprint-stock.kindmoss-c6723cbe.eastus2.azurecontainerapps.io/docs` |
| **Product YAML** | `acidni-config/products/terprint-ai-stock/product.yaml` |
| **App Registry** | ID: `8a304f41-cc18-4c3e-b774-3377f76b143b` |

---

## 🎯 Success Criteria

Service is production-ready when:

1. ✅ Code pushed to GitHub
2. ✅ Cosmos DB container created
3. ✅ CI/CD pipeline deploys automatically
4. ✅ Container App running and healthy
5. ✅ Managed identity has Cosmos + Blob access
6. ✅ APIM routing configured
7. ✅ Stock updater integrated into menu pipeline
8. ✅ All API endpoints return expected data
9. ✅ Terprint.Web can consume the API
10. ✅ App Registry transitioned to "production" stage

---

## 📞 Support

- **Technical Issues:** jamieson@acidni.net
- **Documentation:** See README.md in repository
- **Architecture Questions:** Review `product.yaml`

---

**Created:** 2026-02-14  
**Status:** Awaiting deployment
**Next Action:** Create GitHub repository and trigger first CI/CD run
