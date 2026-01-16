#!/usr/bin/env python3
"""
Text Reader for Live Fact-Checking

Reads article text and headline, sends to backend for claim extraction.
Bypasses audio transcription - for use with news articles, press releases, etc.

Usage:
    # Interactive mode - prompts for headline, publication date, then article text
    python reader.py

    # Pipe article text, prompts only for headline and date
    cat article.txt | python reader.py

    # Pipe from clipboard (macOS), prompts for headline and date
    pbpaste | python reader.py

    # Use environment variables for non-interactive usage
    HEADLINE="My Article" PUBLICATION_DATE="Januar 2025" cat article.txt | python reader.py
"""

import sys
import os
from datetime import datetime
import requests

# Backend configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:5000")
TEXT_ENDPOINT = f"{BACKEND_URL}/api/text-block"


def get_tty_input(prompt: str, env_var: str = None) -> str:
    """Get input from user, handling piped stdin by reading from /dev/tty."""
    # Check for environment variable first
    if env_var:
        env_value = os.getenv(env_var)
        if env_value:
            print(f"Using {env_var} from environment: {env_value}")
            return env_value

    # Save stdin state for text reading
    saved_stdin = None
    if not sys.stdin.isatty():
        saved_stdin = sys.stdin
        try:
            sys.stdin = open('/dev/tty', 'r')
        except OSError:
            print(f"Error: Cannot prompt when stdin is piped.")
            print(f"Please provide as environment variable: {env_var}='...' python reader.py")
            sys.exit(1)

    print(prompt)
    value = input("> ").strip()

    # Restore stdin if we changed it
    if saved_stdin:
        sys.stdin.close()
        sys.stdin = saved_stdin

    return value


def read_headline() -> str:
    """Prompt for article headline."""
    return get_tty_input("Enter article headline (one line):", "HEADLINE")


def read_publication_date() -> str:
    """Prompt for publication date, default to current month/year."""
    default_date = datetime.now().strftime("%B %Y")

    # Check env var first
    env_date = os.getenv("PUBLICATION_DATE")
    if env_date:
        print(f"Using PUBLICATION_DATE from environment: {env_date}")
        return env_date

    date_input = get_tty_input(f"Enter publication date (default: {default_date}):")
    return date_input if date_input else default_date


def read_text():
    """Read article text from stdin or interactive input"""
    if not sys.stdin.isatty():
        # Piped input - read all of it
        return sys.stdin.read()
    else:
        # Interactive multiline input
        print("\nPaste article text below (press Ctrl+D when done):")
        print("-" * 50)
        lines = []
        try:
            while True:
                lines.append(input())
        except EOFError:
            pass
        return '\n'.join(lines)


def send_to_backend(text: str, headline: str, publication_date: str):
    """Send text, headline, and publication date to backend for claim extraction"""
    try:
        response = requests.post(
            TEXT_ENDPOINT,
            json={
                'text': text,
                'headline': headline,
                'publication_date': publication_date
            },
            timeout=30
        )

        if response.ok:
            result = response.json()
            print(f"\n{'='*50}")
            print(f"Sent successfully!")
            print(f"Status: {result.get('status')}")
            print(f"Message: {result.get('message')}")
            print(f"Source ID: {result.get('source_id')}")
            print(f"{'='*50}")
            return True
        else:
            print(f"\nError: {response.status_code}")
            try:
                error = response.json()
                print(f"Details: {error.get('error', response.text)}")
            except:
                print(f"Details: {response.text}")
            return False

    except requests.exceptions.ConnectionError:
        print(f"\nError: Cannot connect to backend at {BACKEND_URL}")
        print("Make sure the backend is running: cd backend && python app.py")
        return False
    except requests.exceptions.Timeout:
        print("\nError: Request timed out")
        return False
    except Exception as e:
        print(f"\nError: {e}")
        return False


def main():
    print("""
╔══════════════════════════════════════════════════════════════╗
║  Text Reader for Fact-Checking                               ║
╠══════════════════════════════════════════════════════════════╣
║  Sends article text directly for claim extraction            ║
║  (bypasses audio transcription)                              ║
╚══════════════════════════════════════════════════════════════╝
    """)
    print(f"Backend: {BACKEND_URL}")

    # Read headline (always interactive prompt unless HEADLINE env var set)
    headline = read_headline()
    if not headline:
        print("\nWarning: No headline provided (using empty string as context)")

    # Read publication date (defaults to current month/year)
    publication_date = read_publication_date()

    # Read article text
    text = read_text()

    if not text or not text.strip():
        print("\nError: No text provided")
        sys.exit(1)

    # Summary before sending
    print(f"\n{'='*50}")
    print(f"Headline: {headline or '(none)'}")
    print(f"Publication date: {publication_date}")
    print(f"Text length: {len(text)} characters")
    print(f"Text preview: {text[:100]}..." if len(text) > 100 else f"Text: {text}")
    print(f"{'='*50}")

    # Send to backend
    success = send_to_backend(text, headline, publication_date)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
