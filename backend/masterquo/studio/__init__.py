"""Pepe Data & Training Studio (1.33) - separate application (own process, port, data directory, queue, logs) that exports the data of
ONE concrete model task, validates it, builds the model's dataset, trains / fits / calibrates with the model's real trainer, checks the
artifact with the bot's loader and transfers it to the bot's registry as a candidate (SHADOW). It never sends, modifies or closes
orders and never starts the bot's Runtime."""
