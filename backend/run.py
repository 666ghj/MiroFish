"""
GTM Simulation Lab backend Entry Point
"""

import os
import sys

# Fix garbled output in Windows console: set UTF-8 encoding before all other imports
if sys.platform == 'win32':
    # Set environment variable to ensure Python uses UTF-8
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    # Reconfigure standard output streams to UTF-8
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Add project root directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.config import Config


def main():
    """Main function"""
    # Validate configuration
    errors = Config.validate()
    if errors:
        print("Configuration errors:")
        for err in errors:
            print(f"  - {err}")
        print("\nPlease check the configuration in your .env file")
        sys.exit(1)

    # Create application
    app = create_app()

    # Get runtime configuration
    host = os.environ.get('FLASK_HOST', '0.0.0.0')
    # Render (and most PaaS) injects PORT; FLASK_PORT is the local dev override
    port = int(os.environ.get('PORT') or os.environ.get('FLASK_PORT', 5001))
    debug = Config.DEBUG

    # Start server
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == '__main__':
    main()
