# Contributing

LabCouncil has a standard-library local meeting platform with default simulation and an opt-in real-model synthetic case. Start with [the project plan](docs/PLAN.md) and [running instructions](docs/RUNNING.md).

Useful early contributions include a concrete computational research use case, an evaluation protocol, a meeting interface proposal, or a small runtime integration experiment.

For a design change, explain the user problem, the affected part of the research loop, and how the behavior can be checked. For an implementation, include a reproducible example and appropriate validation. Label simulated outputs clearly and distinguish completed work from planned capabilities.

Preserve source references and artifact provenance. Keep API credentials, private research data, runtime logs, and generated experimental outputs outside version control. Reference upstream code and its license when reusing it.

Use `codex/` as the default prefix for new development branches. Keep changes focused on one milestone and update the plan when its assumptions change.

Run `python3 -m unittest discover -s tests -v` and `node --check labcouncil/static/app.js` for changes to the local application. CI checks Python 3.11 and 3.14 without model credentials. Reproduction records may include audited synthetic outputs; clearly label fixtures, actual model responses, source changes and incomplete validations.
