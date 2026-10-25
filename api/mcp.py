import hmac
import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROTOCOL_VERSION = "2025-03-26"


class handler(BaseHTTPRequestHandler):
    def respond(self, status, payload=None):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        if payload is None:
            self.end_headers()
            return
        data = json.dumps(payload).encode("utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        expected = os.getenv("MURALI_API_KEY", "")
        supplied = self.headers.get("Authorization", "")
        return bool(expected) and hmac.compare_digest(supplied, "Bearer " + expected)

    def do_GET(self):
        self.respond(405, {"error": "Use POST for MCP requests"})

    def do_POST(self):
        if not self.authorized():
            return self.respond(401, {"error": "Unauthorized"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 16384:
                return self.respond(413, {"error": "Invalid request size"})
            req = json.loads(self.rfile.read(length))
        except (ValueError, TypeError, json.JSONDecodeError):
            return self.respond(400, {"error": "Invalid JSON"})

        method = req.get("method")
        request_id = req.get("id")
        if method == "notifications/initialized" or method == "notifications/cancelled":
            return self.respond(202)
        if method == "initialize":
            result = {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "murali-assistant", "version": "1.0.0"}
            }
            return self.respond(200, {"jsonrpc": "2.0", "id": request_id, "result": result})
        if method == "ping":
            return self.respond(200, {"jsonrpc": "2.0", "id": request_id, "result": {}})
        if method == "tools/list":
            result = {"tools": [{
                "name": "send_slack_message",
                "description": "Send a message to the configured Slack channel as the Murali Assistant Slack bot. Use only when the user explicitly asks to send a Slack message.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"message": {"type": "string", "minLength": 1, "maxLength": 3000}},
                    "required": ["message"],
                    "additionalProperties": False
                }
            }]}
            return self.respond(200, {"jsonrpc": "2.0", "id": request_id, "result": result})
        if method == "tools/call":
            params = req.get("params") or {}
            if params.get("name") != "send_slack_message":
                return self.respond(200, {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Unknown tool"}})
            args = params.get("arguments") or {}
            message = args.get("message")
            if not isinstance(message, str) or not message.strip() or len(message) > 3000:
                return self.respond(200, {"jsonrpc": "2.0", "id": request_id, "result": {"isError": True, "content": [{"type": "text", "text": "message must be 1-3000 characters"}]}})
            token = os.getenv("SLACK_BOT_TOKEN", "")
            channel = os.getenv("SLACK_CHANNEL_ID", "")
            if not token or not channel:
                return self.respond(200, {"jsonrpc": "2.0", "id": request_id, "result": {"isError": True, "content": [{"type": "text", "text": "Slack integration is not configured"}]}})
            body = json.dumps({"channel": channel, "text": message, "unfurl_links": False, "unfurl_media": False}).encode("utf-8")
            request = Request("https://slack.com/api/chat.postMessage", data=body, headers={"Authorization": "Bearer " + token, "Content-Type": "application/json; charset=utf-8"}, method="POST")
            try:
                with urlopen(request, timeout=10) as response:
                    slack_result = json.load(response)
            except (HTTPError, URLError, TimeoutError):
                return self.respond(200, {"jsonrpc": "2.0", "id": request_id, "result": {"isError": True, "content": [{"type": "text", "text": "Slack request failed"}]}})
            if not slack_result.get("ok"):
                error = str(slack_result.get("error", "unknown_error"))
                return self.respond(200, {"jsonrpc": "2.0", "id": request_id, "result": {"isError": True, "content": [{"type": "text", "text": "Slack rejected message: " + error}]}})
            return self.respond(200, {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": "Message sent successfully as Murali Assistant."}]}})
        return self.respond(200, {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}})
