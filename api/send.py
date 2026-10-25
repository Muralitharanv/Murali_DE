import hmac
import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class handler(BaseHTTPRequestHandler):
    def respond(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        secret = os.getenv("MURALI_API_KEY", "")
        slack_token = os.getenv("SLACK_BOT_TOKEN", "")
        expected_channel = os.getenv("SLACK_CHANNEL_ID", "C0CBWJGGQ3Y")
        authorization = self.headers.get("Authorization", "")
        if not secret or not slack_token:
            return self.respond(503, {"error": "Server not configured"})
        if not hmac.compare_digest(authorization, "Bearer " + secret):
            return self.respond(401, {"error": "Unauthorized"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 8192:
                return self.respond(413, {"error": "Invalid request size"})
            payload = json.loads(self.rfile.read(length))
            message = payload.get("message")
            if not isinstance(message, str) or not message.strip() or len(message) > 3000:
                return self.respond(400, {"error": "message must be 1-3000 characters"})
            body = json.dumps({
                "channel": expected_channel,
                "text": message,
                "unfurl_links": False,
                "unfurl_media": False,
            }).encode("utf-8")
            request = Request(
                "https://slack.com/api/chat.postMessage",
                data=body,
                headers={
                    "Authorization": "Bearer " + slack_token,
                    "Content-Type": "application/json; charset=utf-8",
                },
                method="POST",
            )
            with urlopen(request, timeout=10) as response:
                result = json.load(response)
            if not result.get("ok"):
                return self.respond(502, {"error": "Slack rejected message", "slack_error": result.get("error")})
            return self.respond(200, {"ok": True, "channel": result.get("channel"), "ts": result.get("ts")})
        except (ValueError, TypeError, json.JSONDecodeError):
            return self.respond(400, {"error": "Invalid JSON"})
        except (HTTPError, URLError, TimeoutError):
            return self.respond(502, {"error": "Slack request failed"})
