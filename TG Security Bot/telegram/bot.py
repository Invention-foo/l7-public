from fastapi import APIRouter, Request, Response
from telegram import Update, ChatMember, ChatMemberUpdated
from telegram.ext import Application, CommandHandler, MessageHandler, ChatMemberHandler, TypeHandler, filters
from telegram.constants import ChatMemberStatus
from telegram.helpers import escape_markdown
from telegram.constants import UpdateType, ChatType
from telegram.error import TelegramError
from fuzzywuzzy import fuzz
import traceback
import requests
import re
import logging
import json

from app.telegram.api_rate_limiter import api_call
from app.services.database import get_project_details, remove_admin, remove_outdated_admins, check_twitter_handle, get_project_info, is_group_verified, get_verified_members, is_user_blacklisted, update_verified_group_id, is_user_verified, log_to_database, upsert_admin, get_chat_settings, get_chat_exceptions
from app.telegram.member_monitor import add_member_to_queue, continuous_member_check
from app.telegram.utils import ban_user, check_impersonation, check_spam, extract_message_content
from app.core.config import settings

router = APIRouter()
bot_app = None

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def start(update: Update, context):
    try:
        if update.effective_chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
            if not await is_group_verified(update.effective_chat.id):
                await leave_unverified_group(update.effective_chat)
                return
            await update.message.reply_text("Hello! I'm ready to assist this group.")
        else:
            await update.message.reply_text("Hello! I'm primarily designed to work in verified group chats. How can I assist you?")
    except Exception as e:
        error_message = f"Error in start command: {str(e)}"
        await log_to_database('error', 
                              update.effective_user.id if update and update.effective_user else None,
                              update.effective_chat.id if update and update.effective_chat else None,
                              error_message,
                              {
                                  'command': 'start',
                                  'error_type': type(e).__name__,
                                  'stack_trace': traceback.format_exc()
                              })
        logger.error(f"Error in start command: {str(e)}", exc_info=True)

async def help(update: Update, context):
    try:
        if update.effective_chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
            if not await is_group_verified(update.effective_chat.id):
                await leave_unverified_group(update.effective_chat)
                return
        await update.message.reply_text(
            "Welcome to Neoguard, an AI-powered moderation bot built to mitigate scams in the Web3 space. "
            "This service is in open beta. The following features are currently available: \n"
            " For verified projects: \n"
            "- Protection from impersonators joining the group. Impersonation accounts are automatically banned and added to a global blacklist.\n "
            "- Neoguard only joins groups registered by eligible $SMITH holders. The current eligibility criteria is 250000 $SMITH in your wallet.\n "
            "- [FUTURE] Scans all URLs sent in the chat for malicious activity. If a link is flagged as malicious, actions defined by the project owner will automatically trigger.\n"
            "- [FUTURE] Enhanced impersonator check by comparing profile pictures"
        )
    except Exception as e:
        error_message = f"Error in help command: {str(e)}"
        await log_to_database('error', 
                              update.effective_user.id if update and update.effective_user else None,
                              update.effective_chat.id if update and update.effective_chat else None,
                              error_message,
                              {
                                  'command': 'help',
                                  'error_type': type(e).__name__,
                                  'stack_trace': traceback.format_exc()
                              })
        logger.error(f"Error in help command: {str(e)}", exc_info=True)

async def autosetup(update: Update, context):
    """
    Fetches the group id, admin list and auto adds to database if it meets criteria
    """
    try:
        if update.effective_chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
            return
        
        chat_id = update.effective_chat.id
        if not await is_group_verified(chat_id):
            await leave_unverified_group(update.effective_chat)
            return
            
        sender = update.message.from_user
        admins = await context.bot.get_chat_administrators(chat_id)
        logger.error(admins)
        # TODO: this is inefficiently iterating twice. once here other after verification of command. fix later
        is_sender_admin = any(admin.user.id == sender.id for admin in admins)
        logger.error(is_sender_admin)

        verified_members = await get_verified_members(chat_id)
        if (not await is_user_verified(sender.id, verified_members) and sender.id != 1614115986) and not is_sender_admin:
            logger.info(f"Unauthorized autosetup attempt by user {sender.id}")
            return

        formatted_message = "🛡️ *Chat Administrators:* 🛡️\n\n"
        processed_admins = []
        skipped_admins = []
        current_admin_ids = set()

        for admin in admins:
            user_info = admin.user
            full_name = f"{user_info.first_name} {user_info.last_name or ''}".strip()
            current_admin_ids.add(str(user_info.id))

            # Only skip bots, no longer checking name length
            if user_info.is_bot:
                skipped_admins.append((full_name, "Bot"))
                continue

            admin_details = {
                'telegram_chat_id': str(chat_id),
                'telegram_id': str(user_info.id),
                'telegram_username': user_info.username,
                'telegram_full_name': full_name
            }

            result = await upsert_admin(admin_details)
            status = "Updated" if result and result.get('id') else "Added"
            processed_admins.append((full_name, status))

            admin_details = (
                f"👤 *User ID:* {user_info.id}\n"
                f"📛 *Username:* @{user_info.username or 'N/A'}\n"
                f"📝 *Name:* {full_name}\n"
                "----------------------------------------\n"
            )
            formatted_message += admin_details

        # Remove admins that are no longer in the group
        removed_admins = await remove_outdated_admins(chat_id, current_admin_ids)

        formatted_message += f"Group chat ID: {chat_id}\n\n"
        formatted_message += "Admin Update Results:\n"
        for admin, status in processed_admins:
            formatted_message += f"✅ {admin}: {status}\n"
        for admin, reason in skipped_admins:
            formatted_message += f"❌ {admin}: Skipped ({reason})\n"

        await update.message.reply_text(formatted_message)

    except Exception as e:
        error_message = f"Error in autosetup command: {str(e)}"
        await log_to_database('error', 
                              update.effective_user.id if update and update.effective_user else None,
                              update.effective_chat.id if update and update.effective_chat else None,
                              error_message,
                              {
                                  'command': 'autosetup',
                                  'error_type': type(e).__name__,
                                  'stack_trace': traceback.format_exc()
                              })
        logger.error(f"Error in autosetup command: {str(e)}", exc_info=True)

async def getinfo(update: Update, context):
    try:
        args = context.args
        if len(args) != 2:
            await update.message.reply_text("Usage: /getinfo <blockchain ticker> <contract_address>")
            return
        
        blockchain, contract_address = args
        project_info = await get_project_info(blockchain.upper(), contract_address.lower())

        if project_info:
            message = f"*{escape_markdown(project_info.get('name', ''), version=2)} \\- {escape_markdown(project_info.get('blockchain', ''), version=2)}*\n"
            message += "Verified Project ✅\n"
            message += f"Twitter: [{escape_markdown(project_info.get('twitter', ''), version=2)}]({escape_markdown(project_info.get('twitter', ''), version=2)})\n"
            message += f"Telegram: [{escape_markdown(project_info.get('telegram', ''), version=2)}]({escape_markdown(project_info.get('telegram', ''), version=2)})\n\n"
            message += "Registered Telegram admins:\n"
            for admin in project_info['admins']:
                full_name = escape_markdown(admin.get('telegram_full_name', ''), version=2)
                username = escape_markdown(admin.get('telegram_username') or '', version=2)
                formatted_username = f"@{username}" if username else 'Hidden'
                message += f"\\- {full_name} {formatted_username}\n"

            await update.message.reply_text(message, parse_mode='MarkdownV2', disable_web_page_preview=True)
        else:
            await update.message.reply_text(
                "No results found in our partner network\\. We are considering an integration with CoinGecko and CMC to pull publicly available information for non\\-partners\\. Stay tuned\\!",
                parse_mode='MarkdownV2'
            )

    except Exception as e:
        error_message = f"Error in getinfo command: {str(e)}"
        await log_to_database('error', 
                              update.effective_user.id if update and update.effective_user else None,
                              update.effective_chat.id if update and update.effective_chat else None,
                              error_message,
                              {
                                  'command': 'getinfo',
                                  'error_type': type(e).__name__,
                                  'stack_trace': traceback.format_exc()
                              })
        logger.error(f"Error in getinfo command: {str(e)}", exc_info=True)
        await update.message.reply_text("An error occurred while processing your request. Please try again later.")

async def verifytwt(update: Update, context):
    try:
        if not context.args:
            await update.message.reply_text("Usage: /verifytwt <tweet_url>")
            return
            
        tweet_url = context.args[0]
        logger.info(f"Received tweet URL: {tweet_url}")

        # Regular expression to match Twitter/X URLs and extract the username
        twitter_regex = r'(?:https?:\/\/)?(?:www\.)?(?:twitter\.com|x\.com)\/(\w+)'
        match = re.search(twitter_regex, tweet_url)

        if not match:
            await update.message.reply_text("Invalid Twitter/X URL\\. Please provide a valid tweet URL\\.", parse_mode='MarkdownV2')
            return
        
        username = match.group(1)
        project_info = await check_twitter_handle(username.lower())

        if project_info:
            message = (
                f"This is an official tweet from the main account of *{escape_markdown(project_info['name'], version=2)} \\- {escape_markdown(project_info['blockchain'], version=2)}*\\.\n"
                f"Verified Twitter account: [{escape_markdown(project_info['twitter'], version=2)}]"
                f"({escape_markdown(project_info['twitter'], version=2)})"
            )
            await update.message.reply_text(message, parse_mode='MarkdownV2', disable_web_page_preview=True)
        else:
            message = (
                "No matches found in our partner network\\. "
                "Please run the /getinfo command to verify if the project is in our partner network\\. "
                "If it is, then the tweet you shared is from an unofficial or fake account\\."
            )
            await update.message.reply_text(message, parse_mode='MarkdownV2')

    except Exception as e:
        error_message = f"Error in verifytwt command: {str(e)}"
        await log_to_database('error', 
                              update.effective_user.id if update and update.effective_user else None,
                              update.effective_chat.id if update and update.effective_chat else None,
                              error_message,
                              {
                                  'command': 'verifytwt',
                                  'error_type': type(e).__name__,
                                  'stack_trace': traceback.format_exc()
                              })
        logger.error(f"Error in verifytwt command: {str(e)}", exc_info=True)
        await update.message.reply_text("An error occurred while processing your request\\. Please try again later\\.", parse_mode='MarkdownV2')

async def handle_message(update: Update, context):
    logger.error(f"DEBUG: handle_message called")
    try:
        if update.message is None:
            logger.warning("Received an update with no message")
            return

        if update.effective_chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
            if not await is_group_verified(update.effective_chat.id):
                await leave_unverified_group(update.effective_chat)
                return
            
            chat_id = update.effective_chat.id
            chat_title = update.effective_chat.title

            sender = update.message.from_user
            sender_id = str(sender.id)
            sender_full_name = sender.full_name
            sender_username = sender.username
            
            # TODO: move to global scope later
            # System accounts to ignore
            WHITELISTED_ACCOUNTS = {"777000"}  # Telegram's official service account
            
            if sender_id in WHITELISTED_ACCOUNTS:
                return

            # Get chat settings and exceptions (convert chat_id to string for these functions)
            chat_settings = await get_chat_settings(str(chat_id))
            chat_exceptions = await get_chat_exceptions(str(chat_id))

            # TODO: make it a toggle in settings to delete forwarded stories
            if update.message.story:
                if update.message.chat.id != update.message.story.chat.id:
                    await update.message.delete()
                return

            # Extract message content using the utility function
            message_text, message_type = await extract_message_content(update.message)

            await log_to_database('message', sender_id, chat_id, 
                                f"Message received in group by {sender_full_name}", 
                                {'message_text': message_text, 'message_type': message_type})

            # Check if user is in exceptions list (convert sender_id to string for comparison)
            if any(exc.get('user_id') == sender_id for exc in chat_exceptions):
                logger.info(f"User {sender_id} is in exceptions list for chat {chat_id}")
                return
            
            verified_members = await get_verified_members(chat_id)

            if await is_user_verified(sender_id, verified_members):
                # Keep existing admin info update logic
                admin_info = next((member for member in verified_members if member['telegram_id'] == str(sender_id)), None)
                if admin_info and len(sender_full_name) > 5 and sender_full_name != admin_info['telegram_full_name']:
                    admin_details = {
                        'telegram_chat_id': str(chat_id),
                        'telegram_id': sender_id,
                        'telegram_username': sender_username,
                        'telegram_full_name': sender_full_name
                    }
                    await upsert_admin(admin_details)
                    logger.info(f"Updated admin information for user {sender_id} in chat {chat_id}")
                return

            # Check global blacklist only if enabled in settings
            if chat_settings['use_global_blacklist'] and await is_user_blacklisted(sender_id):
                await ban_user(update.effective_chat, sender_id, sender_full_name, "being on the global blacklist")
                await log_to_database('moderation', sender_id, chat_id, 
                                    f"Banned user {sender_full_name} for being on global blacklist", 
                                    {'action_type': 'ban', 'reason': 'global blacklist'})
                return

            # Keep existing impersonation check
            is_impersonator, is_blacklist = await check_impersonation(sender_full_name, sender_username, verified_members, chat_title)
            if is_impersonator:
                await handle_message_impersonation(update, context, is_blacklist)
                return
        
            # Get project details for spam check
            project_details = await get_project_details(chat_id)
            if not project_details:
                logger.error(f"Could not find project details for chat {chat_id}")
                return
            
            # spam detection if setting is enabled
            if chat_settings['use_spam_detection'] and message_text:
                # Check for spam
                is_spam_message, spam_score = await check_spam(message_text, False, project_details)
                logger.info(f"spam message: {is_spam_message} and score: {spam_score}")

                if is_spam_message:
                    logger.info(f"Spam detected with score {spam_score} in message: {message_text[:100]}...")
                    
                    if spam_score >= 90:  # High confidence spam
                        await update.message.delete()
                        await ban_user(update.effective_chat, sender.id, sender_full_name, "sending spam messages", True)
                        await log_to_database('moderation', sender.id, chat_id,
                                            f"Banned user {sender_full_name} for high-confidence spam",
                                            {'action_type': 'ban', 'reason': 'spam', 'spam_score': spam_score})
                    
                    elif spam_score >= 70:  # Moderate confidence spam
                        await update.message.delete()
                        await log_to_database('moderation', sender.id, chat_id,
                                            f"Deleted message from {sender_full_name} for moderate-confidence spam",
                                            {'action_type': 'delete', 'reason': 'spam', 'spam_score': spam_score})
                    
                    else:  # Low confidence spam
                        await log_to_database('moderation', sender.id, chat_id,
                                            f"Flagged potential spam from {sender_full_name}",
                                            {'action_type': 'flag', 'reason': 'potential_spam', 'spam_score': spam_score})
                    
            return
            
            # TODO: ------ URL SCANNER PORTION TBD FOR NOW -------
            # TODO: shortlinks will not be effective. have option to delete all messages with shortlinks
            # TODO: should consider scenarios where full url is not provided (eg. athena.foo instead of https://athena.foo)
            message_text = update.message.text
            urls = re.findall(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', message_text)
        
            if urls:
                await update.message.reply_text(f"The urls are: {urls}")
                for url in urls:
                    pass

        else:
            # private chat logic
            await update.message.reply_text("I'm primarily designed to protect verified group chats. Please type /help if you need to verify an account or person.")

    except Exception as e:
        error_message = f"Error in handle_message: {str(e)}"
        await log_to_database('error', 
                              update.effective_user.id if update and update.effective_user else None,
                              update.effective_chat.id if update and update.effective_chat else None,
                              error_message,
                              {
                                  'function': 'handle_message',
                                  'error_type': type(e).__name__,
                                  'stack_trace': traceback.format_exc()
                              })
        logger.error(f"Error in handle_message: {str(e)}", exc_info=True)

async def handle_admin_update(update: Update, context):
    try:
        chat_id = update.effective_chat.id
        if not await is_group_verified(chat_id):
            await leave_unverified_group(update.effective_chat)
            return
        
        # Ensure we're dealing with an admin status change
        if update.chat_member.old_chat_member.status != ChatMemberStatus.ADMINISTRATOR and \
           update.chat_member.new_chat_member.status != ChatMemberStatus.ADMINISTRATOR:
            return
        
        user = update.chat_member.new_chat_member.user
        full_name = f"{user.first_name} {user.last_name or ''}".strip()

        if update.chat_member.new_chat_member.status == ChatMemberStatus.ADMINISTRATOR:
            # Admin added
            if not user.is_bot:
                admin_details = {
                    'telegram_chat_id': str(chat_id),
                    'telegram_id': str(user.id),
                    'telegram_username': user.username,
                    'telegram_full_name': full_name
                }
                result = await upsert_admin(admin_details)
                logger.info(f"Admin added/updated: {full_name} (ID: {user.id}) in chat {chat_id}")
            else:
                logger.info(f"Skipped adding admin: {full_name} (ID: {user.id}) in chat {chat_id} - Bot or name too short")
        else:
            # Admin removed
            await remove_admin(chat_id, str(user.id))
            logger.info(f"Admin removed: {full_name} (ID: {user.id}) from chat {chat_id}")

    except Exception as e:
        error_message = f"Error in handle_admin_update: {str(e)}"
        await log_to_database('error', 
                              user.id if user else None,
                              chat_id,
                              error_message,
                              {
                                  'function': 'handle_admin_update',
                                  'error_type': type(e).__name__,
                                  'stack_trace': traceback.format_exc()
                              })
        logger.error(f"Error in handle_admin_update: {str(e)}", exc_info=True)


# TODO: option to just kick
# TODO: option to just mute
# TODO: option to warn chat without doing anything else
# TODO: the check should factor in that generic names are not allowed for verified team members. this should be team member add thing..
async def handle_new_members(update: Update, context):
    try:
        logger.debug("New member event received")

        if not await is_group_verified(update.effective_chat.id):
            await leave_unverified_group(update.effective_chat)
            return
        
        new_members = update.message.new_chat_members
        for new_member in new_members:
            processed_member = await process_new_member(update.effective_chat, new_member)
            if processed_member:
                await add_member_to_queue(
                    update.effective_chat.id, 
                    new_member.id, 
                    new_member.full_name, 
                    new_member.username, 
                )
    except Exception as e:
        error_message = f"Error in handle_new_members: {str(e)}"
        await log_to_database('error', 
                              None,
                              update.effective_chat.id if update and update.effective_chat else None,
                              error_message,
                              {
                                  'function': 'handle_new_members',
                                  'error_type': type(e).__name__,
                                  'stack_trace': traceback.format_exc()
                              })
        logger.error(f"Error in handle_new_members: {str(e)}", exc_info=True)

async def handle_bot_added(update: Update, context):
    """
    Automatically leaves a group if it's not in the verified list
    """
    try:
        if update.effective_chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
            if not await is_group_verified(update.effective_chat.id):
                await leave_unverified_group(update.effective_chat)
                await log_to_database('event', None, update.effective_chat.id, 
                                    "Bot left unverified group", 
                                    {'event_type': 'bot_left_unverified'})
            else:
                await log_to_database('event', None, update.effective_chat.id, 
                                    "Bot added to verified group", 
                                    {'event_type': 'bot_added_verified'})
    except Exception as e:
        error_message = f"Error in handle_bot_added: {str(e)}"
        await log_to_database('error', 
                              None,
                              update.effective_chat.id if update and update.effective_chat else None,
                              error_message,
                              {
                                  'function': 'handle_bot_added',
                                  'error_type': type(e).__name__,
                                  'stack_trace': traceback.format_exc()
                              })
        logger.error(f"Error in handle_bot_added: {str(e)}", exc_info=True)
    
# TODO: edge case where group upgraded to supergroup causes bot to leave
# async def handle_chat_member_update(update: Update, context):
#     """
#     Handles changes in chat member status, such as upgrading to a supergroup.
#     """
#     if update.chat_member.new_chat_member.status == ChatMember.MEMBER:
#         # Check if the group is upgraded to a supergroup
#         chat_id = update.effective_chat.id
#         if update.effective_chat.type == ChatType.GROUP and update.chat_member.new_chat_member.chat.type == ChatType.SUPERGROUP:
#             logger.info(f"Chat upgraded to supergroup: {chat_id}")

#             # Fetch the new group ID
#             new_chat_id = update.chat_member.new_chat_member.chat.id
#             logger.info(f"New supergroup ID: {new_chat_id}")

#             # Update your database with the new group ID
#             await update_verified_group_id(chat_id, new_chat_id)

async def leave_unverified_group(chat):
    try:
        await chat.leave()
        logger.warning(f"Bot left unverified group: {chat.id}")
    except Exception as e:
        logger.error(f"Error leaving unverified group {chat.id}: {str(e)}")

# TODO: option to add to the global blacklist or not
async def process_new_member(chat, new_member):
    user_id = new_member.id
    username = new_member.username
    display_name = new_member.full_name

    # Get the bot's user ID
    bot = chat.get_bot()
    bot_id = bot.id
    
    # Check if the new member is the bot itself
    if user_id == bot_id:
        logger.info(f"Bot {bot_id} was added to the group {chat.id}. Skipping self-ban check.")
        return False

    # Get chat settings and exceptions (convert chat.id to string for these functions)
    chat_settings = await get_chat_settings(str(chat.id))
    chat_exceptions = await get_chat_exceptions(str(chat.id))

    # Check if user is in exceptions list (convert user_id to string for comparison)
    if any(exc.get('user_id') == str(user_id) for exc in chat_exceptions):
        logger.info(f"User {user_id} is in exceptions list for chat {chat.id}")
        return False

    logger.info(f"New member joined: ID: {user_id}, Username: {username}, Full Name: {display_name}")
    await log_to_database('event', user_id, chat.id, 
                          f"New member joined: {display_name}", 
                          {'event_type': 'new_member_joined', 'username': username})

    # Check global blacklist only if enabled in settings
    if chat_settings['use_global_blacklist'] and await is_user_blacklisted(user_id):
        await ban_user(chat, user_id, display_name, "being on the global blacklist")
        await log_to_database('moderation', user_id, chat.id, 
                              f"Banned new member {display_name} for being on global blacklist", 
                              {'action_type': 'ban', 'reason': 'global blacklist'})
        return False
        
    verified_members = await get_verified_members(chat.id)

    if await is_user_verified(user_id, verified_members):
        return False

    is_impersonator, is_blacklist = await check_impersonation(display_name, username, verified_members, chat.title)
    if is_impersonator:
        await ban_user(chat, user_id, display_name, "impersonation of a team member", is_blacklist)
        await log_to_database('moderation', user_id, chat.id, 
                              f"Banned new member {display_name} for impersonation", 
                              {'action_type': 'ban', 'reason': 'impersonation'})
        return False
    
    return chat_settings['use_member_monitor']

async def handle_message_impersonation(update: Update, context, is_blacklist):
    # TODO: offer options on what to do 
    user = update.message.from_user
    chat = update.effective_chat

    await update.message.delete()
    await ban_user(chat, user.id, user.full_name, "impersonation of a team member", is_blacklist)
    await log_to_database('moderation', user.id, chat.id, 
                          f"Banned user {user.full_name} for impersonation in message", 
                          {'action_type': 'ban', 'reason': 'impersonation', 'message_deleted': True})


class RateLimitedBotProxy:
    def __init__(self, bot):
        self._bot = bot

    def __getattr__(self, name):
        attr = getattr(self._bot, name)
        if callable(attr):
            return lambda *args, **kwargs: api_call(self._bot, name, *args, **kwargs)
        return attr


async def setup_bot():
    global bot_app
    logger.info("Setting up bot")
    logger.info(f"WEBHOOK_URL: {settings.NEOGUARD_WEBHOOK_URL}")
    logger.info(f"WEBHOOK_PATH: {settings.NEOGUARD_WEBHOOK_PATH}")
    logger.info(f"REDIS_HOST: {settings.NEOGUARD_REDIS_HOST}")
    logger.info(f"REDIS_PORT: {settings.NEOGUARD_REDIS_PORT}")
    bot_app = Application.builder().token(settings.NEOGUARD_TELEGRAM_TOKEN).build()

    # Wrap the bot's API with our rate-limited api_call function
    bot_app.bot = RateLimitedBotProxy(bot_app.bot)

    bot_app.add_handler(CommandHandler('start', start))
    bot_app.add_handler(CommandHandler('help', help))
    bot_app.add_handler(CommandHandler('autosetup', autosetup))
    # bot_app.add_handler(CommandHandler('getinfo', getinfo))
    # bot_app.add_handler(CommandHandler('verifytwt', verifytwt))

    # Add the new admin update handler
    bot_app.add_handler(ChatMemberHandler(handle_admin_update, ChatMemberHandler.CHAT_MEMBER))

    # handles any messages in chats
    bot_app.add_handler(MessageHandler(
    (filters.TEXT | filters.CAPTION | filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.STORY) 
    & ~filters.COMMAND, 
    handle_message
))
    # handles scenario where bot is added to new group
    bot_app.add_handler(ChatMemberHandler(handle_bot_added, ChatMemberHandler.MY_CHAT_MEMBER))
    # TODO: handles scenario where group is upgraded to supergroup and bot needs to update id
    #bot_app.add_handler(ChatMemberHandler(handle_chat_member_update, ChatMemberHandler.CHAT_MEMBER))
    # handles scenario where a new member is joining
    bot_app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_new_members))

    bot_app.create_task(continuous_member_check(bot_app.bot))

    await bot_app.initialize()
    await bot_app.start()

    try:
        # Delete existing webhook
        await bot_app.bot.delete_webhook()
        logger.error("Existing webhook deleted")

        # Set new webhook
        allowed_updates = ['message', 'chat_member', 'my_chat_member']
        await bot_app.bot.set_webhook(url=settings.NEOGUARD_WEBHOOK_URL, allowed_updates=allowed_updates)
        logger.info(f"Webhook set to {settings.NEOGUARD_WEBHOOK_URL} with allowed_updates: {allowed_updates}")

        # Verify webhook
        webhook_info = await bot_app.bot.get_webhook_info()
        if webhook_info.url == settings.NEOGUARD_WEBHOOK_URL:
            logger.info("Webhook verified successfully")
        else:
            logger.error(f"Webhook verification failed. Current webhook URL: {webhook_info.url}")

        # Log additional webhook info
        logger.info(f"Pending update count: {webhook_info.pending_update_count}")
        if webhook_info.last_error_date:
            logger.warning(f"Last error date: {webhook_info.last_error_date}")
            logger.warning(f"Last error message: {webhook_info.last_error_message}")

    except TelegramError as e:
        logger.error(f"Telegram error during webhook setup: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during startup: {e}", exc_info=True)

    logger.info("Bot setup completed")
    return bot_app
    
@router.post("/")
async def webhook_handler(request: Request):
    global bot_app
    # data = await request.json()
    # logger.info(f"Received update: {json.dumps(data, indent=2)}")
    try:
        if bot_app is None:
            logger.error("Bot application not initialized")
            return Response(status_code=500)
        
        data = await request.json()
        logger.debug(f"Webhook data: {data}")
        update = Update.de_json(data, bot_app.bot)
        logger.debug(f"Update object: {update}")
        await bot_app.process_update(update)
        logger.debug("Update processed successfully")
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
    return Response(status_code=200)

logger.info("Bot module loaded")