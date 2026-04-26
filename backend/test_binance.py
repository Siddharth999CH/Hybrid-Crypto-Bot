import os
import ccxt
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
SECRET_KEY = os.getenv("BINANCE_SECRET")

print("\n" + "="*50)
print("🏦 INITIATING BINANCE TESTNET CONNECTION...")

try:
    # 1. Initialize the Exchange Engine
    exchange = ccxt.binance({
        'apiKey': API_KEY,
        'secret': SECRET_KEY,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'future', # We need futures to go 'Short' and use Leverage
        }
    })
    
    # 2. CRITICAL: Turn on Sandbox (Testnet) Mode
    exchange.set_sandbox_mode(True) 
    
    # 3. Request Account Balance
    print("📡 Pinging Binance servers...")
    balance = exchange.fetch_balance()
    
    # Find the USDT balance
    usdt_balance = balance['total'].get('USDT', 0)
    
    print("\n✅ CONNECTION SECURED!")
    print(f"💰 Available Play Money: ${usdt_balance} USDT")
    print("="*50)

except ccxt.AuthenticationError:
    print("\n❌ AUTHENTICATION FAILED: Your API keys are incorrect or invalid.")
except Exception as e:
    print(f"\n❌ CONNECTION FAILED: {e}")