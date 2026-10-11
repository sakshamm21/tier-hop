"""The shape of a multi-user bot: one conversation per user, replies sent from asyncio.

Discord, Telegram and Slack libraries all hand you a user id and a message inside an
async function. Replace the simulated messages at the bottom with your library's
message handler and call `reply_to()` from it.

    python examples/multi_user_bot.py
"""

import asyncio

from tierhop import Chat, ExhaustedError

SYSTEM = "You are a helpful assistant in a group chat. Keep answers under three sentences."

chats: dict[str, Chat] = {}


async def reply_to(user_id: str, text: str) -> str:
    if text == "/reset":
        chats.pop(user_id, None)
        return "Started a new conversation."
    chat = chats.setdefault(user_id, Chat(SYSTEM))
    try:
        # asend() runs the request in a worker thread, so other users are not kept waiting.
        return await chat.asend(text)
    except ExhaustedError as err:
        return f"I'm out of free quota. Try again in {err.retry_after:.0f} seconds."


async def main() -> None:
    incoming = [
        ("alice", "My favourite colour is green. Remember that."),
        ("bob", "Give me one tip for learning Python."),
        ("alice", "What is my favourite colour?"),
    ]
    # Alice's two messages run one after the other; Bob's runs alongside them.
    alice = [message for message in incoming if message[0] == "alice"]
    bob = [message for message in incoming if message[0] == "bob"]

    async def handle(messages):
        for user_id, text in messages:
            print(f"{user_id}> {text}\n  bot> {await reply_to(user_id, text)}\n")

    await asyncio.gather(handle(alice), handle(bob))


asyncio.run(main())
