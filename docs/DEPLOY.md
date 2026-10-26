# Deploying Seize the game to Azure

The app and its image are now named Seize the game and `seize-the-game-api`. Existing Azure resources and the GitHub repository still use their original identifiers below. Keep those identifiers when updating this deployment; the workflow publishes the renamed image to the existing registry and points the existing Container App at it.

Written 23 Oct 2026. Step 8 in [HANDOFF.md](HANDOFF.md); how it is built and why is in [DESIGN.md, Deployment](DESIGN.md#deployment-azure). The goal: a public link judges can open, kept up until **10 Nov 2026**.

**Scope (agreed 23 Oct):** replay only. The deployed app replays the stored samples, commentary and translations and makes **no GPT-4o calls**, so it needs no Foundry, Content Safety or Translator key. Live simulation comes later, with limits. Viewer profiles go in Cosmos DB (first thing to drop if time runs short: profiles already work in the browser).

```
browser ──► Static Web Apps (Free)  ──► the app, built with VITE_API_BASE
   └──► Container Apps (consumption) ──► image from Container Registry (Basic)
            ├─ identity ─► Key Vault: the Application Insights connection string
            ├─ identity ─► Cosmos DB (free tier): viewer profiles
            └─ telemetry ─► Application Insights (the one you already have)
GitHub Actions ─(OpenID Connect, no secret)─► ACR + Container App; Static Web Apps' own deploy for the app
```

**Rules for this whole guide:** never paste a key, connection string or token into a chat, an issue or a commit; enter each one yourself, in the portal or GitHub. Only names and addresses are ever shared. All resources go in the existing resource group **`rg-pitch-insights`**, region **East US 2**. The portal moves its buttons around now and then, so the labels below may differ a little; the settings matter more than where they are.

## What you'll create

Pick a short unique suffix once (for example your initials and two digits: `au26`). Wherever you see `<sfx>`, use it. Names marked "globally unique" must not exist anywhere in Azure.

| Resource | Name | Notes |
|---|---|---|
| Managed identity (the app's) | `id-pitch-insights-app` | pulls the image, reads Key Vault, uses Cosmos DB |
| Managed identity (GitHub's) | `id-pitch-insights-deploy` | holds the federated credential |
| Container Registry | `acrpitchinsights<sfx>` | globally unique, letters and digits only; SKU **Basic** (about US$5 a month: the only fixed cost) |
| Key Vault | `kv-pitchinsights-<sfx>` | globally unique, 3–24 characters; **Azure role-based access control** |
| Cosmos DB account | `cosmos-pitchinsights-<sfx>` | globally unique; API **NoSQL**; **free tier applied** |
| Cosmos DB database, container | `pitch-insights`, `profiles` | partition key `/id`, 400 RU/s, time to live on |
| Container Apps environment | `cae-pitch-insights` | Consumption only; makes a Log Analytics workspace `log-pitch-insights` |
| Container App | `ca-pitch-insights-api` | 0.5 vCPU, 1 GiB, 1 to 3 replicas, port 8000 |
| Static Web App | `swa-pitch-insights` | **Free** plan, deployment source **Other** |

**GitHub Actions secrets** (repo Settings → Secrets and variables → Actions → *Secrets*): `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_STATIC_WEB_APPS_API_TOKEN`.
**Variables** (same page → *Variables*): `ACR_NAME`, `RESOURCE_GROUP`, `CONTAINER_APP_NAME`, `API_BASE`.
You'll add them as you go; each stage says which.

---

## Stage 1: identities, registry

1. **Managed identities.** Portal → search **Managed Identities** → **Create**. Subscription: yours. Resource group `rg-pitch-insights`, Region **East US 2**, Name `id-pitch-insights-app` → **Review + create** → **Create**. Repeat with `id-pitch-insights-deploy`.
2. **Container Registry.** Search **Container registries** → **Create**. Resource group `rg-pitch-insights`, Registry name `acrpitchinsights<sfx>`, Location **East US 2**, Pricing plan **Basic**. Leave **Domain name label scope** at its default, and everything else, then **Create**. (The admin user stays off; nothing uses a registry password.)
3. **Let the identities use it.** Open the registry → **Access control (IAM)** → **Add** → **Add role assignment**:
   - Role **AcrPull** → Next → Assign access to **Managed identity** → **Select members** → `id-pitch-insights-app` → Review + assign.
   - Again with role **AcrPush** → `id-pitch-insights-deploy`.

**Check:** IAM → **Role assignments** shows both.

## Stage 2: GitHub signs in to Azure (OpenID Connect)

No secret is stored: GitHub gives each workflow run a short-lived token, and Azure accepts it only for this repository and branch.

1. **Federated credential.** Open `id-pitch-insights-deploy` → **Settings** → **Federated credentials** → **Add credential**. Scenario **GitHub Actions deploying Azure resources**. Organization `ILikePotatoesALot`, Repository `pitch-insights`, Entity **Branch**, Branch `main`, Name `github-main` → **Add**. (The subject it makes is `repo:ILikePotatoesALot/pitch-insights:ref:refs/heads/main`; the repository can stay private.)
2. **What it may do.** Open the resource group `rg-pitch-insights` → **Access control (IAM)** → Add role assignment → role **Contributor** → Managed identity → `id-pitch-insights-deploy`. (It needs to change the Container App; the registry push right is the AcrPush from Stage 1.)
3. **Three IDs for GitHub.** Open `id-pitch-insights-deploy` → **Overview**: copy **Client ID**. The **Subscription ID** is on the Overview of your subscription; the **Tenant ID** is on Microsoft Entra ID → Overview. They're identifiers, not passwords, but enter them yourself as repository **secrets**: `AZURE_CLIENT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_TENANT_ID`.
4. **Variables:** `ACR_NAME` = the registry's name (just the name, no `.azurecr.io`), `RESOURCE_GROUP` = `rg-pitch-insights`. Leave `CONTAINER_APP_NAME` unset for now: until it exists the workflow only builds the image and fills the registry.

> **Testing from a branch:** the workflows trigger on `main` only. To try a change before merging it, once the workflow is on `main` use **Actions → Deploy backend → Run workflow** and pick the branch; that needs a second federated credential (Entity **Branch**, that branch's name) on `id-pitch-insights-deploy`, which should be deleted afterwards. The bring-up credential `github-deploy-branch` (branch `claude/deploy-bec969`) is no longer needed: delete it. The frontend workflow stays on `main` only, because a branch deployment would go to a separate preview address that the server doesn't allow.

**Check (after the code is pushed):** Actions → **Deploy backend** → the run is green, and the registry's **Repositories** shows `seize-the-game-api` with a tag. If **Test the server** or **Build the image** fails, nothing has reached Azure; if **azure/login** fails, the federated credential's branch or names don't match (the error prints the subject Azure received).

## Stage 3: Key Vault (one secret)

The deployed app makes no model calls, so the only secret is the Application Insights connection string.

1. **Key Vault.** Search **Key vaults** → **Create**. Resource group `rg-pitch-insights`, Name `kv-pitchinsights-<sfx>`, Region **East US 2**, Pricing tier **Standard**. **Access configuration** tab: **Azure role-based access control**. Networking: public access on (default). Create.
2. **Let yourself write secrets** (Owner is not enough under role-based access: it manages the vault, not its contents). Vault → **Access control (IAM)** → Add role assignment → **Key Vault Secrets Officer** → User → you.
3. **Let the app read.** Add role assignment → **Key Vault Secrets User** → Managed identity → `id-pitch-insights-app`.
4. **The secret.** Open your Application Insights resource → **Overview** → copy **Connection String** (the long `InstrumentationKey=...` text). In the vault: **Objects** → **Secrets** → **Generate/Import**: Name `appinsights-connection-string`, Secret value: paste → **Create**.

**Check:** the vault lists `appinsights-connection-string` as Enabled. Never paste the value anywhere else.

## Stage 4: Cosmos DB (free tier)

Only one free-tier account is allowed per subscription, and **it can only be chosen while creating the account**; it can't be switched on later.

1. Search **Azure Cosmos DB** → **Create** → **Azure Cosmos DB for NoSQL** → **Create**.
2. Resource group `rg-pitch-insights`, Account name `cosmos-pitchinsights-<sfx>`, Location **East US 2**, Capacity mode **Provisioned throughput**, **Apply Free Tier Discount: Apply** (if the box is greyed out or says another account has it, this subscription already has a free-tier account: delete that one or skip Cosmos DB, the app works without it), Limit total account throughput: leave on. Leave Availability Zones off.
3. Next tabs: Global distribution (geo-redundancy off, multi-region writes off), Networking (**All networks** is fine: the app reaches it from Container Apps; access is by identity only), Backup policy (**Periodic**, default), Encryption (default). Review + create → Create (about 5 minutes).
4. **Database, container, access, keys off: one Cloud Shell block.** Portal top bar → the **Cloud Shell** icon → **Bash** (choose "No storage account required" if asked). Paste this, with your account name; it creates the database and the container (partition key `/id`, 400 RU/s, time to live on so each profile can expire), gives the app's identity the *Cosmos DB Built-in Data Contributor* role (data-plane roles can't be set in the portal) and turns off account keys, so only identities can use the account:

   ```bash
   RG=rg-pitch-insights
   COSMOS=cosmos-pitchinsights-<sfx>
   az cosmosdb sql database create -g $RG -a $COSMOS -n pitch-insights
   az cosmosdb sql container create -g $RG -a $COSMOS -d pitch-insights -n profiles \
     --partition-key-path /id --throughput 400 --ttl -1
   APP_ID=$(az identity show -g $RG -n id-pitch-insights-app --query principalId -o tsv)
   az cosmosdb sql role assignment create -g $RG -a $COSMOS \
     --role-definition-id 00000000-0000-0000-0000-000000000002 --principal-id $APP_ID --scope "/"
   az resource update --ids $(az cosmosdb show -g $RG -n $COSMOS --query id -o tsv) \
     --set properties.disableLocalAuth=true
   az cosmosdb sql role assignment list -g $RG -a $COSMOS -o table
   ```

   The last command should list one assignment. (If `--role-definition-id` complains, run `az cosmosdb sql role definition list -g $RG -a $COSMOS -o table`, find "Cosmos DB Built-in Data Contributor" and use its full id.)
5. Copy the account's **URI**: the Cosmos DB account → **Overview** → **URI** (`https://cosmos-pitchinsights-<sfx>.documents.azure.com:443/`). It's an address, not a secret; you'll use it as `COSMOS_ENDPOINT`.

**Check:** the account's Overview says **Free tier discount: Applied**. Data Explorer won't open for you while keys are off unless you also give yourself the data role; you don't need it.

## Stage 5: the Container App

Needs the image from Stage 2 in the registry.

1. Search **Container Apps** → **Create** → **Container App**.
   - **Basics:** Resource group `rg-pitch-insights`, Name `ca-pitch-insights-api`, **Deployment source: Container image**, Region **East US 2**. Container Apps environment → **Create new**: Name `cae-pitch-insights`, Environment type **Consumption only**; Monitoring: Log Analytics workspace **Create new** `log-pitch-insights`; networking: leave public. Create.
   - **Container:** untick **Use quickstart image**. Image source **Azure Container Registry**, Registry `acrpitchinsights<sfx>`, Image `seize-the-game-api`, Image tag `latest`. Authentication type **Managed identity** → Identity `id-pitch-insights-app`. (If this box isn't offered, finish creating with the quickstart image and set the registry afterwards under **Settings → Containers → Edit and deploy**.) CPU and memory **0.5 CPU cores, 1 Gi**.
     Environment variables (type the values; none is a secret): `AZURE_CLIENT_ID` = the **Client ID** of `id-pitch-insights-app` (its Overview), `COSMOS_ENDPOINT` = the Cosmos URI from Stage 4.
   - **Ingress:** Enabled; **Ingress traffic: Accepting traffic from anywhere**; Ingress type **HTTP**; Target port **8000**; Insecure connections **off**.
   - Create. When it's done, open the app → **Settings → Identity → User assigned** and confirm `id-pitch-insights-app` is attached (add it if not).
2. **Scale.** App → **Application → Scale** → Edit and deploy → Scale: Min replicas **1** (a warm replica, so the first judge doesn't wait for a start; set it to 0 if you want it free and can accept a slow first load), Max **3**. Leave the default HTTP scaling rule.
3. **The Key Vault reference.** App → **Security → Secrets** → **Add**: Key `appinsights-connection-string`, Type **Key Vault reference**, Key Vault secret URL: open the secret in Key Vault and copy its **Secret Identifier**, **without the version** (end the URL at `/secrets/appinsights-connection-string`, so a rotated value is picked up by itself), Identity **id-pitch-insights-app** → Add.
4. **Use it.** **Application → Containers → Edit and deploy** → click the container → **Environment variables** → Add: Name `APPLICATIONINSIGHTS_CONNECTION_STRING`, Source **Reference a secret**, Value `appinsights-connection-string` → Save → **Create** (a new revision).
5. **Tell GitHub.** The app's **Overview → Application Url** is `https://ca-pitch-insights-api.<something>.eastus2.azurecontainerapps.io`. Add repository **variables**: `CONTAINER_APP_NAME` = `ca-pitch-insights-api`, `API_BASE` = that Application Url (no trailing slash).
6. **Leave ingress CORS off** (Networking → CORS): the server answers cross-origin calls itself, only for the origins you list in Stage 6, and two layers would fight.

**Check:** `curl --ssl-no-revoke https://<Application Url>/api/matches` returns the three demo matches, and **Revision management** shows the revision **Running** (healthy). If it doesn't start: app → **Monitoring → Log stream**.

## Stage 6: the app on Static Web Apps

1. Search **Static Web Apps** → **Create**. Resource group `rg-pitch-insights`, Name `swa-pitch-insights`, Plan type **Free**, Region **East US 2**, **Deployment details → Source: Other** (choosing GitHub here would make Azure commit its own workflow file to the repository; our workflow does the job). Create.
2. **Deployment token.** Open it → **Overview** → **Manage deployment token** → copy. In GitHub add repository **secret** `AZURE_STATIC_WEB_APPS_API_TOKEN` (paste it yourself).
3. **Its address:** Overview → **URL**, `https://<name>.<n>.azurestaticapps.net`. **Allow it on the server:** Container App → **Application → Containers → Edit and deploy** → container → Environment variables → Add `PITCH_ALLOWED_ORIGINS` = that URL (no trailing slash; several origins are separated by commas) → Save → Create. (Localhost is always allowed, for development.)
4. Run **Deploy frontend** (Actions → Deploy frontend → Run workflow, once the code is on `main`; it also runs on every push that touches `frontend/`).

**Check:** the SWA URL opens the app, the matches list fills in, the browser's developer tools show the WebSocket to `wss://ca-pitch-insights-api...` connected.

## Stage 7: check the live link

Open the live link in a browser and check: a replay from kick-off and a seek; the language switch (Deutsch, 中文); the profile picker, saving a profile, reloading (and the Cosmos DB copy: delete the browser's copy and it comes back); `/?compare=1`; broadcast and fan overlays; a replay that runs longer than 4 minutes (the Container Apps ingress has a 240-second request timeout, so this checks a WebSocket survives it); and that Application Insights shows requests. To see a profile in the database itself, give yourself the data role (`az cosmosdb sql role assignment create ... --principal-id <your object id>`) and open **Data Explorer**.

---

## Deploying changes

Merging to `main` runs the workflows: backend changes (`backend/`, `samples/`, the Dockerfile) build and deploy the image; `frontend/` changes redeploy the app. Both can be run by hand from the Actions tab. Each image is tagged with its commit, so a bad deploy can be rolled back: Container App → **Revisions and replicas** → activate the earlier revision, or run `az containerapp update -n ca-pitch-insights-api -g rg-pitch-insights --image acrpitchinsights<sfx>.azurecr.io/seize-the-game-api:<commit>`.

When live simulation is added later: its keys go in Key Vault as new secrets (Stage 3), get a secret reference (Stage 5 step 3) and an environment variable (step 4); the app's identity already has the right to read them.

## Cost, and keeping it in budget

| Part | Cost |
|---|---|
| Container Registry Basic | about US$5 a month, billed daily (about US$0.17 a day). **The only fixed cost.** |
| Container Apps (consumption) | a monthly free grant per subscription of 180,000 vCPU-seconds, 360,000 GiB-seconds and 2 million requests. One warm 0.5 vCPU / 1 GiB replica uses about 1.3 million vCPU-seconds and 2.6 million GiB-seconds a month at the lower idle rate: roughly US$10 a month, so about US$6 from 24 Oct to 10 Nov. At 0 minimum replicas it's inside the free grant |
| Cosmos DB | free tier covers 1,000 RU/s and 25 GB; this uses 400 RU/s and a few KB |
| Static Web Apps | Free plan |
| Key Vault | cents (one secret, a few reads) |
| Application Insights, Log Analytics | free allowance of 5 GB a month each; a replay server logs very little |

The US$20 monthly budget alert on the subscription stays on. To keep the bill down: leave **Max replicas** at 3, don't turn on Dedicated plans, and if Azure Cost Analysis shows something unexpected, drop **Min replicas** to 0 first. Each push adds an image of about 150 MB to the registry (Basic holds 10 GB); old ones can be deleted from the registry's **Repositories** page.

## Tearing it down after 10 Nov

The resource group also holds things that are **not** part of the deployment (Foundry, Content Safety, Translator, Application Insights, the Azure ML workspace), so **don't delete the resource group**. Delete these, in this order, from the portal (each resource's **Delete** button):

1. Container App `ca-pitch-insights-api`, then the environment `cae-pitch-insights`, then the Log Analytics workspace `log-pitch-insights`.
2. Static Web App `swa-pitch-insights`.
3. Container Registry `acrpitchinsights<sfx>`: **this stops the fixed cost**. If you only want to stop spending quickly, delete this one first.
4. Cosmos DB account `cosmos-pitchinsights-<sfx>` (deleting it frees the subscription's one free-tier slot).
5. Key Vault `kv-pitchinsights-<sfx>`; it stays soft-deleted for 90 days and keeps its name: **Manage deleted vaults** → **Purge** if you need the name back.
6. Managed identities `id-pitch-insights-app` and `id-pitch-insights-deploy` (this also removes the federated credential).
7. GitHub: delete the repository secrets and variables listed at the top, and delete or disable `.github/workflows/deploy-backend.yml` and `deploy-frontend.yml` so a push doesn't try to deploy to nothing.

If the repository is still public and the link is gone, the README should say the demo was hosted until 10 Nov.
