Essential Credentials (Sandbox)
Auth URL: https://auth.truelayer.comData 
API URL: https://api.truelayer.com/data/v1Required 
Scopes: info, accounts, balance, transactions, offline_access (Critical for background sync).

The Auth Flow (OAuth2)

The AI agent needs to implement these two steps in your Python FastAPI backend:StepActionEndpoint

Create LinkGenerate a URL to send the user to their bank. GET /connect/auth2. 
Exchange CodeSwap the redirect code for an access_token.
POST /connect/tokenCode Exchange Payload 

(Example):JSON{
"grant_type": "authorization_code",
"client_id": "YOUR_CLIENT_ID",
"client_secret": "YOUR_CLIENT_SECRET",
"redirect_uri": "YOUR_REDIRECT_URI",
"code": "CODE_FROM_URL"
}

Data Retrieval Endpoints

Once you have the access_token, use these to pull data into your Supabase DB:

List Accounts: GET /accounts (Returns account_id, display_name, currency)

Get Balance: GET /accounts/{id}/balance (Returns current, available balances)

Get Transactions: GET /accounts/{id}/transactions (Returns amount, description, timestamp, transaction_id)


The UK "90-Day" Rule (Re-confirmation)

In the UK, you don't always need the user to re-log into their bank app every 90 days. You only need them to re-confirm consent within your app.

API Endpoint: POST /connections/extendLogic: If user_has_reconfirmed_consent: true is sent, TrueLayer attempts to refresh the link without a full login redirect.