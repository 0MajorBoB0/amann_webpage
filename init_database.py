#!/usr/bin/env python3
"""
Helper script to initialize the database with environment variables
"""
import os

# Load environment variables from .env file
env_file = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key] = value

# Now import and run init_db
from app import init_db

if __name__ == '__main__':
    print("Initializing database tables...")
    init_db()
    print("Database tables created successfully!")
