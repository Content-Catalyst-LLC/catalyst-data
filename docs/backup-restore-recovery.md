# Backup, Restore, and Recovery Procedure

1. Run `catalyst-data status DATABASE` and resolve integrity or migration errors.
2. Create a verified backup with `backup-create`.
3. Store both the SQLite file and its `.manifest.json` sidecar outside the live repository directory.
4. Test the backup with `backup-verify`.
5. Restore to a separate path first. Confirm record counts, migration version, and critical workflows.
6. Use `--force` only when intentionally replacing an existing repository. Catalyst Data creates a timestamped pre-restore safety copy.
7. Retain installer-created source backups until the upgraded release has passed institutional validation.

A restore automatically migrates an older supported backup to the current schema. The original backup remains unchanged.
