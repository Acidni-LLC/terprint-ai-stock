# Terprint AI Stock Service - Deployment Guide

## Status

- Repository scaffolded with FastAPI app, stock updater, Dockerfile, and CI workflow
- CMDB entry added in acidni-config
- App Registry entry created (ID `8a304f41-cc18-4c3e-b774-3377f76b143b`)

## Step 1: Create GitHub Repository

```powershell
Set-Location "C:\Users\JamiesonGill\Documents\GitHub\Acidni-LLC\terprint-ai-stock"

# Create GitHub repository (CLI)
gh repo create Acidni-LLC/terprint-ai-stock --public --source=. --remote=origin

# Push code
git push -u origin main
```

GitHub Web UI:

1. Go to [https://github.com/organizations/Acidni-LLC/repositories/new](https://github.com/organizations/Acidni-LLC/repositories/new)
2. Name: `terprint-ai-stock`
3. Public repository
4. Do not initialize with README
5. Create repository
6. Add remote and push:

```powershell
git remote add origin https://github.com/Acidni-LLC/terprint-ai-stock.git
git push -u origin main
```

## Step 2: Create Cosmos DB Container

```powershell
az cosmosdb sql container create `
  --account-name cosmos-terprint-dev `
  --database-name TerprintAI `
  --name stock `
  --partition-key-path "/store_id" `
  --resource-group rg-dev-terprint-shared
```

Verify:

```powershell
az cosmosdb sql container show `
  --account-name cosmos-terprint-dev `
  --database-name TerprintAI `
  --name stock `
  --resource-group rg-dev-terprint-shared
```

## Step 3: Configure GitHub Actions Secret

```powershell
az ad sp create-for-rbac --name "sp-terprint-ai-stock-github" `
  --role contributor `
  --scopes /subscriptions/bb40fccf-9ffa-4bad-b9c0-ea40e326882c/resourceGroups/rg-dev-terprint-ca `
  --sdk-auth
```

Add the JSON output as a GitHub secret:

- Repo settings: [https://github.com/Acidni-LLC/terprint-ai-stock/settings/secrets/actions](https://github.com/Acidni-LLC/terprint-ai-stock/settings/secrets/actions)
- Name: `AZURE_CREDENTIALS`

## Step 4: Deploy via CI/CD

Push to `main` triggers deployment. Monitor runs at:

- [https://github.com/Acidni-LLC/terprint-ai-stock/actions](https://github.com/Acidni-LLC/terprint-ai-stock/actions)

## Step 5: Grant Managed Identity Access

After the Container App is created:

```powershell
$identityId = az containerapp show `
  --name ca-terprint-stock `
  --resource-group rg-dev-terprint-ca `
  --query identity.principalId -o tsv

$cosmosId = az cosmosdb show `
  --name cosmos-terprint-dev `
  --resource-group rg-dev-terprint-shared `
  --query id -o tsv

az role assignment create `
  --assignee $identityId `
  --role "00000000-0000-0000-0000-000000000002" `
  --scope $cosmosId
```

Blob read access:

```powershell
$storageId = az storage account show `
  --name stterprintsharedgen2 `
  --resource-group rg-dev-terprint-shared `
  --query id -o tsv

az role assignment create `
  --assignee $identityId `
  --role "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1" `
  --scope $storageId
```

## Step 6: Configure APIM Routing

Import OpenAPI:

```powershell
az apim api import `
  --resource-group rg-terprint-apim-dev `
  --service-name apim-terprint-dev `
  --api-id terprint-stock-api `
  --path /stock `
  --specification-format OpenApi `
  --specification-url "https://ca-terprint-stock.kindmoss-c6723cbe.eastus2.azurecontainerapps.io/openapi.json" `
  --display-name "Terprint AI Stock" `
  --protocols https `
  --subscription-required true
```

Set backend URL to:

- `https://ca-terprint-stock.kindmoss-c6723cbe.eastus2.azurecontainerapps.io`

## Step 7: Verify Health

```powershell
$fqdn = az containerapp show `
  --name ca-terprint-stock `
  --resource-group rg-dev-terprint-ca `
  --query properties.configuration.ingress.fqdn -o tsv

Invoke-RestMethod -Uri "https://$fqdn/health" | ConvertTo-Json
```

## Quick Links

- Repo: [https://github.com/Acidni-LLC/terprint-ai-stock](https://github.com/Acidni-LLC/terprint-ai-stock)
- Container App: [https://ca-terprint-stock.kindmoss-c6723cbe.eastus2.azurecontainerapps.io](https://ca-terprint-stock.kindmoss-c6723cbe.eastus2.azurecontainerapps.io)
- APIM Gateway: [https://apim-terprint-dev.azure-api.net/stock](https://apim-terprint-dev.azure-api.net/stock)
