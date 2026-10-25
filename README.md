# Murali Assistant Slack bridge

A Vercel Python serverless backend for the **Murali Assistant** Slack bot.

It supports:

- Sending an explicitly approved message from ChatGPT to Slack.
- Receiving Slack `@Murali Assistant` mentions.
- Asking Murali for approval in a private Slack DM before generating an answer.
- Showing the generated draft to Murali for a second approval.
- Posting the final approved answer in the original Slack thread.

## Existing outbound endpoints

- MCP: `POST /api/mcp`
- Direct send: `POST /api/send`

These endpoints continue to use `SLACK_CHANNEL_ID` and do not change when the approval workflow is enabled.

## Two-stage approval endpoint

Slack events and interactive button payloads use:

```text
https://muralide.vercel.app/api/slack_events
```

Workflow:

1. Another Slack user mentions `@Murali Assistant` in the approved channel.
2. Murali receives a private DM asking whether the bot should prepare a response.
3. After Murali selects **Prepare response**, the backend calls the OpenAI Responses API.
4. Murali receives the full draft in the same private DM.
5. Only after Murali selects **Send** is the draft posted in the original Slack thread.

Messages from the owner are ignored by the incoming workflow. Rejecting either approval sends nothing.

## Vercel environment variables

Keep all values in Vercel; never commit them.

| Variable | Purpose |
| --- | --- |
| `SLACK_BOT_TOKEN` | Slack bot OAuth token |
| `SLACK_SIGNING_SECRET` | Verifies events and button actions came from Slack |
| `MURALI_API_KEY` | Authenticates MCP/direct-send requests and signs approval state |
| `SLACK_CHANNEL_ID` | Existing default channel used by `/api/send` and `/api/mcp` |
| `SLACK_APPROVAL_CHANNEL_ID` | Only channel whose mentions trigger approvals; use `C0CBTKDL04V` for `#murali-tasks` |
| `MURALI_USER_ID` | Slack owner allowed to approve; use `U0CBH66G947` |
| `OPENAI_API_KEY` | OpenAI API key used only after first approval |
| `OPENAI_MODEL` | Optional; defaults to `gpt-6-luna` |

ChatGPT subscriptions and OpenAI API billing are separate. The API key needs an API project with billing or available credits.

## Slack app configuration

In the Murali Assistant Slack app:

1. Add bot scopes: `app_mentions:read`, `chat:write`, and `im:write`.
2. Reinstall the app to the Slack workspace after changing scopes.
3. Under **Event Subscriptions**, enable events and set the Request URL to `https://muralide.vercel.app/api/slack_events`.
4. Subscribe to the bot event `app_mention`.
5. Under **Interactivity & Shortcuts**, enable interactivity and use the same Request URL.
6. Invite `@Murali Assistant` to `#murali-tasks`.

## Security

- Slack request signatures are verified and requests older than five minutes are rejected.
- Only `MURALI_USER_ID` can use approval buttons.
- Approval button state is HMAC-signed.
- The bot responds only in `SLACK_APPROVAL_CHANNEL_ID`.
- No response is posted without both approvals.
- Rotate any secret accidentally exposed in chats, screenshots, logs, or source control.
