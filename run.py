import signal
import threading

from dotenv import load_dotenv

load_dotenv()

from publisher import S3Publisher
from dataFeed.impl.CoinbaseDataFeed import CoinbaseDataFeed

publisher = S3Publisher(prefix="market-data")

feeds = [
    CoinbaseDataFeed(publisher=publisher, on_tick=lambda t: print(t)),
]

for feed in feeds:
    print(f"Starting {feed.name}...")
    feed.start()

# Block until Ctrl+C
shutdown = threading.Event()
signal.signal(signal.SIGINT, lambda *_: shutdown.set())
shutdown.wait()

for feed in feeds:
    print(f"Stopping {feed.name}...")
    feed.stop()
print("Done.")
