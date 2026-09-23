"""Split a SQL script into individual statements.

Shared by the bot's startup schema check (main.py) and the migration runner
(scripts/run_migrations.py). Both used to split on ";" by hand, and main.py's
version also dropped any statement that had a comment above it. On the
project's schema.sql that meant 17 of 19 tables were never created, and two
comments containing semicolons ("...audit_events; tracks dashboard mod
actions)") became statements of their own — syntax errors that made
init_database() fail and the bot exit on startup.

This splitter understands line comments, single-quoted strings and
dollar-quoted blocks, so a semicolon inside any of them does not end a
statement.
"""


def split_sql(sql_text):
    """Split on statement-terminating semicolons, respecting quoting.

    Migration 013 uses a `DO $$ ... $$` block whose body contains semicolons. A
    naive line-based split tore those blocks apart and fed Postgres fragments.
    """
    statements, current = [], []
    in_single = in_dollar = False
    dollar_tag = ""
    i, length = 0, len(sql_text)

    while i < length:
        char = sql_text[i]

        if in_single:
            current.append(char)
            if char == "'":
                # '' is an escaped quote, not a terminator.
                if i + 1 < length and sql_text[i + 1] == "'":
                    current.append(sql_text[i + 1])
                    i += 2
                    continue
                in_single = False
            i += 1
            continue

        if in_dollar:
            current.append(char)
            if sql_text.startswith(dollar_tag, i):
                current.append(sql_text[i + 1:i + len(dollar_tag)])
                i += len(dollar_tag)
                in_dollar = False
                continue
            i += 1
            continue

        # Line comment outside any quoting.
        if char == "-" and sql_text.startswith("--", i):
            end = sql_text.find("\n", i)
            i = length if end == -1 else end + 1
            continue

        if char == "'":
            in_single = True
            current.append(char)
            i += 1
            continue

        if char == "$":
            end = sql_text.find("$", i + 1)
            if end != -1 and sql_text[i + 1:end].replace("_", "").isalnum() or (
                    end == i + 1):
                dollar_tag = sql_text[i:end + 1]
                in_dollar = True
                current.append(dollar_tag)
                i = end + 1
                continue

        if char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            i += 1
            continue

        current.append(char)
        i += 1

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements
