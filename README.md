# plueprint
[API Blueprint](https://github.com/apiaryio/api-blueprint) parser written in Python.
It uses [Markdown](https://pythonhosted.org/Markdown) well-known package to do
initial DOM parsing.

### Installing
```
pip install plueprint
```

### Using
As a library:
```Python
from markdown import Markdown
m = Markdown(extensions=["plueprint"])
m.set_output_format("apiblueprint")
api = m.convert("""
FORMAT: 1A

# The Simplest API
This is one of the simplest APIs written in the **API Blueprint**.

# /message

## GET
+ Response 200 (text/plain)

        Hello World!
""")
print(api)
```
As a script:
```
python -m plueprint "Real World API.md"
python -m plueprint "Real World API.md" -o "api.pickle"
```

### Notes
To suppress warnings about parsed documents, set `plueprint.entities.report_warnings` to `False`.

Released under New BSD license.
