# commands/__init__.py
"""
Commands package for LoanCentral bot

This package contains all the command modules that handle different bot commands.
Each command module should have:
1. A COMMAND_TRIGGER constant defining the trigger text
2. A process_*_command function that takes only a comment parameter
3. Any necessary imports done inside the function to avoid circular imports
"""

__version__ = "1.0.0"
__author__ = "LoanCentral Bot"

# You can add any shared utilities or constants here if needed
# For example:
# COMMON_ERROR_MESSAGE = "An error occurred processing your request. Please try again later."