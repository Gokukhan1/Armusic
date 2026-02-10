import re
from pymongo import MongoClient
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated
from pyrogram.enums import ParseMode, ChatMemberStatus
from AviaxMusic import app, MONGO_DB_URI as mongo_url  # Assuming TEAMZYRO provides app and mongo_url
import logging

# Set up logging with console output for debugging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='bot.log'
)
logger = logging.getLogger(__name__)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Initialize MongoDB client
try:
    mongo_client = MongoClient(mongo_url)
    db = mongo_client["gamingwelcome"]
    welcome_settings_collection = db["welcome_settings"]
    rules_settings_collection = db["rules_settings"]
    welcome_settings_collection.create_index("chat_id")
    rules_settings_collection.create_index("chat_id")
except Exception as e:
    logger.error(f"Failed to connect to MongoDB: {e}")
    raise SystemExit("MongoDB connection failed. Check mongo_url and network.")

# Check if the user is an admin
async def is_admin(client: Client, chat_id: int, user_id: int) -> bool:
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception as e:
        logger.error(f"Error checking admin status for user {user_id} in chat {chat_id}: {e}")
        return False

# Parse buttons from message text
async def parse_buttons(text: str, chat_id: str = None) -> tuple:
    buttons = []
    current_row = []
    bot_username = None
    if chat_id:
        try:
            bot = await app.get_me()
            bot_username = f"{bot.username}" if bot.username else None
        except Exception as e:
            logger.error(f"Error getting bot username: {e}")
    
    # Updated regex to handle buttonurl:// and #RULES
    button_regex = r'\[([^\]]+)\]\(buttonurl:(?://)?([^\s)]+?)(?::same)?\)|\[([^\]]+)\]\(#RULES\)'
    
    matches = list(re.finditer(button_regex, text))
    cleaned_text = re.sub(button_regex, '', text).rstrip()
    
    logger.debug(f"Button matches: {matches}")
    for match in matches:
        if match.group(3):  # Rules button [name](#RULES)
            button_text = match.group(3)
            if not bot_username or not chat_id:
                logger.warning("Cannot create rules button: bot username or chat_id missing")
                continue
            url = f"https://t.me/{bot_username}?start=rules_{chat_id}"
            button = InlineKeyboardButton(button_text, url=url)
            logger.debug(f"Rules button: text={button_text}, url={url}")
        else:  # Regular button [name](buttonurl:...)
            button_text = match.group(1)
            url = match.group(2)
            same_row = ':same' in (match.group(0) or '')
            
            # Ensure proper URL format
            if not url.startswith(('http://', 'https://', 't.me/')):
                url = f'https://{url}'
            
            logger.debug(f"Processing button: text={button_text}, url={url}, same_row={same_row}")
            if url.startswith('#'):
                button = InlineKeyboardButton(button_text, callback_data=f"note_{url[1:]}")
            else:
                button = InlineKeyboardButton(button_text, url=url)
        
        if match.group(3) or (same_row and current_row):
            current_row.append(button)
        else:
            if current_row:
                buttons.append(current_row)
            current_row = [button]
    
    if current_row:
        buttons.append(current_row)
    
    keyboard = InlineKeyboardMarkup(buttons) if buttons else None
    logger.debug(f"Parsed buttons: {buttons}, cleaned_text: {cleaned_text}")
    return cleaned_text, keyboard

# Parse fillings and convert Markdown to HTML
async def parse_fillings(text: str, user, chat) -> tuple:
    options = {
        "disable_notification": False,
        "disable_web_page_preview": True,
        "protect_content": False,
        "preview_top": False
    }
    
    if "{nonotif}" in text:
        options["disable_notification"] = True
        text = text.replace("{nonotif}", "")
    if "{preview}" in text:
        options["disable_web_page_preview"] = False
        text = text.replace("{preview}", "")
    if "{preview:top}" in text:
        options["disable_web_page_preview"] = False
        options["preview_top"] = True
        text = text.replace("{preview:top}", "")
    if "{protect}" in text:
        options["protect_content"] = True
        text = text.replace("{protect}", "")
    
    fillings = {
        "{first}": user.first_name or "",
        "{last}": user.last_name or "",
        "{fullname}": f"{user.first_name} {user.last_name or ''}".strip(),
        "{username}": f"@{user.username}" if user.username else user.first_name,
        "{mention}": f"<a href='tg://user?id={user.id}'>{user.first_name}</a>",
        "{id}": str(user.id),
        "{chatname}": chat.title or "" if chat else "Unknown Chat",
        "{rules}": "",
        "{rules:same}": ""
    }
    
    def escape_html(text: str) -> str:
        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    
    rules_button = None
    rules_same = "{rules:same}" in text
    if "{rules}" in text or "{rules:same}" in text:
        rules_button = InlineKeyboardButton("Rules", callback_data=f"rules_{chat.id if chat else 'unknown'}")
        text = text.replace("{rules}", "").replace("{rules:same}", "")
    
    # Replace fillings while preserving newlines and formatting
    for key, value in fillings.items():
        text = text.replace(key, escape_html(value))
    
    # Convert Markdown to HTML
    # Bold: **text** -> <b>text</b>
    text = re.sub(r'\*(.*?)\*', r'<b>\1</b>', text)
    # Italic: __text__ -> <i>text</i>
    text = re.sub(r'__(.*?)__', r'<i>\1</i>', text)
    # Underline: --text-- -> <u>text</u>
    text = re.sub(r'--(.*?)--', r'<u>\1</u>', text)
    # Strikethrough: ~~text~~ -> <s>text</s>
    text = re.sub(r'~~(.*?)~~', r'<s>\1</s>', text)
    # Spoiler: ||text|| -> <span class="tg-spoiler">text</span>
    text = re.sub(r'\|\|(.*?)\|\|', r'<span class="tg-spoiler">\1</span>', text)
    # Inline code: `code` -> <code>code</code>
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    # URLs: [text](https://...) -> <a href="url">text</a>
    text = re.sub(r'\[([^\]]+)\]\((https?://[^\s)]+)\)', r'<a href="\2">\1</a>', text)
    # User mentions: [text](tg://user?id=...) -> <a href="tg://user?id=...">text</a>
    text = re.sub(r'\[([^\]]+)\]\(tg://user\?id=(\d+)\)', r'<a href="tg://user?id=\2">\1</a>', text)
    # Code blocks: ```language\ncode\n``` or ```\ncode\n``` -> <pre><code class="language-...">code</code></pre>
    text = re.sub(
        r'```(\w+)?\n(.*?)\n```',
        lambda m: f'<pre><code class="language-{m.group(1) or "none"}">{escape_html(m.group(2))}</code></pre>',
        text,
        flags=re.DOTALL
    )
    
    # Wrap text in <pre> to preserve exact formatting
    text = f"{text}"
    
    logger.debug(f"Final parsed text: {text}")
    return text, options, rules_button, rules_same

# Helper function to send welcome message
async def send_welcome_message(client: Client, chat_id: str, user, chat):
    try:
        chat_settings = welcome_settings_collection.find_one({"chat_id": chat_id})
        logger.debug(f"Settings for {chat_id}: {chat_settings}")
        if not chat_settings:
            welcome_settings_collection.insert_one({
                "chat_id": chat_id,
                "enabled": True,
                "delete_old": False,
                "message": "Hey there {first}, and welcome to {chatname}! How are you?"
            })
            logger.info(f"Initialized default settings for chat {chat_id}")
            return
        
        if not chat_settings.get("enabled", False):
            logger.info(f"Welcome messages disabled for chat {chat_id}")
            return
        
        welcome = chat_settings.get("message")
        if not welcome:
            logger.warning(f"No welcome message set for chat {chat_id}")
            return
        
        # Delete old message if enabled
        if chat_settings.get("delete_old", False):
            old_message_id = chat_settings.get("last_message_id")
            if old_message_id:
                try:
                    await client.delete_messages(chat_id, old_message_id)
                    logger.info(f"Deleted old welcome message {old_message_id} in chat {chat_id}")
                except Exception as e:
                    logger.error(f"Failed to delete old message {old_message_id}: {e}")
        
        logger.debug(f"Sending welcome for user {user.id} in chat {chat_id}")
        sent_message = None
        
        if isinstance(welcome, dict):
            if welcome["type"] == "sticker":
                sent_message = await client.send_sticker(chat_id, welcome["file_id"])
            elif welcome["type"] == "photo":
                caption = welcome.get("caption", "")
                logger.debug(f"Original photo caption: {caption}")
                
                # Parse buttons first
                caption, keyboard = await parse_buttons(caption, chat_id)
                logger.debug(f"Caption after button parsing: {caption}")
                
                # Parse fillings (replace placeholders and Markdown)
                caption, options, rules_button, rules_same = await parse_fillings(caption, user, chat)
                logger.debug(f"Caption after filling parsing: {caption}")
                
                # Handle buttons
                buttons = keyboard.inline_keyboard if keyboard else []
                if rules_button:
                    if rules_same and buttons:
                        buttons[-1].append(rules_button)
                    else:
                        buttons.append([rules_button])
                keyboard = InlineKeyboardMarkup(buttons) if buttons else None
                
                logger.debug(f"Final photo caption: {caption}, buttons: {buttons}")
                sent_message = await client.send_photo(
                    chat_id,
                    welcome["file_id"],
                    caption=caption,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML,
                    disable_notification=options["disable_notification"],
                    protect_content=options["protect_content"]
                )
            elif welcome["type"] == "animation":
                caption = welcome.get("caption", "")
                logger.debug(f"Original animation caption: {caption}")
                
                # Parse buttons first
                caption, keyboard = await parse_buttons(caption, chat_id)
                logger.debug(f"Caption after button parsing: {caption}")
                
                # Parse fillings (replace placeholders and Markdown)
                caption, options, rules_button, rules_same = await parse_fillings(caption, user, chat)
                logger.debug(f"Caption after filling parsing: {caption}")
                
                # Handle buttons
                buttons = keyboard.inline_keyboard if keyboard else []
                if rules_button:
                    if rules_same and buttons:
                        buttons[-1].append(rules_button)
                    else:
                        buttons.append([rules_button])
                keyboard = InlineKeyboardMarkup(buttons) if buttons else None
                
                logger.debug(f"Final animation caption: {caption}, buttons: {buttons}")
                sent_message = await client.send_animation(
                    chat_id,
                    welcome["file_id"],
                    caption=caption,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML,
                    disable_notification=options["disable_notification"],
                    protect_content=options["protect_content"]
                )
            else:
                logger.warning(f"Invalid welcome message type for chat {chat_id}: {welcome['type']}")
                return
        else:
            # Handle text message
            text, keyboard = await parse_buttons(welcome, chat_id)
            text, options, rules_button, rules_same = await parse_fillings(text, user, chat)
            buttons = keyboard.inline_keyboard if keyboard else []
            if rules_button:
                if rules_same and buttons:
                    buttons[-1].append(rules_button)
                else:
                    buttons.append([rules_button])
            keyboard = InlineKeyboardMarkup(buttons) if buttons else None
            logger.debug(f"Text message: {text}, buttons: {buttons}")
            sent_message = await client.send_message(
                chat_id,
                text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
                disable_notification=options["disable_notification"],
                disable_web_page_preview=options["disable_web_page_preview"],
                protect_content=options["protect_content"]
            )
        
        # Save message ID for deletion
        if chat_settings.get("delete_old", False) and sent_message and hasattr(sent_message, 'message_id'):
            welcome_settings_collection.update_one(
                {"chat_id": chat_id},
                {"$set": {"last_message_id": sent_message.message_id}}
            )
            logger.info(f"Saved new welcome message ID {sent_message.message_id} for chat {chat_id}")
            
    except Exception as e:
        logger.error(f"Error sending welcome message for user {user.id} in chat {chat_id}: {e}")
        try:
            await client.send_message(chat_id, f"Error sending welcome message: {str(e)}")
        except:
            pass

# Handler for new chat members using on_chat_member_updated
@app.on_chat_member_updated(filters.group)
async def welcome_new_member_updated(client: Client, update: ChatMemberUpdated):
    chat_id = str(update.chat.id)
    logger.debug(f"Chat member updated in chat {chat_id}, user: {update.new_chat_member.user.id if update.new_chat_member else 'None'}")
    
    try:
        if update.new_chat_member and update.old_chat_member is None:
            user = update.new_chat_member.user
            bot_id = (await client.get_me()).id
            bot_member = await client.get_chat_member(chat_id, bot_id)
            logger.debug(f"Bot status in chat {chat_id}: {bot_member.status}")
            if bot_member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
                logger.warning(f"Bot is not an admin in chat {chat_id}. Cannot send welcome messages.")
                return
            
            await send_welcome_message(client, chat_id, user, update.chat)
    except Exception as e:
        logger.error(f"Error in welcome_new_member_updated for chat {chat_id}: {e}")

# Handler for /setwelcome command
@app.on_message(filters.command("setwelcome") & filters.group, group=929292929)
async def set_welcome(client: Client, message: Message):
    chat_id = str(message.chat.id)
    user_id = message.from_user.id

    if not await is_admin(client, message.chat.id, user_id):
        await message.reply_text("Sorry, only admins can use this command.")
        return

    if not message.photo and not message.sticker and not message.animation and not message.reply_to_message and len(message.command) < 2:
        await message.reply_text("Please provide a welcome message, send a photo/sticker/animation with caption, or reply to a text, photo, sticker, or animation.")
        return

    try:
        message_data = None
        reply_text = "Welcome message updated."

        if message.photo:
            if len(message.command) > 1:
                caption_text = message.text[len("/setwelcome"):].strip()
            else:
                caption_text = ""
            
            message_data = {
                "type": "photo",
                "file_id": message.photo.file_id,
                "caption": caption_text
            }
            reply_text = "Welcome message set to this photo with caption."
            logger.debug(f"Photo welcome set with caption: {caption_text}")
            
        elif message.sticker:
            message_data = {
                "type": "sticker",
                "file_id": message.sticker.file_id
            }
            reply_text = "Welcome message set to this sticker."
            
        elif message.animation:
            if len(message.command) > 1:
                caption_text = message.text[len("/setwelcome"):].strip()
            else:
                caption_text = ""
            
            message_data = {
                "type": "animation",
                "file_id": message.animation.file_id,
                "caption": caption_text
            }
            reply_text = "Welcome message set to this animation with caption."
            logger.debug(f"Animation welcome set with caption: {caption_text}")
            
        elif message.reply_to_message:
            if message.reply_to_message.sticker:
                message_data = {
                    "type": "sticker",
                    "file_id": message.reply_to_message.sticker.file_id
                }
                reply_text = "Welcome message set to the replied sticker."
                
            elif message.reply_to_message.photo:
                if len(message.command) > 1:
                    caption = message.text[len("/setwelcome"):].strip()
                else:
                    caption = message.reply_to_message.caption or ""
                
                message_data = {
                    "type": "photo",
                    "file_id": message.reply_to_message.photo.file_id,
                    "caption": caption
                }
                reply_text = "Welcome message set to the replied photo with caption."
                logger.debug(f"Replied photo welcome set with caption: {caption}")
                
            elif message.reply_to_message.animation:
                if len(message.command) > 1:
                    caption = message.text[len("/setwelcome"):].strip()
                else:
                    caption = message.reply_to_message.caption or ""
                
                message_data = {
                    "type": "animation",
                    "file_id": message.reply_to_message.animation.file_id,
                    "caption": caption
                }
                reply_text = "Welcome message set to the replied animation with caption."
                logger.debug(f"Replied animation welcome set with caption: {caption}")
                
            elif message.reply_to_message.text:
                message_data = message.reply_to_message.text
                reply_text = "Welcome message set to the replied text."
            else:
                await message.reply_text("Unsupported message type. Reply to a text, photo, sticker, or animation.")
                return
        else:
            raw_message = message.text[len("/setwelcome"):].strip()
            message_data = raw_message
            reply_text = "Welcome message updated."

        # Save to database
        welcome_settings_collection.update_one(
            {"chat_id": chat_id},
            {"$set": {"message": message_data, "enabled": True, "delete_old": False}},
            upsert=True
        )
        
        logger.info(f"Welcome message saved for chat {chat_id}: {message_data}")
        await message.reply_text(reply_text)
        
    except Exception as e:
        logger.error(f"Error in set_welcome for chat {chat_id}: {e}")
        await message.reply_text(f"An error occurred while setting the welcome message: {str(e)}")



# Handler for /welcome command (on/off/deleteon/deleteoff)
@app.on_message(filters.command("welcome") & filters.group, group=929292929)
async def toggle_welcome(client: Client, message: Message):
    chat_id = str(message.chat.id)
    user_id = message.from_user.id

    if not await is_admin(client, message.chat.id, user_id):
        await message.reply_text("Sorry, only admins can use this command.")
        return

    try:
        if len(message.command) < 2:
            chat_settings = welcome_settings_collection.find_one({"chat_id": chat_id})
            if not chat_settings:
                welcome_settings_collection.insert_one({
                    "chat_id": chat_id,
                    "enabled": False,
                    "delete_old": False,
                    "message": "Hey there {first}, and welcome to {chatname}! How are you?"
                })
                chat_settings = welcome_settings_collection.find_one({"chat_id": chat_id})

            welcome = chat_settings.get("message", "Hey there {first}, and welcome to {chatname}! How are you?")
            enabled = chat_settings.get("enabled", False)
            delete_old = chat_settings.get("delete_old", False)
            
            status_text = (
                f"I am currently welcoming users: {enabled}\n"
                f"I am currently deleting old welcomes: {delete_old}\n\n"
                "Members are currently welcomed with:"
            )
            await message.reply_text(status_text)
            
            if isinstance(welcome, dict):
                if welcome["type"] == "sticker":
                    await client.send_sticker(message.chat.id, welcome["file_id"])
                elif welcome["type"] == "photo":
                    caption = welcome.get("caption", "")
                    parsed_caption, keyboard = await parse_buttons(caption, chat_id)
                    filled_caption, options, rules_button, rules_same = await parse_fillings(parsed_caption, message.from_user, message.chat)
                    
                    buttons = keyboard.inline_keyboard if keyboard else []
                    if rules_button:
                        if rules_same and buttons:
                            buttons[-1].append(rules_button)
                        else:
                            buttons.append([rules_button])
                    keyboard = InlineKeyboardMarkup(buttons) if buttons else None
                    
                    await client.send_photo(
                        message.chat.id,
                        welcome["file_id"],
                        caption=filled_caption,
                        reply_markup=keyboard,
                        parse_mode=ParseMode.HTML
                    )
                elif welcome["type"] == "animation":
                    caption = welcome.get("caption", "")
                    parsed_caption, keyboard = await parse_buttons(caption, chat_id)
                    filled_caption, options, rules_button, rules_same = await parse_fillings(parsed_caption, message.from_user, message.chat)
                    
                    buttons = keyboard.inline_keyboard if keyboard else []
                    if rules_button:
                        if rules_same and buttons:
                            buttons[-1].append(rules_button)
                        else:
                            buttons.append([rules_button])
                    keyboard = InlineKeyboardMarkup(buttons) if buttons else None
                    
                    await client.send_animation(
                        message.chat.id,
                        welcome["file_id"],
                        caption=filled_caption,
                        reply_markup=keyboard,
                        parse_mode=ParseMode.HTML
                    )
                else:
                    await message.reply_text("Invalid welcome message format in database.")
            else:
                parsed_text, keyboard = await parse_buttons(welcome, chat_id)
                filled_text, options, rules_button, rules_same = await parse_fillings(parsed_text, message.from_user, message.chat)
                
                buttons = keyboard.inline_keyboard if keyboard else []
                if rules_button:
                    if rules_same and buttons:
                        buttons[-1].append(rules_button)
                    else:
                        buttons.append([rules_button])
                keyboard = InlineKeyboardMarkup(buttons) if buttons else None
                
                await message.reply_text(
                    filled_text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=options["disable_web_page_preview"]
                )
            return

        action = message.command[1].lower()
        chat_settings = welcome_settings_collection.find_one({"chat_id": chat_id})
        if not chat_settings:
            welcome_settings_collection.insert_one({
                "chat_id": chat_id,
                "enabled": False,
                "delete_old": False,
                "message": "Hey there {first}, and welcome to {chatname}! How are you?"
            })

        if action == "on":
            welcome_settings_collection.update_one(
                {"chat_id": chat_id},
                {"$set": {"enabled": True}}
            )
            await message.reply_text("Welcome messages are now enabled.")
        elif action == "off":
            welcome_settings_collection.update_one(
                {"chat_id": chat_id},
                {"$set": {"enabled": False}}
            )
            await message.reply_text("Welcome messages are now disabled.")
        elif action == "deleteon":
            welcome_settings_collection.update_one(
                {"chat_id": chat_id},
                {"$set": {"delete_old": True}}
            )
            await message.reply_text("Deleting old welcome messages is now enabled.")
        elif action == "deleteoff":
            welcome_settings_collection.update_one(
                {"chat_id": chat_id},
                {"$set": {"delete_old": False}}
            )
            await message.reply_text("Deleting old welcome messages is now disabled.")
        else:
            await message.reply_text("Invalid argument. Use /welcome on, /welcome off, /welcome deleteon, or /welcome deleteoff")
    except Exception as e:
        logger.error(f"Error in toggle_welcome for chat {chat_id}: {e}")
        await message.reply_text(f"An error occurred while processing the command: {str(e)}")



