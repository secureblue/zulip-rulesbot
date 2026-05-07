import time
from typing import Any, Final
from workers import WorkerEntrypoint, Request, Response
import json

from zulip import Client
from zulip_bots.lib import AbstractBotHandler, ExternalBotHandler

AGREEMENT_STATUS_STRING: Final[str] = "AGREED"
MEMBER_GROUP: Final[int] = 1522351

class RulesHandler:
    def handle_message(self, message: dict[str, Any], bot_handler: AbstractBotHandler, client: Client) -> None:
        content = message["content"].removeprefix("@**RulesBot**").strip()
        if content != "I agree to the rules":
            content = "Not a valid command. Send \"I agree to the rules\" to be granted server access."
            bot_handler.send_reply(message, content)
            bot_handler.react(message, "interrobang")
            return

        sender_email = message['sender_email']
        sender_user = client.call_endpoint(
            url=f"/users/{sender_email}",
            method="GET",
        )
        sender_user_id = sender_user["user"]["user_id"]
        sender_user_fullname = sender_user["user"]["full_name"]
        try:
            current_agreement_status = bot_handler.storage.get(str(sender_user_id))
        except KeyError:
            current_agreement_status = None
        if current_agreement_status == AGREEMENT_STATUS_STRING:
            content = "You have already agreed to the rules."
            bot_handler.send_reply(message, content)
            bot_handler.react(message, "check")
            return

        onboard_user_request_params = {
            "add": [sender_user_id]
        }
        onboard_user_response = client.update_user_group_members(MEMBER_GROUP, onboard_user_request_params)
        bot_handler.react(message, "check")
        content = "You have been granted server access."
        if onboard_user_response["result"] != "success":
            onboard_response_error = onboard_user_response["msg"]          
            client.send_message(dict(
                type='stream',
                to="modlog",
                subject="Errors",
                content=onboard_response_error,
            ))
            raise Exception(onboard_user_response["msg"])
        
        bot_handler.storage.put(str(sender_user_id), AGREEMENT_STATUS_STRING)
        onboarding_log_message = f"User @**{sender_user_fullname}|{sender_user_id}** has agreed to the rules."
        client.send_message(dict(
            type='stream',
            to="modlog",
            subject="Onboarding",
            content=onboarding_log_message,
        ))

class Default(WorkerEntrypoint):
    def _get_client(self):
        return Client(
            email=self.env.ZULIP_EMAIL,
            api_key=self.env.ZULIP_API_KEY,
            site=self.env.ZULIP_SITE
        )

    async def fetch(self, request: Request) -> Response:
        client = self._get_client()
        bot_handler = ExternalBotHandler(
            client=client,
            root_dir=None,
            bot_details={"name": "RulesBot"}
        )

        try:
            payload: dict[str, Any] | None = await request.json()
            if not payload:
                return Response.json({"error": "Missing request content"}, status=400)
            message: dict[str, Any] = payload.get("message")
            if not message:
                return Response.json({"error": "Missing 'message' in request"}, status=400)
            handler = RulesHandler()
            handler.handle_message(message, bot_handler, client)
            return Response(json.dumps({"result": "success"}), status=200)

        except Exception as e:
            return Response(json.dumps({"error": str(e)}), status=500)