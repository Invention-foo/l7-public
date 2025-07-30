from sklearn.feature_extraction.text import CountVectorizer
import logging
from fuzzywuzzy import fuzz
from app.services.database import add_blacklisted_user
from app.telegram.llm_interface import llm_check_impersonation, llm_check_spam
from jellyfish import soundex, metaphone
from telegram import Message
from typing import Tuple
import unicodedata
import re
# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Regular expressions for detecting URLs, wallet addresses, and contract addresses
URL_PATTERN = re.compile(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+')
ETH_ADDRESS_PATTERN = re.compile(r'0x[a-fA-F0-9]{40}')
BTC_ADDRESS_PATTERN = re.compile(r'[13][a-km-zA-HJ-NP-Z1-9]{25,34}')

# Add more suspicious top-level domains
SUSPICIOUS_TLDS = {'scam', 'xyz', 'tk', 'ml', 'ga', 'cf', 'gq'}

# Set of suspicious keywords
SUSPICIOUS_KEYWORDS = {
    'airdrop', 'free tokens', 'giveaway', 'claim now', 'exclusive offer',
    'limited time', 'invest now', 'guaranteed returns', 'double your',
    'triple your', '100x', '1000x', 'moon', 'pump', 'dump', 'insider info',
    'secret', 'urgent', 'act now', 'don\'t miss out', 'winner', 'selected',
    'verify wallet', 'validate', 'authenticate', 'prize', 'reward',
    'cryptocurrency giveaway', 'bitcoin', 'ethereum', 'wallet', 'private key',
    'seed phrase', 'password', 'login', 'account', 'ico', 'presale', 'pre-sale',
    'whitelist', 'white-list', 'bonus', 'extra', 'free money', 'get rich',
    'million', 'billion', 'trading bot', 'arbitrage', 'mining', 'staking',
    'yield farming', 'liquidity pool', 'smart contract', 'dex', 'exchange',
    'listing', 'partnership', 'collab', 'announcement', 'ama', 'big news',
    'invest', 'emergency', 'gains', 'giving away', 'free', 'send funds', 'fork'
}


async def extract_message_content(message: Message) -> Tuple[str, str]:
    """
    Extracts content and type from any Telegram message.
    
    Args:
        message: The Telegram message object
        
    Returns:
        Tuple[str, str, bool]: (message_content, message_type, is_forwarded)
        - message_content: The text content or caption of the message
        - message_type: The type of message (text, photo_with_caption, etc.)
        - is_forwarded: Whether the message is forwarded
    """
    message_content = ""
    message_type = "text"  # default type

    logger.error(f"Message attributes: {message}")

    # Handle different message types
    if message.text:
        message_content = message.text
        message_type = "text"
    elif message.caption:
        message_content = message.caption
        message_type = "caption"
        if message.photo:
            message_type = "photo_with_caption"
        elif message.video:
            message_type = "video_with_caption"
        elif message.document:
            message_type = "document_with_caption"
    elif message.photo:
        message_content = "[Photo without caption]"
        message_type = "photo"
    elif message.video:
        message_content = "[Video without caption]"
        message_type = "video"
    elif message.document:
        message_content = f"[Document: {message.document.file_name}]"
        message_type = "document"

    return message_content, message_type

async def ban_user(chat, user_id, full_name, reason, add_to_blacklist=False):
    await chat.ban_member(user_id)
    logger.warning(f"Banned user due to {reason}: ID: {user_id}, Name: {full_name}")

    if add_to_blacklist:
        await add_blacklisted_user(user_id, reason)

async def check_impersonation(sender_name, sender_username, verified_members, chat_title):
    """
    Returns True/False (for impersonation), followed by True/False (for blacklist)
    """
    # Skip impersonation check for short names
    if len(sender_name) < 6:
        return False, False

    sender_name_norm = normalize_name(sender_name)
    sender_username_norm = normalize_name(sender_username) if sender_username else None
    chat_title_norm = normalize_name(chat_title)
    bot_name_norm = normalize_name("AthenaSecure")

    max_similarity = 0
    max_similarity_type = "no_match"

    # Check for bot name impersonation
    bot_name_ratio = max(fuzz.ratio(bot_name_norm, sender_name_norm) / 100,
                         fuzz.partial_ratio(bot_name_norm, sender_name_norm) / 100)
    if bot_name_ratio >= 0.9:
        return True, True

    # Check for chat title impersonation
    chat_title_ratio = max(fuzz.ratio(chat_title_norm, sender_name_norm) / 100,
                           fuzz.partial_ratio(chat_title_norm, sender_name_norm) / 100)
    if chat_title_ratio >= 0.9:
        return True, True

    for member in verified_members:
        verified_name = normalize_name(member.get('telegram_full_name', ''))
        verified_username = normalize_name(member.get('telegram_username', '').lstrip('@'))

        # Skip verification against short names/usernames
        if len(verified_name) < 6 and (not verified_username or len(verified_username) < 6):
            continue

        # High-confidence checks
        if len(verified_name) >= 6 and sender_name_norm == verified_name:
            return True, True
        
        name_ratio = fuzz.ratio(verified_name, sender_name_norm) / 100
        if name_ratio >= 0.95:
            return True, True
        
        if phonetic_similarity(verified_name, sender_name_norm):
            return True, True
        
        if compare_name_components(verified_name, sender_name_norm):
            return True, True

        # Calculate various similarity metrics
        name_partial = fuzz.partial_ratio(verified_name, sender_name_norm) / 100
        name_similarity = max(name_ratio, name_partial)
        
        if name_similarity > max_similarity:
            max_similarity = name_similarity
            max_similarity_type = "name_similarity"

        # Username checks
        if sender_username_norm and verified_username:
            username_ratio = fuzz.ratio(verified_username, sender_username_norm) / 100
            username_partial = fuzz.partial_ratio(verified_username, sender_username_norm) / 100

            # High-confidence checks
            if sender_username_norm == verified_username:
                return True, True
            
            if username_ratio >= 0.95:
                return True, True
            
            if phonetic_similarity(verified_username, sender_username_norm):
                return True, True
            
            if compare_name_components(verified_username, sender_username_norm):
                return True, True

            username_similarity = max(username_ratio, username_partial)
            
            if username_similarity > max_similarity:
                max_similarity = username_similarity
                max_similarity_type = "username_similarity"

        # If similarity is 65% or higher, pass to LLM for final check
        if max_similarity >= 0.65:
            if max_similarity_type == "name_similarity":
                llm_reason, llm_result, llm_confidence, llm_score = await llm_check_impersonation(member.get('telegram_full_name', ''), sender_name)
            
            elif max_similarity_type == "username_similarity":
                llm_reason, llm_result, llm_confidence, llm_score = await llm_check_impersonation(member.get('telegram_username', '').lstrip('@'), sender_username)
            
            if llm_result:
                if int(llm_score) >= 90:
                    logger.warning(f"User {sender_name} being added to blacklist due to impersonation of {member.get('telegram_full_name', '')} with score of {llm_score}")
                    logger.warning(f"User {sender_username} being banned due to impersonation of {member.get('telegram_username', '')} with score of {llm_score}")
                    logger.warning(f"max similarity: {max_similarity}")
                    logger.warning(f"max similarity type: {max_similarity_type}")
                    return True, True 
                elif int(llm_score) >= 69:
                    logger.warning(f"User {sender_name} being banned due to impersonation of {member.get('telegram_full_name', '')} with score of {llm_score}")
                    logger.warning(f"User {sender_username} being banned due to impersonation of {member.get('telegram_username', '')} with score of {llm_score}")
                    logger.warning(f"max similarity: {max_similarity}")
                    logger.warning(f"max similarity type: {max_similarity_type}")
                    return True, False
                else:
                    logger.warning(f"User {sender_name} not being added to blacklist due to impersonation of {member.get('telegram_full_name', '')} with score of {llm_score}")
                    logger.warning(f"User {sender_username} not being banned due to impersonation of {member.get('telegram_username', '')} with score of {llm_score}")
                    logger.warning(f"max similarity: {max_similarity}")
                    logger.warning(f"max similarity type: {max_similarity_type}")
                    return False, False

    return False, False

async def check_spam(message, is_admin, project_info):
    if is_admin:
        logger.warning("Admin message detected, skipping spam check")
        return False, 0

    if len(message) < 120 and len(message) > 20:
        if contains_suspicious_content(message):
            reason, is_spam, score = await llm_check_spam(message, project_info)
            logger.warning(f"Spam check result: {reason}, {is_spam}, {score}")
            return is_spam, score
        else:
            return False, 22
    
    if len(message) >= 120:
        reason, is_spam, score = await llm_check_spam(message, project_info)
        logger.warning(f"Spam check result: {reason}, {is_spam}, {score}")
        return is_spam, score
    
    return False, 0

def compare_name_components(name1, name2):
    # Split names into components, preserving underscores and numbers
    def split_components(name):
        return re.findall(r'[a-z0-9]+|_', name.lower())
    
    components1 = split_components(name1)
    components2 = split_components(name2)
    
    # Check if components are the same, ignoring order
    return set(components1) == set(components2)

def phonetic_similarity(name1, name2):
    soundex_sim = soundex(name1) == soundex(name2)
    metaphone_sim = metaphone(name1) == metaphone(name2)
    ratio = fuzz.ratio(name1, name2)
    return soundex_sim and metaphone_sim and ratio >= 95 and abs(len(name1) - len(name2)) <= 1

def normalize_name(name):
    name = name.lower()
    # Common substitutions
    substitutions = {
        '@': 'a', '4': 'a', 
        '3': 'e',
        '1': 'i', '!': 'i', '|': 'i', 'l': 'i',
        '0': 'o',
        '5': 's', '$': 's',
        '7': 't',
        'vv': 'w',
        'v': 'u',
        'rn': 'm',
        'cl': 'd',
        'nn': 'm',
        # Cyrillic to Latin
        'а': 'a', 'в': 'b', 'с': 'c', 'е': 'e', 'о': 'o', 'р': 'p', 'х': 'x', 'у': 'y',
        'ё': 'e', 'ъ': '', 'ь': '', 'а́': 'a', 'е́': 'e', 'и́': 'i', 'о́': 'o', 'у́': 'u',
        'ы́': 'y', 'э́': 'e', 'ю́': 'yu', 'я́': 'ya'
    }
    fancy_char_map = {
        '𝓔': 'e', '𝓬': 'c', '𝓱': 'h', '𝓸': 'o', '𝓞': 'o', '𝓣': 't', '𝓓': 'd',
    }

    # Replace fancy Unicode characters with regular ones
    for fancy_char, normal_char in fancy_char_map.items():
        name = name.replace(fancy_char, normal_char)
    
    # Apply substitutions
    for char, replacement in substitutions.items():
        name = name.replace(char, replacement)
    
    # Normalize Unicode characters
    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('utf-8')
    
    # Remove non-ASCII characters
    name = re.sub(r'[^\x00-\x7F]+', '', name)
    
    # Remove any remaining non-alphabetic characters
    name = re.sub(r'[^a-z]', '', name)
    
    return name

def n_gram_similarity(name1, name2, n=2):
    vectorizer = CountVectorizer(analyzer='char', ngram_range=(n, n))
    all_ngrams = vectorizer.fit_transform([name1, name2])
    ngram_matrix = all_ngrams.toarray()
    
    # Calculate Jaccard similarity
    intersection = ngram_matrix[0] & ngram_matrix[1]  # Common n-grams
    union = ngram_matrix[0] | ngram_matrix[1]  # Total unique n-grams
    return intersection.sum() / union.sum() if union.sum() != 0 else 0

def contains_suspicious_content(message):
    # Convert message to lowercase for case-insensitive matching
    lower_message = message.lower()
    
    # Check for URLs
    urls = URL_PATTERN.findall(lower_message)
    if urls:
        for url in urls:
            # Check if the URL contains suspicious TLDs
            if any(url.endswith('.' + tld) for tld in SUSPICIOUS_TLDS):
                return True
            # Check if the URL contains suspicious keywords
            if any(keyword in url for keyword in SUSPICIOUS_KEYWORDS):
                return True
    
    # Check for crypto addresses
    if ETH_ADDRESS_PATTERN.search(message) or BTC_ADDRESS_PATTERN.search(message):
        return True
    
    # Check for suspicious keywords
    words = re.findall(r'\b\w+\b', lower_message)
    if any(keyword in words for keyword in SUSPICIOUS_KEYWORDS):
        return True
    
    # Check for two-word phrases
    two_word_phrases = [' '.join(words[i:i+2]) for i in range(len(words)-1)]
    if any(keyword in two_word_phrases for keyword in SUSPICIOUS_KEYWORDS):
        return True
    
    return False
