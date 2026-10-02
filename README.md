# Chess-Fox

## Persistent accounts

Accounts and win/loss/draw totals are stored in SQLite in `chess_fox.sqlite3` by default. Set `DATABASE_PATH` to choose another database file. For hosted deployments, point it at a persistent disk; files on an ephemeral filesystem are lost when the host replaces the instance.

Set `SECRET_KEY` to a stable, private value in the hosting environment so signed-in sessions remain valid after restarts. If it is not set, the app generates a new key when it starts.