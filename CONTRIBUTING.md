# Contribute to Tagalog singing development

Help advance the [roadmap](ROADMAP.md) toward fluent Tagalog singing. Useful contributions include reproducible failures, tested model integration, pronunciation benchmarks, permitted-data tooling, and primary-source resource corrections.

## Use pull requests

Jessica/Codex is the designated maintainer and has the owner's standing permission to merge its verified changes into `main` after applicable checks pass. Other contributors must submit pull requests and must not update `main` directly. A pull request is also the preferred reviewable path for the maintainer's work.

Follow the repository's review and CI requirements. Do not bypass branch protections, force-push shared history, or merge another contributor's work solely because it builds. Review its intended behavior and material side effects before merging.

## Show the result

Keep changes small and describe the concrete problem, resulting behavior, validation, and remaining limits in the pull request. Reuse existing helpers and include original synthetic fixtures for tooling changes. Run the regression suite from a checkout:

```sh
python -m unittest discover -s tests -v
```

Run the relevant [README examples](README.md) for the changed command. Model or language-quality claims need evidence from the actual evaluated inputs and outputs; a metadata pass does not establish fluent singing.

## Preserve permissions and private material

Do not include private recordings, third-party song lyrics, credentials, internal project records, or restricted datasets and weights in commits or attachments. Cite primary sources for resource permissions and keep code, data, recording, and voice-use terms distinct. New spending and use or publication of a person's voice need the applicable authority before execution.
