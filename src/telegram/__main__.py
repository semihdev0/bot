"""Allow running as: python -m src.telegram"""

from src.telegram.main import main

import asyncio

asyncio.run(main())
