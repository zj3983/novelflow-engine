"""Package marker for the ``scripts`` directory.

The directory lives at the project root so ``python -m
scripts.migrate_modular_story_state`` and ``python -m
scripts.smoke_modular_pipeline`` can find the
``packages.story_core`` import the smoke script needs.
Without this marker ``python -m`` treats the script as a
top-level module and cannot resolve its imports.

The scripts are intentionally not part of the runtime
package — they are operator-facing entry points that the
README documents as ``python -m scripts.<name>``.
"""
