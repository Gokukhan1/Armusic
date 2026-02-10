from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import motor.motor_asyncio
from AviaxMusic import app, db, rules_collection
from config import MONGO_DB_URI as MONGO_URI




bot_username = "Oneforall_robot"  # Apne bot ka username (without @)



@app.on_message(filters.command("setrules") & filters.group)
async def set_rules(client, message):
    if len(message.command) < 2:
        return await message.reply("Usage: /setrules Your rules here")

    rules_text = message.text.split(None, 1)[1]
    await rules_collection.update_one(
        {"chat_id": message.chat.id},
        {"$set": {"rules": rules_text}},
        upsert=True
    )
    await message.reply("Rules have been saved.")


@app.on_message(filters.command("rules") & filters.group)
async def rules_button(client, message):
    chat_id = message.chat.id
    url = f"https://t.me/{app.username}?start=rules_{chat_id}"
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Check Rules", url=url)]]
    )
    await message.reply("Click the button below to check the group rules:", reply_markup=keyboard)
