import base64
import hashlib
import hmac
import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs
from urllib.request import Request, urlopen


MAX_BODY_BYTES = 256_000


def _env(name):
    return os.getenv(name, "").strip()


def _signing_secret():
    return _env("SLACK_SIGNING_SECRET")


def _state_secret():
    return _env("MURALI_API_KEY")


def _verify_slack_request(headers, raw_body):
    timestamp = headers.get("X-Slack-Request-Timestamp", "")
    signature = headers.get("X-Slack-Signature", "")
    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except (TypeError, ValueError):
        return False
    secret = _signing_secret()
    if not secret or not signature:
        return False
    base = b"v0:" + timestamp.encode("utf-8") + b":" + raw_body
    expected = "v0=" + hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _encode_state(data):
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    signature = hmac.new(_state_secret().encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload + signature).decode("ascii")


def _decode_state(value):
    try:
        decoded = base64.urlsafe_b64decode(value.encode("ascii"))
        payload, supplied = decoded[:-32], decoded[-32:]
        expected = hmac.new(_state_secret().encode("utf-8"), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(supplied, expected):
            return None
        return json.loads(payload)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def _post_json(url, payload, headers=None, timeout=25):
    request_headers = {"Content-Type": "application/json; charset=utf-8"}
    request_headers.update(headers or {})
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _slack_api(method, payload):
    token = _env("SLACK_BOT_TOKEN")
    if not token:
        raise RuntimeError("SLACK_BOT_TOKEN is missing")
    result = _post_json(
        "https://slack.com/api/" + method,
        payload,
        {"Authorization": "Bearer " + token},
        timeout=15,
    )
    if not result.get("ok"):
        raise RuntimeError("Slack " + method + " failed: " + str(result.get("error", "unknown_error")))
    return result


def _openai_draft(question):
    api_key = _env("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing")
    model = _env("OPENAI_MODEL") or "gpt-6-luna"
    payload = {
        "model": model,
        "instructions": (
            "You are Murali Assistant. Draft a clear, helpful Slack reply to the user's question. "
            "Use plain language, be concise, do not claim actions you did not perform, and do not "
            "mention this approval workflow. Return only the proposed reply text."
        ),
        "input": question,
        "max_output_tokens": 700,
        "store": False,
    }
    result = _post_json(
        "https://api.openai.com/v1/responses",
        payload,
        {"Authorization": "Bearer " + api_key},
        timeout=90,
    )
    if isinstance(result.get("output_text"), str) and result["output_text"].strip():
        return result["output_text"].strip()
    parts = []
    for item in result.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                parts.append(content["text"])
    draft = "\n".join(parts).strip()
    if not draft:
        raise RuntimeError("OpenAI returned no draft text")
    return draft


def _approval_blocks(requester, question, state):
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Approval 1 of 2*\n<@%s> asked Murali Assistant:\n\n>%s" % (
                    requester,
                    question.replace("\n", "\n>"),
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "style": "primary",
                    "text": {"type": "plain_text", "text": "Prepare response"},
                    "action_id": "prepare_response",
                    "value": _encode_state(state),
                },
                {
                    "type": "button",
                    "style": "danger",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "action_id": "reject_request",
                    "value": _encode_state(state),
                },
            ],
        },
    ]


def _draft_blocks(draft, state):
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Approval 2 of 2 — review this draft:*\n\n" + draft},
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "style": "primary",
                    "text": {"type": "plain_text", "text": "Send"},
                    "action_id": "send_response",
                    "value": _encode_state(state),
                },
                {
                    "type": "button",
                    "style": "danger",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "action_id": "reject_draft",
                    "value": _encode_state(state),
                },
            ],
        },
    ]


def _extract_after(text, marker):
    if marker not in text:
        return ""
    return text.split(marker, 1)[1].strip()


class handler(BaseHTTPRequestHandler):
    def respond(self, status, payload=None):
        data = b"" if payload is None else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    def do_GET(self):
        self.respond(200, {"ok": True, "service": "murali-assistant-slack-events"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.respond(400, {"error": "Invalid content length"})
        if length < 1 or length > MAX_BODY_BYTES:
            return self.respond(413, {"error": "Invalid request size"})
        raw_body = self.rfile.read(length)
        if not _verify_slack_request(self.headers, raw_body):
            return self.respond(401, {"error": "Invalid Slack signature"})

        content_type = self.headers.get("Content-Type", "")
        try:
            if content_type.startswith("application/x-www-form-urlencoded"):
                form = parse_qs(raw_body.decode("utf-8"))
                payload = json.loads(form.get("payload", [""])[0])
                self.respond(200, {})
                return self._handle_interaction(payload)
            payload = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
            return self.respond(400, {"error": "Invalid payload"})

        if payload.get("type") == "url_verification":
            return self.respond(200, {"challenge": payload.get("challenge", "")})
        if payload.get("type") != "event_callback":
            return self.respond(200, {"ok": True})

        self.respond(200, {"ok": True})
        try:
            self._handle_event(payload.get("event") or {})
        except Exception as exc:
            print("event handling failed:", type(exc).__name__, str(exc))

    def _handle_event(self, event):
        if event.get("type") != "app_mention" or event.get("bot_id"):
            return
        allowed_channel = _env("SLACK_APPROVAL_CHANNEL_ID")
        if allowed_channel and event.get("channel") != allowed_channel:
            return
        owner = _env("MURALI_USER_ID")
        requester = event.get("user", "")
        if not owner or not requester or requester == owner:
            return
        question = re.sub(r"<@[A-Z0-9]+>", "", event.get("text", "")).strip()
        if not question:
            return
        source_ts = event.get("thread_ts") or event.get("ts")
        state = {
            "channel": event.get("channel"),
            "thread_ts": source_ts,
            "requester": requester,
        }
        dm = _slack_api("conversations.open", {"users": owner})
        _slack_api(
            "chat.postMessage",
            {
                "channel": dm["channel"]["id"],
                "text": "Approval 1 of 2\nQuestion:\n" + question,
                "blocks": _approval_blocks(requester, question, state),
                "unfurl_links": False,
                "unfurl_media": False,
            },
        )

    def _handle_interaction(self, payload):
        owner = _env("MURALI_USER_ID")
        actor = (payload.get("user") or {}).get("id")
        if not owner or actor != owner:
            return
        actions = payload.get("actions") or []
        if not actions:
            return
        action = actions[0]
        state = _decode_state(action.get("value", ""))
        if not state:
            return
        action_id = action.get("action_id")
        container = payload.get("container") or {}
        dm_channel = container.get("channel_id") or (payload.get("channel") or {}).get("id")
        message_ts = container.get("message_ts") or (payload.get("message") or {}).get("ts")

        if action_id in ("reject_request", "reject_draft"):
            _slack_api(
                "chat.update",
                {"channel": dm_channel, "ts": message_ts, "text": "Rejected by Murali. Nothing was sent."},
            )
            return

        if action_id == "prepare_response":
            question = _extract_after((payload.get("message") or {}).get("text", ""), "Question:\n")
            _slack_api(
                "chat.update",
                {"channel": dm_channel, "ts": message_ts, "text": "Preparing a response draft…"},
            )
            try:
                draft = _openai_draft(question)
                _slack_api(
                    "chat.update",
                    {
                        "channel": dm_channel,
                        "ts": message_ts,
                        "text": "Draft:\n" + draft,
                        "blocks": _draft_blocks(draft, state),
                    },
                )
            except Exception as exc:
                _slack_api(
                    "chat.update",
                    {
                        "channel": dm_channel,
                        "ts": message_ts,
                        "text": "Could not prepare the draft: " + str(exc),
                    },
                )
            return

        if action_id == "send_response":
            draft = _extract_after((payload.get("message") or {}).get("text", ""), "Draft:\n")
            if not draft:
                return
            sent = _slack_api(
                "chat.postMessage",
                {
                    "channel": state["channel"],
                    "thread_ts": state["thread_ts"],
                    "text": draft,
                    "unfurl_links": False,
                    "unfurl_media": False,
                },
            )
            _slack_api(
                "chat.update",
                {
                    "channel": dm_channel,
                    "ts": message_ts,
                    "text": "Sent to Slack successfully (message %s)." % sent.get("ts", ""),
                },
            )

