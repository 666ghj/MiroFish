"""
MiroFish Backend startup entry point
"""

import os
import sys

# Fix non-ASCII output garbling on the Windows console: set UTF-8 encoding before any imports.
if sys.platform == 'win32':
    # Set the environment variable to force Python to use UTF-8.
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    # Reconfigure standard output streams as UTF-8.
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Add the project root directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.config import Config


def main():
    """Main function"""
    # Validate configuration
    errors = Config.validate()
    if errors:
        print("Configuration error:")
        for err in errors:
            print(f"  - {err}")
        print("\nPlease check the configuration in your .env file")
        sys.exit(1)

    # Create the application
    app = create_app()

    # Get runtime configuration
    host = os.environ.get('FLASK_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_PORT', 5001))
    debug = Config.DEBUG

    # Start the service
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == '__main__':
    main()
