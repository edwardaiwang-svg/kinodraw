# Five showcase sources

These editable scripts preserve the original five required genres. `catalog.json`
labels their status and interpretation. The story, product, transport figures and
events are fictional. The multiplication example is an instructional illustration.
The lion source still says “Mara and the other lionesses”; a visual showcase may
use the requested tigress treatment without silently rewriting that narration.

From an installed source environment at the repository root:

```sh
python -m kinodraw.cli make examples/showcases/explainer.md -o projects/explainer --director rules --director-v3
```

Replace `explainer` with `lion`, `product-launch`, `lesson`, or `news`. Choose fresh
output directories. These full pipeline commands may download voice/search models
on first use; they use local rules, not an AI provider. A saved, reviewed AI plan
can produce a different treatment; the source script alone does not promise the
same frames as a previously rendered showcase. See [developer tools](../../docs/developer.md)
for confined offline preview and narrated MCP modes, and [scientific examples](../scientific/README.md)
for real observations and explicit analytical models.

There are no claimed final videos in this source folder. Package accepted outputs
with [the local gallery helper](../../docs/launch-kit/README.md).
