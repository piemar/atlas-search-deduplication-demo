#!/usr/bin/env python3
"""
Customer Duplicate Detection Web Application Launcher
"""

import os
import sys
import logging
from waitress import serve
from app import app, init_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    """Main entry point for the web application"""
    
    # Check if .env file exists
    env_file = '.env'
    if not os.path.exists(env_file):
        logger.error("❌ No .env file found!")
        logger.error("Please copy env.example to .env and configure your MongoDB connection:")
        logger.error("  cp env.example .env")
        logger.error("  # Edit .env with your MongoDB Atlas credentials")
        sys.exit(1)
    
    # Initialize database connection
    logger.info("🔗 Initializing database connection...")
    if not init_db():
        logger.error("❌ Failed to initialize database connection")
        logger.error("Please check your MongoDB connection settings in .env")
        sys.exit(1)
    
    # Determine run mode
    development_mode = os.getenv('FLASK_ENV') == 'development' or '--dev' in sys.argv
    port = int(os.getenv('PORT', 6000))
    host = os.getenv('HOST', '0.0.0.0')
    
    if development_mode:
        logger.info("🚀 Starting web application in DEVELOPMENT mode...")
        logger.info(f"🌐 Open your browser to: http://localhost:{port}")
        logger.info("📝 Use Ctrl+C to stop the server")
        app.run(debug=True, host=host, port=port)
    else:
        logger.info("🚀 Starting web application in PRODUCTION mode...")
        logger.info(f"🌐 Server running on: http://{host}:{port}")
        logger.info("📝 Use Ctrl+C to stop the server")
        serve(app, host=host, port=port)

if __name__ == '__main__':
    main()
