# Code Standards Reference

## Naming Conventions
- **camelCase**: methods, functions, variables
- **PascalCase**: classes, interfaces
- **kebab-case**: files, directories

## Code Rules
- All code in English (variables, functions, classes, comments)
- No abbreviations, no names over 30 characters
- No magic numbers — use named constants
- Functions start with a verb, perform single clear action
- Maximum 3 parameters per function (use objects for more)
- Functions do mutation OR query, never both
- Maximum 2 nesting levels for conditionals, prefer early returns
- Never use boolean flag parameters to toggle behavior
- Maximum 50 lines per method
- Maximum 300 lines per class
- No blank lines within methods/functions
- Avoid comments — code should be self-explanatory
- One variable per line, declare close to usage
