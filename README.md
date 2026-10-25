# Murali Assistant Slack bridge

A minimal Vercel Python serverless endpoint that sends messages as the installed **Murali Assistant** Slack bot.

## Deployment
1. Import this repository into Vercel. Framework preset: Other. Root directory: `./`.
2. Add the following **Vercel Environment Variables** (never commit their values):
   - `SLACK_BOT_TOKEN`: Slack bot OAuth token with `chat:write` scope.
   - `MURALI_API_KEY`: a long, random secret used to authenticate requests.
   - `SLACK_CHANNEL_ID`: `C0CBWJGGQ3Y` (the `#general` channel).
3. Deploy. The POST endpoint is `https://YOUR-DEPLOYMENT.vercel.app/api/send`.

## API
Send POST JSON `{"message":"Hello from Murali Assistant"}` with the header `Authorization: Bearer YOUR_MURALI_API_KEY`.

**Security:** This endpoint requires a separate secret and sends only to the configured channel. Do not share tokens in chats, screenshots, GitHub files, or URLs. Rotate any accidentally exposed token.

**Important:** Deploying this bridge does **not** automatically give ChatGPT access to it. A separate authenticated ChatGPT-compatible custom integration is required before ChatGPT can invoke it directly.
