import os
import asyncio
from dotenv import load_dotenv
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

# Load the .env file
load_dotenv()

# Extract the keys and aggressively strip any invisible characters or accidental quotes
raw_api_id = os.getenv("TELEGRAM_API_ID", "")
raw_api_hash = os.getenv("TELEGRAM_API_HASH", "")

API_ID = raw_api_id.strip(' "\'\n\r\t')
API_HASH = raw_api_hash.strip(' "\'\n\r\t')

# Forensic Debugging
print(f"\n--- Forensic API Key Check ---")
print(f"API_ID:  [{API_ID}]")
print(f"API_HASH:[{API_HASH}]")
print(f"Hash Length: {len(API_HASH)} characters")
print(f"------------------------------")

if len(API_HASH) != 32:
    print("❌ STOP! Your API_HASH is corrupted.")
    print("A Telegram Hash must be EXACTLY 32 characters long.")
    print("Go back to my.telegram.org and copy it again carefully.")
    exit()

async def main():
    print(f"\nStarting Telegram Login...")
    
    client = TelegramClient(StringSession(''), int(API_ID), API_HASH)
    
    await client.start()
    
    print("\n" + "="*50)
    print("✅ LOGIN SUCCESSFUL!")
    print("Copy the long string below and paste it into your .env file:\n")
    print(client.session.save())
    print("\n" + "="*50)
    
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())