from jose import jwt
from dotenv import load_dotenv
import os
import time

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))

if __name__ == "__main__":
    token = jwt.encode(
        {
            'service': 'backend',
            'exp': int(time.time()) + 3600
        },
        os.getenv('NUTRITRACK_API_KEY'),
        algorithm='HS256'
    )
    print(token)