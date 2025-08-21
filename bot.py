import logging
import os
import re
import asyncio
from telegram import Update, InputMediaPhoto
from telegram.ext import Application, MessageHandler, filters, CallbackContext
from bs4 import BeautifulSoup
import requests
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv('BOT_TOKEN', '8465346144:AAG9x6C3OCOpUhVz3-qEK1wBlACOdb0Bz_s')

class PinDetector:
    def __init__(self):
        self.pin_regex = re.compile(r'\b\d{6}\b')

    def detect_pin(self, text):
        match = self.pin_regex.search(text)
        return match.group(0) if match else '110001'

    def detect_sizes(self, text):
        size_regex = re.compile(r'\b(S|M|L|XL|XXL|\d{2}-\d{2})\b', re.IGNORECASE)
        sizes = size_regex.findall(text)
        if sizes:
            return ', '.join(set(s.upper() for s in sizes))
        return 'All'

class ResponseBuilder:
    def __init__(self):
        self.ecommerce_domains = ['amazon', 'flipkart', 'meesho', 'myntra', 'ajio', 'snapdeal']

    def is_ecommerce(self, url):
        domain = urlparse(url).netloc.lower()
        return any(d in domain for d in self.ecommerce_domains)

    def is_meesho(self, url):
        return 'meesho' in urlparse(url).netloc.lower()

    def build_response(self, title, price, url, is_meesho=False, sizes='All', pin='110001'):
        price_str = f'@{price} rs' if price else '@ rs'
        response = f"{title} {price_str}\n{url}\n"
        if is_meesho:
            response += f"Size - {sizes}\nPin - {pin}\n"
        response += "\n@reviewcheckk"
        return response

async def handle_message(update: Update, context: CallbackContext):
    message = update.message
    text = message.text or message.caption or ''
    photos = message.photo

    # Extract URLs
    url_regex = re.compile(r'https?://[^\s]+')
    urls = url_regex.findall(text)

    if not urls:
        if photos:
            await message.reply_photo(photo=photos[-1].file_id, caption="No title provided", parse_mode=None)
        else:
            await message.reply_text("❌ Unsupported or invalid product link", parse_mode=None)
        return

    resolver = URLResolver()
    cleaner = TitleCleaner()
    pin_detector = PinDetector()
    builder = ResponseBuilder()

    for url in urls:
        try:
            clean_url = await resolver.unshorten_and_clean(url)
            logger.info(f"Unshortened and cleaned URL: {clean_url}")

            if not builder.is_ecommerce(clean_url):
                await message.reply_text("❌ Unsupported or invalid product link", parse_mode=None)
                continue

            # Fetch page content
            try:
                response = await asyncio.to_thread(requests.get, clean_url, headers={'User-Agent': resolver.user_agent}, timeout=3)
                html = response.text
                soup = BeautifulSoup(html, 'html.parser')

                # Extract title
                og_title = soup.find('meta', property='og:title')
                title_tag = soup.title
                h1 = soup.find('h1')

                raw_title = (og_title['content'] if og_title else '') or (title_tag.string if title_tag else '') or (h1.text if h1 else '')
                if not raw_title:
                    raw_title = urlparse(clean_url).path.replace('/', ' ').replace('-', ' ').strip()

                title = cleaner.clean_title(raw_title, clean_url)
                logger.info(f"Cleaned title: {title}")

                # Extract price: message first
                price = cleaner.extract_price(text, html)

                # Meesho specifics
                is_meesho = builder.is_meesho(clean_url)
                sizes = pin_detector.detect_sizes(text) if is_meesho else ''
                pin = pin_detector.detect_pin(text) if is_meesho else ''

                # Build response
                resp_text = builder.build_response(title, price, clean_url, is_meesho, sizes, pin)

                if photos:
                    await message.reply_photo(photo=photos[-1].file_id, caption=resp_text, parse_mode=None)
                else:
                    await message.reply_text(resp_text, parse_mode=None)

            except Exception as e:
                logger.error(f"Error fetching page: {e}")
                await message.reply_text("❌ Unable to extract product info", parse_mode=None)

        except Exception as e:
            logger.error(f"Error processing URL {url}: {e}")
            await message.reply_text("❌ Unable to extract product info", parse_mode=None)

def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))
    application.run_polling()

if __name__ == '__main__':
    main()
